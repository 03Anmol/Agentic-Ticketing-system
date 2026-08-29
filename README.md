# Train Ticket Agent — Phase 1 + 2 build

Implements the system described in [docs/PRD.md](docs/PRD.md) / [docs/FRD.md](docs/FRD.md): a LangGraph-orchestrated multi-agent search across IRCTC/ixigo/ConfirmTkt, a Tatkal-window scheduler, and an assisted-booking flow with a hard human-confirmation gate. Single FastAPI backend + a plain-JS frontend it serves directly — no separate Node build.

## What's real vs. stubbed

| Piece | Status |
|---|---|
| NL request parsing (Gemini 2.5 Flash) | **Real** |
| LangGraph orchestrator (parallel search → merge → rank) | **Real** |
| Comparison/ranking, results summary | **Real** |
| Web UI (search, jobs, passengers, audit) | **Real** |
| Scheduler (APScheduler, persistent, IST windows, misfire grace) | **Real** |
| Human-confirmation gate + single-use tokens + guardrail rate limiting | **Real** — this is the piece the legal constraint in PRD §2 depends on, tested end-to-end |
| Audit log | **Real** |
| IRCTC / ixigo / ConfirmTkt search agents | **Mock data**, deterministic per-query. See the big comment in [backend/app/agents/mock_data.py](backend/app/agents/mock_data.py) for exactly what's needed to make each one real (official API first, ToS-checked read-only scraping as fallback) |
| Actual platform login / form-fill during staging | **Stub** (`asyncio.sleep`) — same reason as above, plus this repo has no platform credentials to test against |
| CAPTCHA solving / final submit | **Not implemented, by design** — a human does this in-browser; the backend only ever asks "did a human just confirm" via the token |

## 1. Setup

```powershell
cd C:\Users\a\Documents\Anmol\AutoApply\job-automation-2-main\check\train-ticket-agent\backend

# reuse the existing venv at check\venv, or make a fresh one here - either works
C:\Users\a\Documents\Anmol\AutoApply\job-automation-2-main\check\venv\Scripts\python.exe -m pip install -r requirements.txt

copy .env.example .env
# then edit .env and put your real Gemini API key in GEMINI_API_KEY
# (.env is loaded automatically at startup - never edit .env.example itself,
#  that file is the template and should stay a placeholder)
```

## 2. Run

```powershell
cd C:\Users\a\Documents\Anmol\AutoApply\job-automation-2-main\check\train-ticket-agent\backend
C:\Users\a\Documents\Anmol\AutoApply\job-automation-2-main\check\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Open **http://127.0.0.1:8000/** — that's the whole web UI, served by the same FastAPI process (no separate frontend server needed).

A SQLite file `ticket_agent.db` is created next to `backend/` on first run (holds journeys, jobs, tokens, audit log, scheduler's own job store). Delete it any time to reset to a clean state.

## 3. Try it

1. **Search tab**: type something like *"Book AC 3-tier from Delhi to Mumbai this Friday, Tatkal, 2 adults"* → Parse request. Review the auto-filled fields (Gemini parses the free text) → Confirm & search. You'll get a ranked comparison across the three (mock) platforms with a plain-language summary.
2. Pick a row → **Schedule** → set a window-open time a minute or two out (for testing — real Tatkal windows are 10:00/11:00 IST) and a short lead time → Schedule staging.
3. Watch the **Scheduled Jobs** tab. When the trigger time hits, the job flips to `staged_and_waiting` and a notification banner appears at the top ("Go confirm now...").
4. Click **Confirm booking** on that job. This is the human-confirmation gate from PRD §2 / FRD FR-7: it issues a short-lived, single-use token and only then lets you complete the booking. Trying to confirm twice, or without a valid token, is rejected — check the **Audit Log** tab to see every step (including the rejections) logged.

## 4. Making the platform agents real

Each platform has its own file under `backend/app/agents/` (`irctc_agent.py`, `ixigo_agent.py`, `confirmtkt_agent.py`), all implementing the same `search()` signature from `agents/base.py`. To go live for a given platform:

1. Get official API access if it exists (this is how ixigo/ConfirmTkt themselves talk to IRCTC — they're licensed agents, not scrapers).
2. If none exists, confirm the platform's ToS/robots.txt permit automated *search* access before touching that page at all, and keep it strictly read-only.
3. Replace the body of that one `search()` method — nothing else in the system (orchestrator, comparison, UI, scheduler) needs to change.

**Do not** extend this to the booking/payment flow without keeping FR-7's human-confirmation gate intact — see [docs/PRD.md §2](docs/PRD.md) for why.

## 5. Project layout

```
train-ticket-agent/
  docs/PRD.md, FRD.md
  backend/
    app/
      main.py            FastAPI app, mounts the frontend as static files
      config.py           env-driven settings
      database.py, models.py, schemas.py
      llm.py               Gemini 2.5 Flash: NL parsing + result summaries
      agents/
        base.py             shared SearchAgent interface + DTO
        mock_data.py         shared mock generator (read this first)
        irctc_agent.py, ixigo_agent.py, confirmtkt_agent.py
        comparison_agent.py  merge + rank
        orchestrator.py      LangGraph graph (fan-out/fan-in)
        scheduler_agent.py   APScheduler wrapper (FR-5)
        booking_agent.py     staging + the confirmation gate (FR-6/FR-7)
        guardrail.py         independent gate enforcement + rate limiting (FR-9)
        notification_agent.py
        audit.py              append-only log writer (FR-10)
      routers/journey.py, schedule.py, misc.py
    requirements.txt, .env.example
  frontend/
    index.html, app.js, style.css   (no build step, just static files)
```

## 6. Known gaps vs. the full FRD (next steps, not done here)

- Auth/authZ (FRD §9) — there's no login; this is a single-user local tool as scoped in PRD §5, and the API is wide open (CORS `*`). Add real auth before exposing this beyond localhost.
- Secrets vault (FRD §9) — `.env` is fine for one user on one machine; don't commit it, and move to a real vault if this ever runs anywhere shared.
- Real notification channel (push/SMS/email) — currently just an in-app polling banner (PRD §13 left this open).
- Prompt-injection hardening on scraped content (FRD §5/§9) — moot right now since the search agents are mocked and don't ingest live external text yet; revisit when a real adapter starts parsing platform HTML/JSON into the LLM's context.
