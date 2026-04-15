from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import time
import uuid


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    DEBUGGER = "debugger"


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    DONE = "done"
    ERROR = "error"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    TESTING = "testing"
    DEBUGGING = "debugging"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    sender: AgentRole
    receiver: AgentRole | str
    content: str
    timestamp: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskState(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_task: str = ""
    status: TaskStatus = TaskStatus.PENDING
    plan: str = ""
    code: dict[str, str] = Field(default_factory=dict)  # filename -> code
    review: str = ""
    review_approved: bool = False
    review_iteration: int = 0
    tests: str = ""
    test_results: str = ""
    error: str = ""
    debug_analysis: str = ""
    messages: list[AgentMessage] = Field(default_factory=list)

    def add_message(self, sender: AgentRole, receiver: AgentRole | str, content: str, **kwargs) -> AgentMessage:
        msg = AgentMessage(sender=sender, receiver=receiver, content=content, metadata=kwargs)
        self.messages.append(msg)
        return msg


class SwarmEvent(BaseModel):
    type: str  # "agent_status", "message", "task_status", "code_output"
    data: dict[str, Any]
