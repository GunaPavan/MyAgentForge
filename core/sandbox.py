"""Sandboxed code execution.

Two backends:
- subprocess (default, works everywhere including HF Spaces)
- Docker (auto-detected if /var/run/docker.sock exists)

Hard limits enforced:
- Wall-clock timeout (default 10s)
- Output truncated to 4KB stdout + 4KB stderr
- On Linux subprocess: RLIMIT_CPU, RLIMIT_AS, RLIMIT_NPROC, RLIMIT_FSIZE
- On Docker: --network none, --read-only (except /tmp), --memory, --pids-limit, --user

Designed for short, deterministic tests of LLM-generated code. Not a general-purpose
sandbox — assume the code being run is malicious-by-default and act accordingly.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from typing import Optional


MAX_OUTPUT = 4096          # bytes of stdout/stderr to capture
DEFAULT_TIMEOUT = 10       # wall-clock seconds
MAX_TIMEOUT = 30           # absolute hard cap
MEM_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MB
CPU_LIMIT_SECONDS = 10
FILE_SIZE_LIMIT = 10 * 1024 * 1024   # 10 MB
PROC_LIMIT = 8


@dataclass
class ExecutionResult:
    backend: str           # "subprocess" or "docker"
    exit_code: int         # -1 = timeout, -2 = sandbox error
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    passed: bool           # convenience: exit_code == 0 and not timed_out

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------- Backend detection -----------------------------

_docker_available_cache: Optional[bool] = None


def _docker_available() -> bool:
    """Check if Docker is usable for sandboxing. Cached after first call."""
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache

    # On Linux Docker socket lives here; on macOS it's also here when Docker Desktop runs
    if not os.path.exists("/var/run/docker.sock"):
        _docker_available_cache = False
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, timeout=2, check=True, text=True,
        )
        _docker_available_cache = bool(result.stdout.strip())
        return _docker_available_cache
    except Exception:
        _docker_available_cache = False
        return False


# ----------------------------- File staging -----------------------------

# Safe path: must be a basename + simple extension, no traversal
_SAFE_FILENAME_RE = __import__("re").compile(r"^[A-Za-z0-9_\-.][A-Za-z0-9_\-./]{0,200}$")


def _stage_files(files: dict[str, str], tmpdir: str) -> list[str]:
    """Write each file into tmpdir, returning the absolute paths created.
    Rejects unsafe filenames (path traversal, absolute paths)."""
    written = []
    for fname, content in files.items():
        # Sanitize: only basenames allowed at top level; nested dirs allowed but never ".."
        safe = fname.strip().replace("\\", "/")
        if not safe or safe.startswith("/") or ".." in safe.split("/"):
            continue  # silently skip; reviewer/parser should have caught earlier
        if not _SAFE_FILENAME_RE.match(safe.replace("/", "_")):
            continue
        target = os.path.normpath(os.path.join(tmpdir, safe))
        # Final guard: must remain under tmpdir
        if not target.startswith(os.path.normpath(tmpdir) + os.sep):
            continue
        os.makedirs(os.path.dirname(target) or tmpdir, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(str(content))
        written.append(target)
    return written


def _pick_python_entrypoint(files: dict[str, str], hint: Optional[str]) -> Optional[str]:
    """Choose which file to run. Priority: explicit hint > test_*.py > main/app/run.py > single .py file."""
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return None
    if hint and hint in files and hint.endswith(".py"):
        return hint
    for cand in ("test_main.py", "tests.py", "test.py"):
        if cand in files:
            return cand
    for cand in ("main.py", "app.py", "run.py", "__main__.py"):
        if cand in files:
            return cand
    # First non-test file
    for f in py_files:
        if not f.startswith("test_"):
            return f
    return py_files[0]


# ----------------------------- subprocess backend -----------------------------

def _apply_unix_rlimits():
    """Called inside the child process on POSIX systems (preexec_fn)."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS))
        resource.setrlimit(resource.RLIMIT_AS, (MEM_LIMIT_BYTES, MEM_LIMIT_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT, FILE_SIZE_LIMIT))
        resource.setrlimit(resource.RLIMIT_NPROC, (PROC_LIMIT, PROC_LIMIT))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        # Best-effort on non-Linux POSIX
        pass


