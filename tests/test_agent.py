import json

from fastapi.testclient import TestClient

from app.main import AgentDecision, LeadUpdates, SESSIONS, app

client = TestClient(app)


def fresh():
    SESSIONS.clear()


def decision(intent, reply="Okay.", **kwargs):
    return AgentDecision(
        intent=intent,
        reply=reply,
        lead_updates=LeadUpdates(**kwargs.pop("lead_updates", {})),
        action=kwargs.pop("action", "none"),
        handoff_reason=kwargs.pop("handoff_reason", None),
        end_conversation=kwargs.pop("end_conversation", False),
        contact_allowed=kwargs.pop("contact_allowed", None),
    )


def mock_llm(monkeypatch, *decisions):
    queue = list(decisions)
    def fake_decide(session):
        return queue.pop(0)
    monkeypatch.setattr("app.main.decide_with_llm", fake_decide)
    monkeypatch.setattr("app.main.finalize_reply", lambda session, d, b: (
        "Booking confirmed by backend." if b == "confirmed" else
        "Booking failed; it was not booked." if b == "failed" else
        "A human can help you."
    ))


def test_health_and_homepage():
    fresh()
    assert client.get("/api/health").status_code == 200
    assert "Northstar Homes" in client.get("/").text


def test_context_memory_is_model_extracted(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision(
        "qualification", "Got it.",
        lead_updates={"configuration": "3 BHK", "budget": "₹2 crore"},
    ))
    r = client.post("/api/chat", json={"message": "Mujhe 3 BHK chahiye, budget around 2 crore hai."})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert SESSIONS[sid]["profile"]["configuration"] == "3 BHK"
    assert SESSIONS[sid]["profile"]["budget"] == "₹2 crore"


def test_site_visit_question_does_not_trigger_booking(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("site_visit_question", "I can help arrange one if you'd like."))
    r = client.post("/api/chat", json={"message": "What is the process for a site visit?"})
    assert r.status_code == 200
    assert r.json()["booking_status"] is None


def test_booking_action_calls_backend_and_confirms(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("site_visit_booking", action="book_site_visit", reply="I can arrange that."))
    r = client.post("/api/chat", json={"message": "I'd like to book a site visit."})
    assert r.status_code == 200
    assert r.json()["booking_status"] == "confirmed"
    assert r.json()["reply"] == "Booking confirmed by backend."


def test_booking_failure_is_backend_controlled_not_keyword_controlled(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("site_visit_booking", action="book_site_visit", reply="I can arrange that."))
    r = client.post("/api/chat", json={"message": "Please book a site visit." , "demo_booking_result": "failed"})
    assert r.status_code == 200
    assert r.json()["booking_status"] == "failed"
    assert "not booked" in r.json()["reply"]


def test_customer_word_fail_does_not_control_booking(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("site_visit_booking", action="book_site_visit", reply="I can arrange that."))
    r = client.post("/api/chat", json={"message": "Please book a site visit; I hope nothing fails."})
    assert r.status_code == 200
    assert r.json()["booking_status"] == "confirmed"


def test_opt_out_ends_and_blocks_followup(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("opt_out", "Understood. I won't contact you further.", end_conversation=True, contact_allowed=False))
    r = client.post("/api/chat", json={"message": "Please don't contact me anymore."})
    assert r.status_code == 200
    assert r.json()["ended"] is True
    sid = r.json()["session_id"]
    assert SESSIONS[sid]["profile"]["contact_allowed"] is False
    assert client.post("/api/chat", json={"session_id": sid, "message": "Actually tell me the price"}).status_code == 409


def test_not_interested_ends(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("not_interested", "Understood. Thanks for your time.", end_conversation=True))
    r = client.post("/api/chat", json={"message": "I'm not interested."})
    assert r.status_code == 200
    assert r.json()["ended"] is True


def test_goodbye_ends(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("goodbye", "Thank you. Have a great day!", end_conversation=True))
    r = client.post("/api/chat", json={"message": "Okay thanks, bye!"})
    assert r.status_code == 200
    assert r.json()["ended"] is True


def test_unknown_question_requests_human(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision(
        "unknown_fact",
        "I don't have that information. I can connect you with a human sales representative.",
        action="request_human",
        handoff_reason="unknown_project_information",
    ))
    r = client.post("/api/chat", json={"message": "What is the exact carpet area and RERA number?"})
    assert r.status_code == 200
    assert r.json()["handoff_requested"] is True
    assert SESSIONS[r.json()["session_id"]]["handoff_reason"] == "unknown_project_information"


def test_human_request_sets_handoff(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("human_request", action="request_human", handoff_reason="customer_requested_human"))
    r = client.post("/api/chat", json={"message": "Can I speak to a human?"})
    assert r.status_code == 200
    assert r.json()["handoff_requested"] is True


def test_model_controls_budget_instead_of_regex(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("general", "Got it."))
    r = client.post("/api/chat", json={"message": "You said 2 BHK starts at 1.35 crore, right?"})
    sid = r.json()["session_id"]
    assert SESSIONS[sid]["profile"]["budget"] is None


def test_model_can_store_explicit_budget(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("qualification", "Got it.", lead_updates={"budget": "₹2 crore", "configuration": "3 BHK"}))
    r = client.post("/api/chat", json={"message": "My budget is around 2 crore for a 3 BHK."})
    sid = r.json()["session_id"]
    assert SESSIONS[sid]["profile"]["budget"] == "₹2 crore"


def test_follow_up_is_model_extracted(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("follow_up", "Sure, I can note that.", lead_updates={"follow_up_required": True, "follow_up_time": "tomorrow evening"}))
    r = client.post("/api/chat", json={"message": "Call me tomorrow evening."})
    sid = r.json()["session_id"]
    p = SESSIONS[sid]["profile"]
    assert p["follow_up_required"] is True
    assert p["follow_up_time"] == "tomorrow evening"


def test_analytics_contains_required_fields(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("qualification", "Got it.", lead_updates={"budget": "₹2 crore", "configuration": "3 BHK", "purpose": "investment"}))
    r = client.post("/api/chat", json={"message": "3 BHK, budget 2 crore, for investment."})
    sid = r.json()["session_id"]
    end = client.post("/api/end", json={"session_id": sid})
    assert end.status_code == 200
    a = end.json()["analytics"]
    for key in ["budget", "configuration", "purpose", "timeline", "interest_level", "site_visit_status", "follow_up_required", "follow_up_time", "contact_allowed", "handoff_requested", "ended"]:
        assert key in a
    assert a["ended"] is True


def test_end_then_chat_is_blocked(monkeypatch):
    fresh()
    mock_llm(monkeypatch, decision("general", "Sure."))
    r = client.post("/api/chat", json={"message": "Tell me about Northstar One."})
    sid = r.json()["session_id"]
    assert client.post("/api/end", json={"session_id": sid}).status_code == 200
    assert client.post("/api/chat", json={"session_id": sid, "message": "What is the price?"}).status_code == 409
