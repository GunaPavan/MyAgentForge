from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class OrchestratorAgent(BaseAgent):
    role = AgentRole.ORCHESTRATOR
    system_prompt = (
        "You are the Orchestrator agent in a software engineering swarm. "
        "Your job is to analyze user tasks and create a clear, structured brief "
        "for the Planner agent. Break down the user's request into specific requirements, "
        "identify constraints, and define what success looks like. "
        "Be concise and precise. Output a structured task brief."
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.PENDING
        prompt = (
            f"User Task: {state.user_task}\n\n"
            "Create a structured task brief with:\n"
            "1. Summary of what needs to be built\n"
            "2. Specific requirements (numbered list)\n"
            "3. Technical constraints or preferences\n"
            "4. Expected files/output\n"
            "5. Success criteria"
        )
        result = await self.think(prompt, on_chunk=on_chunk)
        state.add_message(self.role, AgentRole.PLANNER, result, type="task_brief")
        return state
