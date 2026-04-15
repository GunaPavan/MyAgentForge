from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class ReviewerAgent(BaseAgent):
    role = AgentRole.REVIEWER
    system_prompt = (
        "You are the Reviewer agent in a software engineering swarm. "
        "You review code for correctness, bugs, security issues, and best practices. "
        "Be constructive and specific. For each issue found, explain what's wrong and how to fix it.\n\n"
        "At the END of your review, you MUST include a verdict line:\n"
        "VERDICT: APPROVED  — if code is good to ship\n"
        "VERDICT: NEEDS_FIXES — if issues need to be addressed\n"
        "Always include exactly one VERDICT line."
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.REVIEWING
        code_text = "\n\n".join(
            f"--- {fname} ---\n{code}" for fname, code in state.code.items()
        )
        prompt = (
            f"Original Task: {state.user_task}\n\n"
            f"Plan:\n{state.plan}\n\n"
            f"Code to Review:\n{code_text}\n\n"
            f"Review iteration: {state.review_iteration + 1}\n\n"
            "Review for: correctness, bugs, security, code quality, completeness.\n"
            "End with VERDICT: APPROVED or VERDICT: NEEDS_FIXES"
        )
        result = await self.think(prompt, on_chunk=on_chunk)
        state.review = result
        state.review_approved = "VERDICT: APPROVED" in result.upper() or "VERDICT:APPROVED" in result.upper()
        state.review_iteration += 1

        if state.review_approved:
            state.add_message(self.role, AgentRole.TESTER, result, type="review", approved=True)
        else:
            state.add_message(self.role, AgentRole.CODER, result, type="review", approved=False)

        return state
