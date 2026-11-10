# E-commerce Customer Support Voice Agent

Multilingual, multi-agent voice support for an e-commerce business. Recruiters open the dashboard (no login),
pick one of 15 seeded customers, inspect their records, and **talk to the agent with the microphone of any
device** (laptop, phone, tablet). Answers are grounded in PostgreSQL; actions need explicit confirmation.

FastAPI · SQLAlchemy async + asyncpg · PostgreSQL · LangGraph (`AsyncPostgresSaver`) · Groq · Gnani STT/TTS
(timbre-v2.5) · Streamlit · Pytest.

## Quick start (Docker)

```bash
cp backend/.env.example backend/.env      # add GROQ_API_KEY and GNANI_API_KEY
docker compose up --build
```
* Dashboard: http://localhost:8501 · API docs: http://localhost:8000/docs · Health: http://localhost:8000/api/health

## Quick start (local)

```bash
# 1. PostgreSQL (any 14+), e.g.: docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=voice_agent postgres:16
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # fill in keys
uvicorn app.main:app --reload              # creates tables, seeds data/customers.json, starts the checkpointer
# 2. frontend (new terminal)
cd frontend && pip install -r requirements.txt && streamlit run app.py
```
Without API keys everything still starts: data pages work, the agent uses its deterministic paths
(rule-based routing, template replies) and the voice client falls back to typed input. `/api/health` shows which
optional providers are configured.

## Using the microphone on a laptop, phone or any other device

The agent's voice client is a standalone web page **served by the backend** (`/api/voice/client`), so any device
with a browser and a microphone works. Streamlit embeds it, and also shows a direct link.

| Situation | What to do |
|---|---|
| Same computer as the server | Works on `http://localhost` (browsers treat it as secure). Allow the mic prompt. |
| Phone / tablet / another computer | Browsers **block the microphone on plain `http://` LAN addresses**. Expose the backend over **HTTPS**: |

```bash
# easiest: a free tunnel that gives you an https:// URL
cloudflared tunnel --url http://localhost:8000        # or: ngrok http 8000
# then, on the phone, open:   https://<tunnel-host>/api/voice/client
#   (pick a customer, tap "Create session", tap "Start call")
# or set BACKEND_PUBLIC_URL=https://<tunnel-host> before starting Streamlit so the dashboard's
# embedded client and "open on your phone" link use it.
```
Alternative: `uvicorn app.main:app --ssl-keyfile key.pem --ssl-certfile cert.pem` with a locally trusted cert (e.g. `mkcert`).

Client behaviour: capture at the device's native rate → resampled in-browser to **16 kHz PCM s16le mono** (the
format Gnani STT requires) and streamed in 1,024-byte frames; echo-cancellation/noise-suppression enabled;
iOS/Safari audio unlock on the Start tap; AudioWorklet with ScriptProcessor fallback; auto-reconnect; mute button;
language chips and a typed-message box as fallbacks. The session is **half-duplex**: the mic is ignored while the
agent speaks (prevents it hearing itself on speakers), so barge-in is not supported.

## How it works

```
Browser mic ──PCM/WebSocket──▶ FastAPI /api/voice/{conversation_id} ──▶ Gnani realtime STT (1 locale/session)
                                                      │ text
                                                      ▼
   LangGraph (thread_id = conversation_id, AsyncPostgresSaver) ── supervisor ─▶ order/product/payment/refund/complaint agents
        guardrails in/out · tool gateway · confirmation gate                    └▶ typed async tools ▶ PostgreSQL
                                                      │ grounded text
                                                      ▼
Browser speaker ◀──PCM chunks── Gnani realtime TTS (timbre-v2.5, voice chosen per language)
```
* **Language first**: every new conversation starts with the fixed greeting and language question; the choice is saved
  on the conversation + graph state, STT locale/TTS voice are reconfigured, and it only changes on an explicit request.
  Hinglish uses STT `en-IN` + voice Poorvi (`language="auto"`).
* **Identity**: the customer is bound to the conversation server-side at creation. If missing/invalid, the agent asks for
  the registered mobile number and discloses nothing until exactly one customer matches. The binding can never change.
* **Short-term memory**: LangGraph state per conversation persists via `AsyncPostgresSaver` (its own `langgraph` schema and
  pool). Application transcript lives separately in `messages`. Follow-ups like "the laptop" resolve from saved state.
* **Actions** (cancel order, register ticket, request refund — simulated records, no gateway): the specialist checks
  eligibility → backend stores a `pending_action` → agent asks yes/no → on "yes" (voice or the Confirm button) the backend
  **re-validates ownership and eligibility** and executes in one transaction. Confirmations expire, are tied to one action
  id, and cannot be replayed.
