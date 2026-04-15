from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional
from core.models import AgentRole, TaskState, AgentMessage
from core.config import llm_call, llm_stream


class BaseAgent(ABC):
    role: AgentRole
    system_prompt: str

    @abstractmethod
    async def execute(self, state: TaskState, on_chunk: Optional[Callable[[str], Awaitable[None]]] = None) -> TaskState:
        ...

    async def think(self, prompt: str, on_chunk: Optional[Callable[[str], Awaitable[None]]] = None) -> str:
        if on_chunk is None:
            return await llm_call(self.system_prompt, prompt)

        # Streaming mode
        full_text = ""
        async for chunk in llm_stream(self.system_prompt, prompt):
            full_text += chunk
            await on_chunk(chunk)
        return full_text
