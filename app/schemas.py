from datetime import datetime
from pydantic import BaseModel, ConfigDict

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    customer_id: str | None
    display_name: str | None
    is_active: bool
    created_at: datetime

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content: str
    tool_call_id: str | None
    tool_calls: dict | None
    citations: dict | None
    feedback: dict | None
    created_at: datetime

class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

class ChatStreamRequest(BaseModel):
    conversation_id: int
    content: str

class FeedbackRequest(BaseModel):
    type: str  # "up" | "down"