* **Guardrails** (backend code, not prompts): input validation, prompt-injection/exfiltration patterns, customer
  authorization on every query, tool allow-list + strict argument models (the customer id is injected from verified state —
  the model cannot choose it), grounding check of every ID/amount/date/product name in the reply, language/leak checks.
* **Database integrity**: composite foreign keys make it impossible to store a payment, refund or ticket that points to
  another customer's order.
* **Monitor**: every event shown in the right-hand panel is a persisted backend event (`conversation_events`).

## Data note (please read)

`data/customers.json` is used as provided and is never modified. It contains **16 of 20 support tickets whose
`customer_id` differs from the owner of the order they reference** (e.g. `TKT1001` → `ORD1003`, which belongs to CUS1002).
Because the schema forbids cross-customer references, the seeder treats the **order as the source of truth**, re-assigns
those tickets to the order owner, and logs each repair (`seed data repaired: ...`). Fix the JSON if you want the
directory's "open complaints" counts to match the file exactly.

## Evaluation

```bash
cd backend
python ../scripts/generate_eval_datasets.py                 # (re)generate datasets from customers.json
python -m app.evaluation.run_evaluation --no-judge          # deterministic checks only
python -m app.evaluation.run_evaluation                     # + LLM-as-a-Judge (set GROQ_JUDGE_MODEL to a different model)
python -m app.evaluation.run_evaluation --calibrate         # compare the judge with human-labelled reference examples
```
Or use the dashboard's *Evaluation* page / `POST /api/evaluations/run`. 47 cases across five datasets. Each case runs as a
real multi-turn conversation; **demo data is snapshotted and restored after every case**. Deterministic checks (customer
isolation, forbidden claims, grounding, expected tool, intent, DB-verified action outcome) are hard gates; the judge adds
1–5 scores, a hallucination flag, explanation, evidence and failure category. Reports are saved in
`backend/app/evaluation/reports/`.

## Tests

```bash
cd backend && pytest
```
Uses SQLite + in-memory LangGraph saver, no network, no keys, no real money movement.

## Configuration

See `backend/.env.example`. The Groq model is `GROQ_MODEL` (judge: `GROQ_JUDGE_MODEL`). Return window and confirmation
expiry: `RETURN_WINDOW_DAYS`, `PENDING_ACTION_TTL_SECONDS`. No Alembic: tables are created with `create_all` (never
dropped/altered); `scripts/reset_demo_database.py --yes` is the only destructive path and must be run by hand.
Windows: the app sets the selector event loop policy required by psycopg async.

## Known limitations

* No barge-in (half-duplex). STT is one locale per session, so the language question is asked in `en-IN`: say the language
  name in English, or tap a language chip.
* Replies to REST-confirmed actions are English templates; LLM replies follow the selected language.
* Static "language selected" sentences should be reviewed by native speakers.
* Verify Gnani voice/locale availability for your account: startup logs warnings from `validate_against_sdk()`.


## Editing details, customer management & the change log

**From the dashboard** (Customer Dashboard → *Edit profile* / *Edit delivery address*): name, email, mobile, preferred language
and address. Every field is validated by the backend (email format, 10-digit Indian mobile starting 6-9, 6-digit PIN,
unique email/mobile) and recorded in the change log. A delivery address can only change while the order is
`placed` or `processing`.

**From the voice agent** (same confirm step as cancellations - nothing is saved until the customer says yes):

| Say | What happens |
|---|---|
| "Change my address to 12 MG Road, Pune, Maharashtra 411001" | Agent reads the full new address back → "yes" saves it |
| "Update my email to aarav.new@example.com" | Agent reads it back and warns it is used to verify the customer → "yes" saves it |
| "Change my mobile number to 9876511111" | Same extra-explicit confirmation |
| "I want to change my name" | Agent asks for the new name first |
| "Change the delivery address for ORD1010" | Agent asks for the new address (only if the order has not shipped) |
| "What is my registered email?" | Reads your own details (mobile only in masked form) |

The backend re-validates ownership, the dispatch rule and uniqueness **at confirmation time**, and every edit made by voice is
logged with `source=voice_agent` and the conversation id. Without a Groq key, spoken addresses must be comma-separated
("12 MG Road, Pune, Maharashtra 411001"); with Groq, natural phrasing works.

**Customers page**: search/filter, *Add customer*, deactivate/reactivate (a deactivated customer cannot start new calls and any open
call is ended), and a *Demo data* tab that generates dummy customers with sample orders and payments (always at least one
`processing` order so address-edit and cancellation can be tested). Customers created from the app can be deleted again; the 15
seeded customers are protected. **Change Log page**: filter by customer/source/field and download CSV.



