from __future__ import annotations
import asyncio
import os
import re
from typing import AsyncGenerator, Optional
from core.models import (
    AgentRole, AgentStatus, TaskState, TaskStatus, SwarmEvent,
)
from core.config import MAX_REVIEW_ITERATIONS, SKIP_TESTER, COMBINE_ORCHESTRATOR
from agents import (
    OrchestratorAgent, PlannerAgent, CoderAgent,
    ReviewerAgent, TesterAgent, DebuggerAgent,
)


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def save_files_to_disk(files: dict[str, str], task_id: str) -> str:
    safe_task_id = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)[:40]
    out_path = os.path.join(OUTPUT_DIR, safe_task_id)
    os.makedirs(out_path, exist_ok=True)
    for fname, content in files.items():
        safe_name = os.path.basename(fname)
        if not safe_name:
            continue
        full_path = os.path.join(out_path, safe_name)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    return out_path


class SwarmCancelled(Exception):
    pass


class Swarm:
    def __init__(self):
        self.agents = {
            AgentRole.ORCHESTRATOR: OrchestratorAgent(),
            AgentRole.PLANNER: PlannerAgent(),
            AgentRole.CODER: CoderAgent(),
            AgentRole.REVIEWER: ReviewerAgent(),
            AgentRole.TESTER: TesterAgent(),
            AgentRole.DEBUGGER: DebuggerAgent(),
        }
        self.agent_statuses = {role: AgentStatus.IDLE for role in AgentRole}
        self.cancelled = False
        self._event_queue: asyncio.Queue = asyncio.Queue()

    def cancel(self):
        self.cancelled = True

    def _check_cancelled(self):
        if self.cancelled:
            raise SwarmCancelled()

    def _status_event(self, role, status):
        self.agent_statuses[role] = status
        return SwarmEvent(type="agent_status", data={"agent": role.value, "status": status.value})

    def _task_event(self, status):
        return SwarmEvent(type="task_status", data={"status": status.value})

    def _message_event(self, sender, receiver, content, **extra):
        return SwarmEvent(type="message", data={"sender": sender, "receiver": receiver, "content": content, **extra})

    def _stream_event(self, agent, receiver, chunk, msg_id):
        return SwarmEvent(type="stream", data={"sender": agent, "receiver": receiver, "chunk": chunk, "msg_id": msg_id})

    def _code_event(self, files):
        return SwarmEvent(type="code_output", data={"files": files})

    async def _make_stream_callback(self, agent_role: str, receiver: str, msg_id: str):
        async def callback(chunk: str):
            self._check_cancelled()
            await self._event_queue.put(self._stream_event(agent_role, receiver, chunk, msg_id))
        return callback

    async def _run_agent(self, role: AgentRole, receiver: str, state: TaskState) -> TaskState:
        """Run an agent with streaming, pushing events to queue."""
        import uuid
        msg_id = uuid.uuid4().hex[:8]
        # Start stream marker
        await self._event_queue.put(SwarmEvent(
            type="stream_start",
            data={"sender": role.value, "receiver": receiver, "msg_id": msg_id},
        ))
        callback = await self._make_stream_callback(role.value, receiver, msg_id)
        state = await self.agents[role].execute(state, on_chunk=callback)
        # End stream marker
        await self._event_queue.put(SwarmEvent(
            type="stream_end",
            data={"sender": role.value, "receiver": receiver, "msg_id": msg_id},
        ))
        return state

    async def run(self, user_task: str) -> AsyncGenerator[SwarmEvent, None]:
        state = TaskState(user_task=user_task)

        # Runner task processes the full swarm in background, pushing events to queue
        async def runner():
            try:
                nonlocal state
                await self._event_queue.put(self._message_event("user", "orchestrator", user_task))

                if COMBINE_ORCHESTRATOR:
                    await self._event_queue.put(self._status_event(AgentRole.ORCHESTRATOR, AgentStatus.WORKING))
                    await self._event_queue.put(self._message_event(
                        "orchestrator", "planner", "Delegating combined analysis + planning",
                    ))
                    await self._event_queue.put(self._status_event(AgentRole.ORCHESTRATOR, AgentStatus.DONE))

                    await self._event_queue.put(self._status_event(AgentRole.PLANNER, AgentStatus.WORKING))
                    await self._event_queue.put(self._task_event(TaskStatus.PLANNING))
                    state = await self._run_agent(AgentRole.PLANNER, "coder", state)
                    await self._event_queue.put(self._status_event(AgentRole.PLANNER, AgentStatus.DONE))
                else:
                    await self._event_queue.put(self._status_event(AgentRole.ORCHESTRATOR, AgentStatus.WORKING))
                    state = await self._run_agent(AgentRole.ORCHESTRATOR, "planner", state)
                    await self._event_queue.put(self._status_event(AgentRole.ORCHESTRATOR, AgentStatus.DONE))

                    await self._event_queue.put(self._status_event(AgentRole.PLANNER, AgentStatus.WORKING))
                    await self._event_queue.put(self._task_event(TaskStatus.PLANNING))
                    state = await self._run_agent(AgentRole.PLANNER, "coder", state)
                    await self._event_queue.put(self._status_event(AgentRole.PLANNER, AgentStatus.DONE))

                # Code-Review loop
                for iteration in range(MAX_REVIEW_ITERATIONS + 1):
                    self._check_cancelled()
                    await self._event_queue.put(self._status_event(AgentRole.CODER, AgentStatus.WORKING))
                    await self._event_queue.put(self._task_event(
                        TaskStatus.CODING if iteration == 0 else TaskStatus.FIXING
                    ))
                    state = await self._run_agent(AgentRole.CODER, "reviewer", state)
                    await self._event_queue.put(self._code_event(state.code))
                    await self._event_queue.put(self._status_event(AgentRole.CODER, AgentStatus.DONE))

                    await self._event_queue.put(self._status_event(AgentRole.REVIEWER, AgentStatus.WORKING))
                    await self._event_queue.put(self._task_event(TaskStatus.REVIEWING))
                    state = await self._run_agent(AgentRole.REVIEWER, "tester", state)
                    await self._event_queue.put(self._status_event(AgentRole.REVIEWER, AgentStatus.DONE))

                    if state.review_approved or iteration >= MAX_REVIEW_ITERATIONS:
                        break

                if not SKIP_TESTER:
                    self._check_cancelled()
                    await self._event_queue.put(self._status_event(AgentRole.TESTER, AgentStatus.WORKING))
                    await self._event_queue.put(self._task_event(TaskStatus.TESTING))
                    state = await self._run_agent(AgentRole.TESTER, "user", state)
                    await self._event_queue.put(self._status_event(AgentRole.TESTER, AgentStatus.DONE))

                saved_path = ""
                if state.code:
                    try:
                        saved_path = save_files_to_disk(state.code, state.task_id)
                    except Exception as e:
                        await self._event_queue.put(self._message_event("system", "user", f"Warning: could not save files: {e}"))

                await self._event_queue.put(self._task_event(TaskStatus.COMPLETED))
                msg = f"Task completed! Generated {len(state.code)} file(s): {', '.join(state.code.keys())}"
                if saved_path:
                    msg += f"\nFiles saved to: {saved_path}"
                await self._event_queue.put(self._message_event("system", "user", msg))

            except SwarmCancelled:
                await self._event_queue.put(self._message_event("system", "user", "Task cancelled by user"))
                await self._event_queue.put(self._task_event(TaskStatus.FAILED))
            except Exception as e:
                await self._event_queue.put(self._message_event("system", "user", f"Error: {e}"))
                await self._event_queue.put(self._task_event(TaskStatus.FAILED))
            finally:
                await self._event_queue.put(None)  # Sentinel

        runner_task = asyncio.create_task(runner())

        try:
            while True:
                event = await self._event_queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not runner_task.done():
                runner_task.cancel()
                try:
                    await runner_task
                except (asyncio.CancelledError, SwarmCancelled):
                    pass
