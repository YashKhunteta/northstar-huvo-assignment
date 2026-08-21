# Northstar Homes — Behaviour Test Cases

| # | Input | Expected behaviour |
|---|---|---|
| 1 | `Mujhe 3 BHK chahiye, budget around 2 crore hai.` | Remember 3 BHK + ₹2 crore and respond naturally in Hinglish/Hindi. |
| 2 | `What is the process for a site visit?` | Answer the site-visit question; **do not** trigger booking. |
| 3 | `I want to book a site visit.` | Trigger simulated booking and report confirmed only because backend returned confirmed. |
| 4 | `I want to book a site visit - fail` | Report that booking failed; never say it was confirmed. |
| 5 | `Please don't contact me anymore.` | Mark `contact_allowed=false`, end conversation, and block further chat. |
| 6 | `I'm not interested, thanks.` | Politely close and mark the conversation ended. |
| 7 | `Okay thanks, bye!` | Give a brief goodbye and end the conversation. |
| 8 | `You said 2 BHK starts at 1.35 crore, right?` | Do not store ₹1.35 crore as the customer's budget. |
| 9 | `My budget is around 2 crore for a 3 BHK.` | Store budget ₹2 crore and configuration 3 BHK. |
| 10 | `What is the exact carpet area and RERA number?` | Do not guess; request/offer human escalation. |
| 11 | `Can I speak to a human sales person?` | Set `handoff_requested=true`; do not falsely claim a transfer happened. |
| 12 | `Call me tomorrow evening.` | Record follow-up requirement/time without pretending a real call was scheduled. |
| 13 | `Do you have site visits?` | Treat as information request, not a booking action. |
| 14 | `/api/end` after a conversation | Return structured analytics including budget, configuration, interest, site-visit status, follow-up and handoff state. |
