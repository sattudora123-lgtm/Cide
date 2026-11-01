import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
_MODEL = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_CAPABILITY = re.compile(r"^[a-z0-9_-]{1,40}$")
AgentKind = Literal["installed_agent", "provider_model", "browser_model", "webhook_agent"]
AgentStatus = Literal["offline", "idle", "busy", "error", "disabled"]
StepStatus = Literal[
    "pending",
    "awaiting_approval",
    "assigned",
    "running",
    "awaiting_user",
    "completed",
    "failed",
    "cancelled",
]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
WorkflowStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
ProviderName = Literal["openai", "anthropic"]


def _single_line(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is invalid")
    cleaned = value.strip()
    if "\n" in cleaned or "\r" in cleaned or "\x00" in cleaned:
        raise ValueError(f"{label} must be a single line")
    return cleaned


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("email is invalid")
        email = value.strip().lower()
        if _EMAIL.fullmatch(email) is None:
            raise ValueError("email is invalid")
        return email

    @field_validator("password")
    @classmethod
    def password_characters(cls, value: str) -> str:
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("password contains unsupported characters")
        return value

    @field_validator("display_name", mode="before")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        return _single_line(value, "display name")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("email is invalid")
        return value.strip().lower()


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=20, max_length=500)


class UserPublic(BaseModel):
    id: UUID
    email: str
    display_name: str
    is_active: bool


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int


class AgentConfigPublic(BaseModel):
    provider: ProviderName | None = None
    model: str | None = None
    notes: str | None = None


class AgentPublic(BaseModel):
    id: UUID
    name: str
    kind: AgentKind
    status: AgentStatus
    capabilities: list[str]
    config: AgentConfigPublic
    last_heartbeat_at: str | None
    created_at: str
    updated_at: str


class AgentCreated(BaseModel):
    agent: AgentPublic
    token: str


