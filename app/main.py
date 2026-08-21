import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict

from app.prompt import SYSTEM_PROMPT

load_dotenv()

app = FastAPI(title="Northstar Homes AI Sales Agent", version="2.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
BOOKING_SIMULATION_RESULT = os.getenv("BOOKING_SIMULATION_RESULT", "confirmed")
SESSIONS: Dict[str, Dict[str, Any]] = {}


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=4000)
    # Demo-only control. It is deliberately separate from customer language so the
    # application never interprets a customer saying "fail" as a booking failure.
    demo_booking_result: Optional[Literal["confirmed", "failed"]] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    ended: bool = False
    booking_status: Optional[str] = None
    intent: Optional[str] = None
    handoff_requested: bool = False
    lead_profile: Optional[Dict[str, Any]] = None


class EndRequest(BaseModel):
    session_id: str


class LeadUpdates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget: Optional[str] = None
    configuration: Optional[Literal["2 BHK", "3 BHK"]] = None
    purpose: Optional[str] = None
    timeline: Optional[str] = None
    location_preference: Optional[str] = None
    interest_level: Optional[Literal["low", "medium", "high", "unknown"]] = None
    follow_up_required: Optional[bool] = None
    follow_up_time: Optional[str] = None


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str
    reply: str
    lead_updates: LeadUpdates
    action: Literal["none", "book_site_visit", "request_human"] = "none"
    handoff_reason: Optional[str] = None
    end_conversation: bool = False
    contact_allowed: Optional[bool] = None


def new_session() -> str:
    sid = str(uuid.uuid4())
    SESSIONS[sid] = {
        "messages": [],
        "profile": {
            "budget": None,
            "configuration": None,
            "purpose": None,
            "timeline": None,
            "location_preference": None,
            "interest_level": "unknown",
            "site_visit_status": "not_requested",
            "follow_up_required": False,
            "follow_up_time": None,
            "contact_allowed": True,
        },
        "ended": False,
        "booking_attempted": False,
        "booking_status": None,
        "handoff_requested": False,
        "handoff_reason": None,
        "last_intent": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return sid


def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        return None


def require_llm():
    client = get_openai_client()
    if client is None:
        raise HTTPException(
            503,
            "LLM is not configured. Add OPENAI_API_KEY to .env and install requirements.txt.",
        )
    return client


def conversation_messages(session: Dict[str, Any]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(session["messages"][-24:])
    return messages


def get_strict_json_schema(model_class) -> Dict[str, Any]:
    schema = model_class.model_json_schema()
    def make_required(s: Dict[str, Any]):
        if "properties" in s:
            s["required"] = list(s["properties"].keys())
        if "$defs" in s:
            for sub_schema in s["$defs"].values():
                make_required(sub_schema)
    make_required(schema)
    return schema


def decide_with_llm(session: Dict[str, Any]) -> AgentDecision:
    client = require_llm()
    response = client.chat.completions.create(
        model=MODEL,
        messages=conversation_messages(session),
        temperature=0.2,
        max_tokens=600,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "northstar_agent_decision",
                "strict": True,
                "schema": get_strict_json_schema(AgentDecision),
            },
        },
    )
    raw = response.choices[0].message.content
    try:
        return AgentDecision.model_validate(json.loads(raw))
    except Exception as exc:
        raise HTTPException(502, f"The model returned an invalid agent decision: {exc}")


def apply_lead_updates(session: Dict[str, Any], updates: LeadUpdates) -> None:
    profile = session["profile"]
    values = updates.model_dump(exclude_none=True)
    for key, value in values.items():
        if key == "follow_up_required":
            profile[key] = bool(value)
        else:
            profile[key] = value


def simulate_booking(session: Dict[str, Any], requested_result: Optional[str]) -> str:
    """Mock booking tool. Business outcome is controlled by backend configuration, not customer text."""
    result = requested_result or BOOKING_SIMULATION_RESULT
    if result not in {"confirmed", "failed"}:
        result = "confirmed"
    session["booking_attempted"] = True
    session["booking_status"] = result
    session["profile"]["site_visit_status"] = result
    return result


