from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class PlannerAgent(BaseAgent):
    role = AgentRole.PLANNER
    system_prompt = (
        "You are the Planner agent in a software engineering swarm. "
        "You receive task briefs and create detailed implementation plans. "
        "Your plans must specify exact file names, function signatures, "
        "data structures, and step-by-step implementation order. "
        "Be thorough but concise. The Coder agent will follow your plan exactly."
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.PLANNING
        prompt = (
            f"User Task: {state.user_task}\n\n"
            "Analyze the requirements and create a detailed implementation plan:\n"
            "1. Brief summary of what to build (1-2 sentences)\n"
            "2. Architecture overview (1-2 sentences)\n"
            "3. Files to create (with exact filenames)\n"
            "4. For each file: key functions/classes with signatures\n"
            "5. Implementation order\n"
            "6. External dependencies if any\n\n"
            "Keep it concise and actionable — the Coder will follow this exactly."
        )
        result = await self.think(prompt, on_chunk=on_chunk)
        state.plan = result
        state.add_message(self.role, AgentRole.CODER, result, type="plan")
        return state
