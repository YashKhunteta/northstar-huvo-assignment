# Northstar Homes — AI Sales Agent

A simple FastAPI-based conversational sales agent for the Huvo AI Forward Deployed Engineer assignment.

## Architecture

```text
Customer
   ↓
Web UI
   ↓
FastAPI
   ↓
LLM + system prompt
   ↓
Structured agent decision
   ├── conversation reply
   ├── lead-field updates
   ├── site-visit booking action
   └── human-handoff action
           ↓
      Backend tool result
           ↓
      Final customer reply
```

The key design principle is **LLM for language understanding, backend for state and action truth**.

### What is intentionally hardcoded
Only the supplied fictional business facts are embedded in the system prompt:

- Project: Northstar One
- Location: Sector 79, Gurugram
- Configurations: 2 BHK and 3 BHK
- Starting prices: 2 BHK ₹1.35 crore onwards; 3 BHK ₹1.75 crore onwards

These are the assignment's ground truth.

### What is NOT hardcoded
The application does not use keyword lists or regex rules to decide:

- customer intent
- booking intent
- budget
- configuration
- purpose
- timeline
- interest level
- objections
- follow-up requirement
- unknown-question escalation
- goodbye / not-interested behaviour

Those are returned by the LLM as structured decisions and validated by Pydantic.

The backend only enforces state integrity and executes actions requested by the model.

## Booking simulation

The site-visit booking is intentionally a mock backend tool because no real CRM/calendar was supplied.

Normal configuration:

```env
BOOKING_SIMULATION_RESULT=confirmed
```

The UI also has explicit demo controls for confirmed/failed outcomes. A customer's words such as `fail` never control booking success or failure.

The backend result is always authoritative:

- `confirmed` → agent may say the booking was confirmed
- `failed` → agent must say it was not booked and offer recovery

## Run locally

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env  # macOS/Linux

# Add OPENAI_API_KEY to .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Tests

The test suite mocks the LLM decision layer so behaviour can be tested deterministically without an API key:

```bash
pytest -q
```

The tests cover normal qualification, context memory, multilingual input shape, site-visit questions, booking success/failure, opt-out, not-interested, goodbye, unknown facts, human escalation, follow-up, analytics, and ended-session protection.

## Prompt approach

The system prompt is designed for both chat and voice. It focuses on:

1. Grounded project knowledge
2. Natural English/Hindi/Hinglish language matching
3. Conversational qualification rather than form-filling
4. Objection handling
5. Strict anti-hallucination behaviour
6. Tool/action truthfulness
7. Human escalation
8. Clean conversation termination

The model also returns a structured decision with an action. This prevents the backend from guessing intent using brittle keyword matching.

## Analytics

At conversation end the backend derives:

- budget
- configuration
- purpose
- timeline
- location preference
- interest level
- site-visit status
- follow-up requirement/time
- contact permission
- human handoff state/reason
- conversation turns
- ended state

## Known limitations

- Booking is simulated; there is no real CRM/calendar integration.
- Conversation state is in-memory and is lost when the server restarts.
- No authentication is included because this is an assignment demo.
- Voice transport/STT/TTS are not included; the same prompt is written to be voice-compatible.
- Production deployment would move session state to Redis/database and connect booking/handoff actions to real systems.
