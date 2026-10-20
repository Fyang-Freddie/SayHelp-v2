from dataclasses import dataclass


@dataclass
class ExecutionContext:
    caller_user_id: int
    caller_role: str
    customer_id: str | None
    conversation_id: int
    confirmed: bool = False


def build_execution_context(*, caller, owner, conversation, confirmed: bool = False) -> ExecutionContext:
    return ExecutionContext(
        caller_user_id=caller.id,
        caller_role=caller.role.value,
        customer_id=owner.customer_id,
        conversation_id=conversation.id,
        confirmed=confirmed,
    )
