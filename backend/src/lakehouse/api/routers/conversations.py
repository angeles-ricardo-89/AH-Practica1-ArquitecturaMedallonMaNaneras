from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from lakehouse.api.deps import CurrentUser, SettingsDep, get_current_user, require_csrf
from lakehouse.db.connection import get_database_url
from lakehouse.schemas.conversation import (
    AgentMessageRequest,
    AgentMessageResponse,
    ConversationCreate,
    ConversationCreated,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    ToolTraceItem,
)
from lakehouse.services.agent.executor import run_agent_turn
from lakehouse.services.memory import (
    add_message,
    add_tool_execution,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    resolve_conversation_id,
    touch_conversation,
)
from lakehouse.services.rate_limit import (
    day_window_start,
    is_allowed,
    minute_window_start,
    retry_after_seconds,
)
from lakehouse.services.security import resolve_jwt_secret

if TYPE_CHECKING:
    from lakehouse.config import Settings

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _pg_conn_str(settings: Settings) -> str:
    return get_database_url(settings)


@router.get(
    "/",
    response_model=ConversationList,
    summary="List own conversations",
    description="Returns the caller's non-expired conversations, newest activity first",
)
def list_own_conversations(
    settings: SettingsDep,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationList:
    items = list_conversations(_pg_conn_str(settings), user.id)
    return ConversationList(conversations=[ConversationSummary(**item) for item in items])


@router.post(
    "/",
    response_model=ConversationCreated,
    summary="Create conversation",
    description="Creates a conversation owned by the authenticated user",
    dependencies=[Depends(require_csrf)],
)
def create(
    payload: ConversationCreate,
    settings: SettingsDep,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationCreated:
    public_id = create_conversation(
        _pg_conn_str(settings),
        user.id,
        payload.title,
        resolve_jwt_secret(settings),
    )
    return ConversationCreated(id=public_id)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get conversation and history",
    description="Returns the caller's conversation and its message history",
)
def detail(
    conversation_id: str,
    settings: SettingsDep,
    user: CurrentUser = Depends(get_current_user),
) -> ConversationDetail:
    data = get_conversation(_pg_conn_str(settings), user.id, conversation_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetail(**data)


@router.delete(
    "/{conversation_id}",
    summary="Delete conversation",
    description="Deletes the caller's conversation, messages and traces (cascade)",
    dependencies=[Depends(require_csrf)],
)
def delete(
    conversation_id: str,
    settings: SettingsDep,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    deleted = delete_conversation(_pg_conn_str(settings), user.id, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


@router.post(
    "/{conversation_id}/messages",
    response_model=AgentMessageResponse,
    summary="Run an agent turn",
    description="Executes the agent loop (plan, tools, synthesis) inside the conversation",
    dependencies=[Depends(require_csrf)],
)
def send_message(
    conversation_id: str,
    payload: AgentMessageRequest,
    settings: SettingsDep,
    user: CurrentUser = Depends(get_current_user),
) -> AgentMessageResponse:
    conn_str = _pg_conn_str(settings)
    conv_id = resolve_conversation_id(conn_str, user.id, conversation_id)
    if conv_id is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not is_allowed(conn_str, f"chat:{user.id}", minute_window_start(), settings.chat_rate_limit):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after_seconds())},
        )
    if not is_allowed(conn_str, f"daily:{user.id}", day_window_start(), settings.daily_rate_limit):
        raise HTTPException(
            status_code=429,
            detail="Daily quota exceeded",
            headers={"Retry-After": "86400"},
        )

    history = [
        {"role": m["role"], "content": m["content"]} for m in list_messages(conn_str, conv_id)
    ]

    add_message(conn_str, conv_id, user.id, "user", payload.question)

    result = run_agent_turn(settings, payload.question, history)

    assistant_id = add_message(
        conn_str,
        conv_id,
        user.id,
        "assistant",
        result.answer,
        model=result.model_used,
        total_tokens=result.token_usage.get("total") if result.token_usage else None,
        sources=[s.model_dump(mode="json") for s in result.sources],
        latency_ms=result.latency_ms,
    )
    for trace in result.tool_executions:
        add_tool_execution(
            conn_str,
            conv_id,
            user.id,
            assistant_id,
            trace.tool_name,
            trace.arguments,
            trace.result_count,
            trace.duration_ms,
            trace.status,
        )
    touch_conversation(conn_str, conv_id)

    return AgentMessageResponse(
        id=conversation_id,
        answer=result.answer,
        refusal=result.refusal,
        model_used=result.model_used,
        tool_executions=[
            ToolTraceItem(
                tool_name=t.tool_name,
                arguments=t.arguments,
                result_count=t.result_count,
                duration_ms=t.duration_ms,
                status=t.status,
            )
            for t in result.tool_executions
        ],
        sources=result.sources,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
    )
