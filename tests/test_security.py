"""Deep security checks: SRI, XSS defenses, key redaction."""
import os
import re
import subprocess
import pytest


# ---------- Static file checks ----------

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_no_inline_onclick_in_html(project_root):
    html = _read(os.path.join(project_root, "static", "index.html"))
    # Any inline event handler — onclick, onload, onerror, onsubmit, etc.
    matches = re.findall(r'\son[a-z]+\s*=\s*["\']', html)
    assert len(matches) == 0, f"Inline event handlers found: {matches}"


def test_sri_on_all_cdn_assets(project_root):
    html = _read(os.path.join(project_root, "static", "index.html"))
    # Every cdnjs reference should have integrity + crossorigin
    cdn_refs = re.findall(r'<(?:script|link)[^>]*cdnjs\.cloudflare\.com[^>]*>', html)
    assert cdn_refs, "Expected at least one CDN reference"
    for ref in cdn_refs:
        assert 'integrity="sha' in ref, f"Missing SRI on: {ref[:80]}"
        assert 'crossorigin=' in ref, f"Missing crossorigin on: {ref[:80]}"


def test_app_js_no_eval_no_function_constructor(project_root):
    js = _read(os.path.join(project_root, "static", "app.js"))
    assert not re.search(r"\beval\s*\(", js), "eval() detected"
    assert not re.search(r"\bnew\s+Function\s*\(", js), "new Function() detected"


def test_app_js_escape_html_used(project_root):
    js = _read(os.path.join(project_root, "static", "app.js"))
    # escapeHtml is defined and used multiple times for XSS protection
    assert "function escapeHtml" in js
    # Should be called many times
    assert js.count("escapeHtml(") >= 8


def test_script_tag_type_module(project_root):
    html = _read(os.path.join(project_root, "static", "index.html"))
    assert 'type="module"' in html, "app.js should be loaded as a module for isolation"


# ---------- Secret scan ----------

KEY_PATTERNS = [
    r"csk-[A-Za-z0-9]{20,}",
    r"gsk_[A-Za-z0-9]{20,}",
    r"sk-proj-[A-Za-z0-9]{20,}",
    r"sk-[A-Za-z0-9]{30,}",
    r"AKIA[A-Z0-9]{16}",          # AWS
    r"AIza[0-9A-Za-z\-_]{35}",    # Google
]


def test_no_secrets_in_tracked_files(project_root):
    leaked = []
    # Exclude: VCS, caches, generated output, test fixtures (they legitimately contain key-shaped strings)
    exclude_dirs = {".git", "__pycache__", "output", ".venv", "venv", "node_modules", "tests", ".pytest_cache"}
    exclude_files = {".env"}  # local-only, gitignored
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for fname in files:
            if fname in exclude_files:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue
            for pattern in KEY_PATTERNS:
                for m in re.findall(pattern, content):
                    leaked.append(f"{path}: {m[:20]}...")
    assert not leaked, f"Possible secrets leaked:\n" + "\n".join(leaked)


def test_env_file_is_gitignored(project_root):
    gi = _read(os.path.join(project_root, ".gitignore"))
    assert ".env" in gi, ".env must be in .gitignore"


def test_dockerignore_excludes_env(project_root):
    di = _read(os.path.join(project_root, ".dockerignore"))
    assert ".env" in di, ".env must be in .dockerignore"


# ---------- Key redaction in server code ----------

def test_key_redaction_patterns():
    from core.config import KeyRedactingFilter

    cases = [
        ("Bearer sk-abc123xyz4567890abcdef", "[REDACTED_KEY]"),
        ("Error with csk-fake12345678901234567890", "[REDACTED_KEY]"),
        ("Auth: gsk_foo1234567890bar1234", "[REDACTED_KEY]"),
    ]
    for raw, must_contain in cases:
        redacted = KeyRedactingFilter.redact(raw)
        assert must_contain in redacted, f"Redaction failed: {raw} -> {redacted}"
        # Original key tail must NOT appear in redacted output
        assert "sk-abc123" not in redacted or raw.startswith("Bearer")
        assert "csk-fake12345678901234567890" not in redacted
        assert "gsk_foo1234567890bar1234" not in redacted


# ---------- Dockerfile security ----------

def test_dockerfile_non_root(project_root):
    df = _read(os.path.join(project_root, "Dockerfile"))
    assert "useradd" in df
    assert re.search(r"^USER\s+app\b", df, re.MULTILINE), "Container must run as non-root user"


def test_dockerfile_multi_stage(project_root):
    df = _read(os.path.join(project_root, "Dockerfile"))
    # Two FROM statements = multi-stage
    froms = re.findall(r"^FROM\s+", df, re.MULTILINE)
    assert len(froms) >= 2, "Dockerfile should be multi-stage to keep runtime small"


def test_dockerfile_has_healthcheck(project_root):
    df = _read(os.path.join(project_root, "Dockerfile"))
    assert "HEALTHCHECK" in df


# ---------- Dependency vulnerability scan ----------

@pytest.mark.slow
def test_no_known_vulnerabilities(project_root):
    """Runs pip-audit against requirements.txt. Will fail on any known CVE."""
    req = os.path.join(project_root, "requirements.txt")
    try:
        result = subprocess.run(
            ["pip-audit", "-r", req, "--strict"],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        pytest.skip("pip-audit not installed")
    # --strict: non-zero exit on ANY vuln
    assert result.returncode == 0, f"pip-audit found vulnerabilities:\n{result.stdout}\n{result.stderr}"
