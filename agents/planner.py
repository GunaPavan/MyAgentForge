from .base import BaseAgent
from core.models import AgentRole, TaskState, TaskStatus


class PlannerAgent(BaseAgent):
    role = AgentRole.PLANNER
    system_prompt = (
        "You are the Planner agent in a software engineering swarm. "
        "You receive task briefs and create detailed implementation plans. "
        "Your plans must specify exact file names, function signatures, "
        "data structures, and step-by-step implementation order. "
        "Be thorough but concise. The Coder agent will follow your plan exactly. "
        "When given existing code as context, you plan modifications to that code "
        "rather than designing from scratch."
    )

    async def execute(self, state, on_chunk=None):
        state.status = TaskStatus.PLANNING

        if state.is_followup and state.prior_code:
            # Follow-up: modifying existing code based on user's change request
            prior_files = "\n\n".join(
                f"--- {fname} ---\n{code}" for fname, code in state.prior_code.items()
            )
            prompt = (
                f"FOLLOW-UP REQUEST. The user already has a project and wants to modify it.\n\n"
                f"Original task: {state.prior_task}\n\n"
                f"Existing files:\n{prior_files}\n\n"
                f"User's new request: {state.user_task}\n\n"
                "Create a focused plan for the modification:\n"
                "1. What the user wants changed (1-2 sentences)\n"
                "2. Which existing files to modify and how\n"
                "3. Any NEW files to add (with filenames)\n"
                "4. Any files to remove (rare)\n"
                "5. Implementation order\n\n"
                "IMPORTANT: Preserve all existing functionality unless the user explicitly asks to remove it. "
                "The Coder will receive the prior code and your plan — they need to know exactly which files "
                "to keep unchanged, modify, add, or remove."
            )
        else:
            # New project
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