class TokenOnce(BaseModel):
    token: str


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    kind: AgentKind
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _single_line(value, "name")

    @field_validator("capabilities")
    @classmethod
    def clean_capabilities(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            if not isinstance(item, str) or _CAPABILITY.fullmatch(item) is None:
                raise ValueError("capability is invalid")
            cleaned.append(item)
        return cleaned

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if _MODEL.fullmatch(stripped) is None:
            raise ValueError("model is invalid")
        return stripped

    @field_validator("notes", mode="before")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _single_line(value, "notes")

    @model_validator(mode="after")
    def check_kind(self):
        validate_agent_shape(self.kind, self.provider, self.model)
        return self


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    capabilities: list[str] | None = Field(default=None, max_length=20)
    provider: ProviderName | None = None
    model: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _single_line(value, "name")

    @field_validator("capabilities")
    @classmethod
    def clean_capabilities(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = []
        for item in value:
            if not isinstance(item, str) or _CAPABILITY.fullmatch(item) is None:
                raise ValueError("capability is invalid")
            cleaned.append(item)
        return cleaned

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if _MODEL.fullmatch(stripped) is None:
            raise ValueError("model is invalid")
        return stripped

    @field_validator("notes", mode="before")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _single_line(value, "notes")


def validate_agent_shape(kind: str, provider: str | None, model: str | None) -> None:
    if kind == "provider_model":
        if provider is None or model is None:
            raise ValueError("provider and model are required")
    elif provider is not None or model is not None:
        raise ValueError("provider and model are only valid for provider models")


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["idle", "busy", "error"] = "idle"


class HeartbeatResponse(BaseModel):
    status: AgentStatus
    last_heartbeat_at: str


class AgentEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: UUID
    event_type: Literal["progress", "result", "error", "log"]
    message: str = Field(default="", max_length=4000)
    output_text: str | None = Field(default=None, max_length=100_000)
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def require_payload(self):
        if self.event_type == "result" and not (self.output_text and self.output_text.strip()):
            raise ValueError("result requires output_text")
        if self.event_type == "error" and not self.error_code:
            raise ValueError("error requires error_code")
        if self.output_text is not None and "\x00" in self.output_text:
            raise ValueError("output contains unsupported characters")
        return self


class AgentEventResult(BaseModel):
    step_id: UUID
    status: StepStatus


class Assignment(BaseModel):
    step_id: UUID
    task_id: UUID
    title: str
    instruction: str
    status: StepStatus
    sequence: int


class AssignmentPage(BaseModel):
    items: list[Assignment]
    next_cursor: str | None


class AgentPage(BaseModel):
    items: list[AgentPublic]
    next_cursor: str | None


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    input_text: str = Field(min_length=1, max_length=20_000)

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _single_line(value, "title")

    @field_validator("input_text")
    @classmethod
    def clean_input(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("input is empty")
        return value


class StepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=20_000)
    requires_approval: bool = False
    assigned_agent_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _single_line(value, "title")

    @field_validator("instruction")
    @classmethod
    def clean_instruction(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("instruction is empty")
        return value


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[StepCreate] = Field(min_length=1, max_length=50)


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID


class TaskPublic(BaseModel):
    id: UUID
    title: str
    input_text: str
    status: TaskStatus
    decomposition: Literal["not_performed"]
    created_at: str
    updated_at: str


class TaskPage(BaseModel):
    items: list[TaskPublic]
    next_cursor: str | None


class ResultPublic(BaseModel):
    id: UUID
    output_text: str
    untrusted: Literal[True]
    error_code: str | None
    created_at: str


class AgentSummary(BaseModel):
    id: UUID
    name: str
    kind: AgentKind
    status: AgentStatus


class StepPublic(BaseModel):
    id: UUID
    workflow_id: UUID
    task_id: UUID
    sequence: int
    title: str
    instruction: str
    status: StepStatus
    requires_approval: bool
    approved: bool
    assigned_agent_id: UUID | None
    agent: AgentSummary | None
    latest_result: ResultPublic | None


class WorkflowPublic(BaseModel):
    id: UUID
    version: int
    status: WorkflowStatus
    steps: list[StepPublic]


class EventPayload(BaseModel):
    message: str
    untrusted: Literal[True]


class EventPublic(BaseModel):
    id: UUID
    seq: int
    task_id: UUID
    step_id: UUID | None
    agent_id: UUID | None
    direction: Literal["host_to_agent", "agent_to_host", "system"]
    event_type: str
    payload: EventPayload
    created_at: str


class EventPage(BaseModel):
    items: list[EventPublic]
    next_cursor: int | None


class TaskDetail(BaseModel):
    task: TaskPublic
    workflow: WorkflowPublic | None
    agents: list[AgentSummary]
    recent_events: list[EventPublic]


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName
    label: str = Field(min_length=1, max_length=80)
    api_key: str = Field(min_length=8, max_length=256)

    @field_validator("label", mode="before")
    @classmethod
    def clean_label(cls, value: str) -> str:
        return _single_line(value, "label")

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value: str) -> str:
        if value.strip() != value or "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("api key is invalid")
        return value


class ProviderPublic(BaseModel):
    id: UUID
    provider: ProviderName
    label: str
    created_at: str


class ProviderPage(BaseModel):
    items: list[ProviderPublic]
    next_cursor: str | None


class BrowserJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: UUID
    target_url: str = Field(min_length=12, max_length=2000)
    prompt: str = Field(min_length=1, max_length=20_000)

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("prompt is empty")
        return value


class BrowserResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("content is empty")
        return value


class BrowserJobPublic(BaseModel):
    id: UUID
    step_id: UUID
    task_id: UUID
    target_url: str
    prompt: str
    status: Literal["awaiting_user", "completed", "cancelled"]
    result_text: str | None
    untrusted: Literal[True]
    created_at: str
    completed_at: str | None


class BrowserJobPage(BaseModel):
    items: list[BrowserJobPublic]
    next_cursor: str | None


class HealthStatus(BaseModel):
    status: Literal["ok", "ready"]
