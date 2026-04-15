from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class TesterAgent(BaseAgent):
    role = AgentRole.TESTER
    system_prompt = (
        "You are the Tester agent in a software engineering swarm. "
        "You analyze code and generate comprehensive test cases. "
        "Write test scenarios covering: happy path, edge cases, error handling, "
        "and boundary conditions. For each test, describe the input, expected output, "
        "and what it validates. Also assess overall test coverage."
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.TESTING
        code_text = "\n\n".join(
            f"--- {fname} ---\n{code}" for fname, code in state.code.items()
        )
        prompt = (
            f"Original Task: {state.user_task}\n\n"
            f"Code to Test:\n{code_text}\n\n"
            "Generate:\n"
            "1. Unit test cases (with test function names and assertions)\n"
            "2. Edge case tests\n"
            "3. Integration test scenarios\n"
            "4. Overall coverage assessment\n"
            "5. Any potential issues found during test design"
        )
        result = await self.think(prompt, on_chunk=on_chunk)
        state.tests = result
        state.add_message(self.role, "user", result, type="tests")
        return state
