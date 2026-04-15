import json
import re
from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class CoderAgent(BaseAgent):
    role = AgentRole.CODER
    system_prompt = (
        "You are the Coder agent in a software engineering swarm. "
        "You receive implementation plans and write clean, production-quality code. "
        "Output your code as a JSON object mapping filenames to file contents.\n\n"
        "CRITICAL RULES:\n"
        "1. Your ENTIRE response must be ONLY a valid JSON object. No markdown, no explanations, no preamble.\n"
        "2. Format: {\"filename.ext\": \"file contents\", \"another.ext\": \"contents\"}\n"
        "3. Write COMPLETE, runnable code — never truncate or use placeholders like // TODO\n"
        "4. Escape inside strings using JSON rules ONLY: \\n for newline, \\\" for quote, \\\\ for backslash\n"
        "5. NEVER use \\' (single quote doesn't need escaping in JSON)\n"
        "6. Keep files focused and concise — quality over quantity\n"
        "7. Include all necessary imports and error handling"
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.CODING
        plan = state.plan
        review_feedback = ""
        if state.review_iteration > 0:
            review_feedback = f"\n\nPrevious Review Feedback (iteration {state.review_iteration}):\n{state.review}\n"
            previous_code = "\n\n".join(
                f"--- {fname} ---\n{code}" for fname, code in state.code.items()
            )
            review_feedback += f"\nPrevious Code:\n{previous_code}\nFix the issues identified in the review."

        prompt = f"Implementation Plan:\n{plan}{review_feedback}\n\nWrite the code now. Output ONLY valid JSON mapping filenames to contents."

        result = await self.think(prompt, on_chunk=on_chunk)
        code = self._parse_code(result)
        state.code = code
        code_summary = ", ".join(code.keys()) if code else "No files generated"
        state.add_message(
            self.role, AgentRole.REVIEWER,
            f"Generated {len(code)} file(s): {code_summary}",
            type="code", files=list(code.keys()),
        )
        return state

    def _parse_code(self, raw: str) -> dict[str, str]:
        # Try multiple parsing strategies
        candidates = [raw, self._clean_json(raw)]

        # Also try extracting from markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if json_match:
            candidates.append(json_match.group(1))
            candidates.append(self._clean_json(json_match.group(1)))

        # Extract first { ... last } as fallback
        first_brace = raw.find("{")
        last_brace = raw.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            trimmed = raw[first_brace:last_brace + 1]
            candidates.append(trimmed)
            candidates.append(self._clean_json(trimmed))

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and parsed:
                    return {k: str(v) for k, v in parsed.items()}
            except (json.JSONDecodeError, ValueError):
                continue

        # Last resort: extract code blocks with filenames from markdown
        code_blocks = {}
        pattern = r"(?:#+\s*)?(?:`([^`]+)`|(\S+\.(?:py|js|html|css|txt|md)))\s*```\w*\n(.*?)```"
        for match in re.finditer(pattern, raw, re.DOTALL):
            fname = match.group(1) or match.group(2)
            code_blocks[fname] = match.group(3).strip()

        return code_blocks if code_blocks else {"output.py": raw}

    def _clean_json(self, s: str) -> str:
        """Clean common LLM JSON mistakes: invalid escapes, trailing commas."""
        # Fix \' (invalid in JSON, valid in JS) -> '
        cleaned = re.sub(r"\\'", "'", s)
        # Remove trailing commas before } or ]
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        return cleaned
