import json
import re
from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus
from core.sandbox import run_code, is_python_project, ExecutionResult


class TesterAgent(BaseAgent):
    role = AgentRole.TESTER
    system_prompt = (
        "You are the Tester agent in a software engineering swarm. "
        "When the project is Python, you generate runnable test code that is then "
        "executed in a sandbox; the actual pass/fail comes from real execution, "
        "not from your prediction. When the project is HTML/JS or unrunnable, you "
        "describe test scenarios in plain text."
    )

    # ---------- entry point ----------

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.TESTING

        if is_python_project(state.code):
            return await self._test_python(state, on_chunk)
        return await self._test_static(state, on_chunk)

    # ---------- Python: generate + execute ----------

    async def _test_python(self, state, on_chunk):
        code_text = "\n\n".join(
            f"--- {fname} ---\n{code}" for fname, code in state.code.items()
        )
        prompt = (
            f"Original Task: {state.user_task}\n\n"
            f"Code under test:\n{code_text}\n\n"
            "Write a Python test file named test_main.py that:\n"
            "1. Imports from the modules above\n"
            "2. Uses assert statements (no test framework needed)\n"
            "3. Covers happy path + at least one edge case\n"
            "4. On success prints 'OK: <N> tests passed'\n"
            "5. Exits cleanly when all asserts pass\n\n"
            "Output ONLY a valid JSON object with this exact shape:\n"
            '{"test_main.py": "<full python code as a single string>"}\n\n'
            "CRITICAL: Your entire response must be valid JSON. No markdown, no preamble."
        )

        raw = await self.think(prompt, on_chunk=on_chunk)
        test_files = self._parse_test_file(raw)

        if not test_files.get("test_main.py"):
            # LLM failed to produce runnable tests — fall back to descriptive mode
            state.tests = raw
            state.add_message(self.role, "user", raw, type="tests")
            return state

        # Combine the existing project code with the generated test file
        combined = {**state.code, **test_files}

        # Run in sandbox
        result: ExecutionResult = await run_code(
            combined, entrypoint="test_main.py", timeout=10,
        )

        # Build a structured summary message
        summary = self._build_summary(test_files["test_main.py"], result)
        state.tests = summary
        state.test_results = json.dumps(result.to_dict())
        # Attach to message metadata so the WebSocket layer can emit a structured event
        state.add_message(
            self.role, "user", summary,
            type="tests",
            execution={
                "backend": result.backend,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
                "passed": result.passed,
                "test_file": test_files["test_main.py"],
            },
        )
        return state

    # ---------- Non-Python: text-only test plan ----------

    async def _test_static(self, state, on_chunk):
        code_text = "\n\n".join(
            f"--- {fname} ---\n{code}" for fname, code in state.code.items()
        )
        prompt = (
            f"Original Task: {state.user_task}\n\n"
            f"Code to test (HTML/JS/static):\n{code_text}\n\n"
            "Describe test scenarios for this project:\n"
            "1. User interaction scenarios (clicks, inputs)\n"
            "2. Edge cases\n"
            "3. Visual/accessibility checks\n"
            "4. Coverage assessment\n"
            "Use plain text. No code execution is available for non-Python projects."
        )
        result = await self.think(prompt, on_chunk=on_chunk)
        state.tests = result
        state.add_message(self.role, "user", result, type="tests")
        return state

    # ---------- helpers ----------

    def _parse_test_file(self, raw: str) -> dict:
        """Pull {test_main.py: ...} out of the LLM response. Tolerant of markdown fences."""
        # Strategy 1: direct JSON parse
        candidates = [raw]
        # Markdown json fence
        m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if m:
            candidates.append(m.group(1))
        # Crop to outermost braces
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            candidates.append(raw[first : last + 1])

        for c in candidates:
            # Clean common LLM JSON mistakes
            cleaned = re.sub(r"\\'", "'", c)
            cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict) and "test_main.py" in obj:
                    return {"test_main.py": str(obj["test_main.py"])}
            except (json.JSONDecodeError, ValueError):
                continue

        # Strategy 2: extract a ```python ... ``` block
        m = re.search(r"```python\s*\n(.*?)```", raw, re.DOTALL)
        if m:
            return {"test_main.py": m.group(1).strip()}

        return {}

    def _build_summary(self, test_code: str, result: ExecutionResult) -> str:
        status = "PASSED" if result.passed else ("TIMED OUT" if result.timed_out else "FAILED")
        emoji = "✅" if result.passed else ("⏱️" if result.timed_out else "❌")
        lines = [
            f"{emoji} Tests {status} in {result.duration_ms} ms (backend: {result.backend})",
            "",
            "--- Generated test_main.py ---",
            test_code[:1500] + ("..." if len(test_code) > 1500 else ""),
            "",
        ]
        if result.stdout:
            lines += ["--- stdout ---", result.stdout, ""]
        if result.stderr and not result.passed:
            lines += ["--- stderr ---", result.stderr, ""]
        return "\n".join(lines)