def booking_event_text(status: str) -> str:
    if status == "confirmed":
        return "BACKEND EVENT: site-visit booking was successfully confirmed. Do not invent a date, time, or reference number unless supplied by the event."
    return "BACKEND EVENT: site-visit booking failed. It was NOT booked. Do not claim confirmation. Offer retry or human assistance."


def finalize_reply(session: Dict[str, Any], decision: AgentDecision, booking_status: Optional[str]) -> str:
    """Give the model the backend event and ask it to produce the final natural response."""
    client = require_llm()
    messages = conversation_messages(session)
    messages.append({"role": "system", "content": (
        "Return only the final customer-facing reply as plain text. "
        "Preserve the language style of the customer. Follow the system prompt. "
        "Do not invent facts."
    )})
    if booking_status:
        messages.append({"role": "system", "content": booking_event_text(booking_status)})
    if session["handoff_requested"]:
        messages.append({
            "role": "system",
            "content": f"BACKEND EVENT: human handoff requested; reason={session['handoff_reason']}. Do not claim a human has already contacted the customer.",
        })
    messages.append({"role": "system", "content": f"Your structured decision was: {decision.model_dump_json()}"})
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.35,
        max_tokens=300,
    )
    return (response.choices[0].message.content or "").strip()


def analytics(session: Dict[str, Any], sid: str) -> Dict[str, Any]:
    p = session["profile"]
    return {
        "session_id": sid,
        "conversation_turns": len([m for m in session["messages"] if m["role"] == "user"]),
        "budget": p["budget"],
        "configuration": p["configuration"],
        "purpose": p["purpose"],
        "timeline": p["timeline"],
        "location_preference": p["location_preference"],
        "interest_level": p["interest_level"],
        "site_visit_status": session["booking_status"] or p["site_visit_status"],
        "follow_up_required": p["follow_up_required"],
        "follow_up_time": p["follow_up_time"],
        "contact_allowed": p["contact_allowed"],
        "handoff_requested": session["handoff_requested"],
        "handoff_reason": session["handoff_reason"],
        "ended": session["ended"],
    }


def chat(req: ChatRequest):
    sid = req.session_id or new_session()
    if sid not in SESSIONS:
        raise HTTPException(404, "Session not found")
    session = SESSIONS[sid]
    if session["ended"]:
        raise HTTPException(409, "Conversation has ended")

    session["messages"].append({"role": "user", "content": req.message})
    decision = decide_with_llm(session)
    apply_lead_updates(session, decision.lead_updates)
    session["last_intent"] = decision.intent

    booking_status = None
    if decision.action == "book_site_visit":
        booking_status = simulate_booking(session, req.demo_booking_result)
        session["profile"]["interest_level"] = "high"
    elif decision.action == "request_human":
        session["handoff_requested"] = True
        session["handoff_reason"] = decision.handoff_reason or "customer_requested_or_required_human_assistance"

    if decision.contact_allowed is False:
        session["profile"]["contact_allowed"] = False
    if decision.end_conversation or decision.contact_allowed is False:
        session["ended"] = True
    elif decision.intent in {"not_interested", "goodbye", "opt_out"}:
        session["ended"] = True

    # If the model explicitly ended the conversation, its initial reply is usually enough.
    # For action/handoff events, regenerate with backend truth so the response cannot lie.
    if booking_status or session["handoff_requested"]:
        reply = finalize_reply(session, decision, booking_status)
    else:
        reply = decision.reply.strip()

    session["messages"].append({"role": "assistant", "content": reply})
    return ChatResponse(
        session_id=sid,
        reply=reply,
        ended=session["ended"],
        booking_status=booking_status,
        intent=decision.intent,
        handoff_requested=session["handoff_requested"],
        lead_profile=analytics(session, sid),
    )


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    return chat(req)


@app.post("/api/end")
def end(req: EndRequest):
    if req.session_id not in SESSIONS:
        raise HTTPException(404, "Session not found")
    session = SESSIONS[req.session_id]
    session["ended"] = True
    return {"analytics": analytics(session, req.session_id)}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_configured": get_openai_client() is not None,
        "model": MODEL,
        "booking_simulation_result": BOOKING_SIMULATION_RESULT,
    }
