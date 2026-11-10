from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.response_agent import render_fallback
from app.core.logging import emit_event
from app.database.base import utcnow
from app.dependencies import get_session
from app.guardrails.action_confirmation import confirm_pending_action, get_pending_action
from app.models import Conversation, ConversationEvent, Customer, Message
from app.schemas.conversation import ConfirmActionRequest, ConversationCreate, ConversationOut

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _out(c: Conversation, customer_id: str | None) -> ConversationOut:
    return ConversationOut(conversation_id=str(c.id), customer_id=customer_id, customer_verified=c.customer_pk is not None,
                           selected_language=c.selected_language, status=c.status, resolution_status=c.resolution_status,
                           started_at=c.started_at.isoformat(), ended_at=c.ended_at.isoformat() if c.ended_at else None,
                           websocket_path=f"/api/voice/{c.id}")


async def _get(db: AsyncSession, conversation_id: str) -> tuple[Conversation, str | None]:
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(404, "Conversation not found")
    c = await db.get(Conversation, cid)
    if c is None:
        raise HTTPException(404, "Conversation not found")
    cust = await db.get(Customer, c.customer_pk) if c.customer_pk else None
    return c, cust.customer_id if cust else None


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(body: ConversationCreate, db: AsyncSession = Depends(get_session)):
    """Create a session. The customer is verified here and *bound for the life of the conversation*.
    A missing/invalid id yields an unverified conversation: the agent then asks for the registered mobile number."""
    cust = None
    if body.customer_id:
        cust = (await db.execute(select(Customer).where(Customer.customer_id == body.customer_id))).scalar_one_or_none()
    if cust is not None and cust.status == "inactive":
        raise HTTPException(409, "This customer is deactivated. Activate the customer to start a support session.")
    conv = Conversation(customer_pk=cust.id if cust else None)
    db.add(conv)
    await db.commit()
    await emit_event(str(conv.id), "conversation_created", agent="api",
                     summary=f"Conversation created for {cust.customer_id}" if cust else "Conversation created (customer unverified)")
    return _out(conv, cust.customer_id if cust else None)


@router.get("", response_model=list[ConversationOut])
async def list_conversations(customer_id: str | None = Query(None), limit: int = Query(50, le=200),
                             db: AsyncSession = Depends(get_session)):
    q = select(Conversation, Customer.customer_id).outerjoin(Customer, Customer.id == Conversation.customer_pk) \
        .order_by(Conversation.started_at.desc()).limit(limit)
    if customer_id:
        q = q.where(Customer.customer_id == customer_id)
    return [_out(c, cid) for c, cid in (await db.execute(q)).all()]


@router.get("/{conversation_id}", response_model=ConversationOut)
async def conversation_detail(conversation_id: str, db: AsyncSession = Depends(get_session)):
    c, cid = await _get(db, conversation_id)
    return _out(c, cid)


@router.get("/{conversation_id}/messages")
async def conversation_messages(conversation_id: str, db: AsyncSession = Depends(get_session)):
    c, _ = await _get(db, conversation_id)
    rows = (await db.execute(select(Message).where(Message.conversation_pk == c.id).order_by(Message.created_at))).scalars().all()
    return [{"id": str(m.id), "role": m.role, "content": m.content, "agent_name": m.agent_name, "metadata": m.meta,
             "created_at": m.created_at.isoformat()} for m in rows]


@router.get("/{conversation_id}/events")
async def conversation_events(conversation_id: str, after: int = Query(0), db: AsyncSession = Depends(get_session)):
    c, _ = await _get(db, conversation_id)
    rows = (await db.execute(select(ConversationEvent).where(ConversationEvent.conversation_pk == c.id,
                                                             ConversationEvent.id > after)
                             .order_by(ConversationEvent.id).limit(500))).scalars().all()
    return [{"id": e.id, "type": e.event_type, "agent": e.agent, "status": e.status, "summary": e.summary,
             "data": e.data, "timestamp": e.created_at.isoformat()} for e in rows]


@router.get("/{conversation_id}/pending-action")
async def pending_action(conversation_id: str, db: AsyncSession = Depends(get_session)):
    await _get(db, conversation_id)
    return {"pending_action": await get_pending_action(conversation_id)}


@router.post("/{conversation_id}/confirm-action")
async def confirm_action(conversation_id: str, body: ConfirmActionRequest, db: AsyncSession = Depends(get_session)):
    """Confirm/reject the pending action. The backend re-validates eligibility and ownership before executing."""
    c, _ = await _get(db, conversation_id)
    outcome = await confirm_pending_action(conversation_id, body.decision, body.action_id)
    if outcome["status"] in {"executed", "rejected", "expired", "no_longer_eligible", "failed"}:
        text = render_fallback({"confirmation_result": outcome})
        db.add(Message(conversation_pk=c.id, role="agent", content=text, agent_name="confirmation",
                       meta={"via": "rest_confirm", "status": outcome["status"]}))
        await db.commit()
        from app.voice.voice_session import ACTIVE_SESSIONS
        live = ACTIVE_SESSIONS.get(conversation_id)
        if live:
            await live.announce(text)
    if not outcome["ok"]:
        raise HTTPException(409, outcome.get("message") or outcome["status"])
    return outcome


@router.post("/{conversation_id}/end", response_model=ConversationOut)
async def end_conversation(conversation_id: str, db: AsyncSession = Depends(get_session)):
    c, cid = await _get(db, conversation_id)
    if c.status != "ended":
        c.status, c.ended_at = "ended", utcnow()
        await db.commit()
        await emit_event(conversation_id, "conversation_ended", agent="api", summary="Conversation ended")
    return _out(c, cid)

