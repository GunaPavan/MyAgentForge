from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class DebuggerAgent(BaseAgent):
    role = AgentRole.DEBUGGER
    system_prompt = (
        "You are the Debugger agent in a software engineering swarm. "
        "You analyze errors, trace root causes, and propose specific fixes. "
        "Be systematic: identify the error type, locate the source, explain why "
        "it happens, and provide a concrete fix with code."
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.DEBUGGING
        code_text = "\n\n".join(
            f"--- {fname} ---\n{code}" for fname, code in state.code.items()
        )
        prompt = (
            f"Error/Issue:\n{state.error}\n\n"
            f"Code:\n{code_text}\n\n"
            "Analyze:\n"
            "1. Error type and root cause\n"
            "2. Exact location in code\n"
            "3. Why this error occurs\n"
            "4. Concrete fix (with corrected code)"
        )
        result = await self.think(prompt, on_chunk=on_chunk)
        state.debug_analysis = result
        state.add_message(self.role, AgentRole.CODER, result, type="debug_analysis")
        return state