async def _run_subprocess(
    files: dict[str, str],
    entrypoint: str,
    timeout: int,
) -> ExecutionResult:
    """Run Python file in a subprocess with timeout + resource limits."""
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="maf_sbx_") as tmpdir:
        _stage_files(files, tmpdir)
        entry_path = os.path.normpath(os.path.join(tmpdir, entrypoint))
        if not os.path.exists(entry_path):
            return ExecutionResult(
                backend="subprocess", exit_code=-2,
                stdout="", stderr=f"Sandbox error: entrypoint '{entrypoint}' not found",
                duration_ms=int((time.time() - started) * 1000),
                timed_out=False, passed=False,
            )

        # Minimal env — strip proxies, PATH, etc.
        env = {
            "PATH": "/usr/bin:/bin" if os.name == "posix" else os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "HOME": tmpdir,
            "TMPDIR": tmpdir,
        }

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": tmpdir,
            "env": env,
        }

        if os.name == "posix":
            kwargs["preexec_fn"] = _apply_unix_rlimits
            kwargs["start_new_session"] = True  # so we can kill the whole process group

        try:
            # Note: we deliberately do NOT use -I (isolated mode) — that strips the
            # script's directory from sys.path, breaking multi-file projects.
            # Security comes from resource limits + minimal env, not from -I.
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-s", entry_path,  # -s = no user site-packages
                **kwargs,
            )
        except Exception as e:
            return ExecutionResult(
                backend="subprocess", exit_code=-2,
                stdout="", stderr=f"Sandbox error: failed to spawn: {e!s}"[:MAX_OUTPUT],
                duration_ms=int((time.time() - started) * 1000),
                timed_out=False, passed=False,
            )

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            # Kill the entire process group (cleans up forked children)
            try:
                if os.name == "posix":
                    import signal
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except Exception:
                pass
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=2)
            except Exception:
                stdout_b, stderr_b = b"", b""
            exit_code = -1

        duration_ms = int((time.time() - started) * 1000)

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT]
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT]
    if len(stdout_b or b"") > MAX_OUTPUT:
        stdout += "\n... (truncated)"
    if len(stderr_b or b"") > MAX_OUTPUT:
        stderr += "\n... (truncated)"

    return ExecutionResult(
        backend="subprocess",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        passed=(exit_code == 0 and not timed_out),
    )


# ----------------------------- Docker backend -----------------------------

async def _run_docker(
    files: dict[str, str],
    entrypoint: str,
    timeout: int,
) -> ExecutionResult:
    """Run code inside a throwaway python container. Maximum isolation."""
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="maf_dbx_") as tmpdir:
        _stage_files(files, tmpdir)
        entry_path = os.path.join(tmpdir, entrypoint)
        if not os.path.exists(entry_path):
            return ExecutionResult(
                backend="docker", exit_code=-2,
                stdout="", stderr=f"Sandbox error: entrypoint '{entrypoint}' not found",
                duration_ms=int((time.time() - started) * 1000),
                timed_out=False, passed=False,
            )

        # Use absolute path inside container
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:size=64m,mode=1777",
            "--memory", f"{MEM_LIMIT_BYTES}",
            "--memory-swap", f"{MEM_LIMIT_BYTES}",
            "--cpus", "0.5",
            "--pids-limit", str(PROC_LIMIT),
            "--user", "1000:1000",
            "--workdir", "/sandbox",
            "-v", f"{tmpdir}:/sandbox:ro",
            "--env", "PYTHONIOENCODING=utf-8",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONUNBUFFERED=1",
            "--env", "HOME=/tmp",
            "python:3.11-slim",
            "python", "-s", f"/sandbox/{entrypoint}",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            return ExecutionResult(
                backend="docker", exit_code=-2,
                stdout="", stderr=f"Sandbox error: docker spawn failed: {e!s}"[:MAX_OUTPUT],
                duration_ms=int((time.time() - started) * 1000),
                timed_out=False, passed=False,
            )

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except Exception:
                pass
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=2)
            except Exception:
                stdout_b, stderr_b = b"", b""
            exit_code = -1

        duration_ms = int((time.time() - started) * 1000)

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT]
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")[:MAX_OUTPUT]

    return ExecutionResult(
        backend="docker",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timed_out=timed_out,
        passed=(exit_code == 0 and not timed_out),
    )


# ----------------------------- Public API -----------------------------

async def run_code(
    files: dict[str, str],
    entrypoint: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    prefer_docker: bool = True,
) -> ExecutionResult:
    """Run Python files in a sandbox.

    Args:
        files: filename -> source code map
        entrypoint: filename to execute (defaults to test_main.py / main.py / first .py)
        timeout: wall-clock seconds (capped at MAX_TIMEOUT)
        prefer_docker: if True and Docker is available, use Docker backend

    Returns:
        ExecutionResult with exit_code, stdout, stderr, duration_ms, etc.
    """
    if not isinstance(files, dict) or not files:
        return ExecutionResult(
            backend="none", exit_code=-2, stdout="", stderr="Sandbox error: no files provided",
            duration_ms=0, timed_out=False, passed=False,
        )

    timeout = max(1, min(int(timeout), MAX_TIMEOUT))

    entry = _pick_python_entrypoint(files, entrypoint)
    if not entry:
        return ExecutionResult(
            backend="none", exit_code=-2, stdout="",
            stderr="Sandbox error: no executable Python file found",
            duration_ms=0, timed_out=False, passed=False,
        )

    if prefer_docker and _docker_available():
        return await _run_docker(files, entry, timeout)
    return await _run_subprocess(files, entry, timeout)


def is_python_project(files: dict[str, str]) -> bool:
    """Quick check: does this project look executable as Python?"""
    if not isinstance(files, dict):
        return False
    return any(f.endswith(".py") for f in files.keys())
