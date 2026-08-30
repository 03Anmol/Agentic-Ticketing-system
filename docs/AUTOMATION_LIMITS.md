# What Can and Cannot Be Automated — IRCTC / ixigo / ConfirmTkt

This document exists so the boundary on automation gets settled once, in writing, instead of re-argued per request. It supersedes any earlier chat explanation — if this file and something said in conversation ever disagree, this file is authoritative for the project.

## The hard limit

**No automated login, navigation, seat selection, CAPTCHA handling, or payment triggering against irctc.co.in, ixigo.com, or confirmtkt.com will be built in this project, under any framing, with or without real credentials.**

This is not a caution that more careful engineering, a different storage location for credentials, or a "human still taps the final button" design resolves. It's a fixed boundary.

## Why — with sources, checked 2026-08-29

1. **IRCTC's own Terms & Conditions**: *"Use of automation software and/or Scripting Software is strictly prohibited."* This is unscoped — it does not say "prohibited for payment," it prohibits automation software against their platform generally. IRCTC explicitly reserves the right to deactivate accounts found using it. ([Terms and Conditions - IRCTC](https://contents.irctc.co.in/en/Terms%20and%20conditions.pdf))
2. **Section 143, Railways Act, 1989** criminalizes procuring railway tickets using unauthorized software/agents, with real enforcement history — including against individuals for personal use, not just resale rings.
3. **IRCTC introduced additional anti-bot technology as of July 1, 2025** specifically to detect and block automated Tatkal booking tools. ([IRCTC New Tatkal Booking Rules with Anti-Bot Technology](https://wbpay.in/en/irctc-tatkal-rules-new-tatkal-booking-rules-introduced-with-anti-bot-technology-easy-ticket-availability/))
4. **ixigo's robots.txt disallows crawling `/search/result/`** — the exact pages that would need to be scraped for live search data. This means even read-only search scraping of ixigo violates their stated crawl policy, separate from any ToS question.
5. **ConfirmTkt's robots.txt disallows `/rbooking/bridge/` and `/rbooking/trains/`** — their booking flow paths.

Consequences that follow directly from #1-#3, regardless of how the request is phrased:

| Ask | Why it's still no |
|---|---|
| "Store my IRCTC password, use it later" | Storage location was never the issue - see below |
| "Let me type it in live, don't save it" | The automation itself (not storage) is what's prohibited |
| "Just get to the payment QR, I'll tap it myself" | Getting there requires the automated login + seat-selection that's already prohibited on its own - the QR isn't a safe stopping point, it's past the line |
| "Build it carefully, follow the guidelines" | The applicable guideline is IRCTC's own ToS, and it's the thing prohibiting this |
| "You're the architect now, tell me how" | Reframing the request doesn't change what the target platform's terms say |

## What IS built and legitimate in this project

- Natural-language journey parsing (Gemini 2.5 Flash)
- Parallel search + comparison/ranking across three platforms, including berth-type preference ranking
- Tatkal-window scheduler (APScheduler) that stages a mock booking ahead of time
- A real human-confirmation gate: single-use tokens, independently enforced twice, fully audited
- Email + in-app notifications, including the mock "payment status"
- Full audit log of every action

All of this runs against **mock data** for the three platforms, by design (see `agents/mock_data.py`) — not because live search was technically hard, but because verifying it wouldn't violate ToS/robots.txt for each platform needed to happen first, and for ixigo/ConfirmTkt search-result scraping, that check came back negative (see #4 above). IRCTC's own robots.txt could not be fetched in this session (timed out twice) but is moot given #1.

## Maximum legitimate automation: the Launch Pad (added 2026-08-30)

The hard limit above says what can't be automated. This section says how far automation *does* go, so "we can't script IRCTC" isn't mistaken for "nothing can be automated."

The scarce resource at a Tatkal window is **human seconds between 10:00:00 and 10:00:40**. Everything that can legitimately be moved out of that window has been, into the minutes before it. The system does all of this on its own:

| Automated | Where |
|---|---|
| Parse the request, search, rank, recommend a train | orchestrator + comparison agents |
| Know the exact window-open instant, count down against server time | `handoff_agent.expected_tatkal_window()` |
| Warn when a scheduled window contradicts the class's real Tatkal hour | `build_handoff()` → `window_warning` |
| Fire prep reminders at T-30m / T-20m / T-10m unprompted | `scheduler_agent.register_readiness_reminders()` |
| Precompute the exact selection spec (train/class/quota/date/stations/fare) | `build_selection_spec()` |
| Format passengers into a paste-ready block, flag missing profiles | `build_passenger_block()` |
| Open the real IRCTC page in the user's own browser, one click | `build_booking_url()` |
| Capture the PNR afterwards, audit it, email confirmation | `POST /api/jobs/{id}/pnr` |

What the human still does — and what the law and IRCTC's ToS reserve to them: log in, select the train, pick passengers, solve the CAPTCHA, pay.

**The speed levers the checklist drives are IRCTC's own features**, so using them is ordinary user behaviour, not automation against the platform:
- **Master List** (My Profile → Master List): pre-saved passengers become one-click selections instead of typed fields. Biggest single time saver; must be done well before the window, hence T-30m.
- **IRCTC eWallet**: prepaid balance settles in ~2s and can't fail the way a payment gateway can mid-window.
- **Logging in 5–10 min early** — the login page itself slows as the window approaches.
- **Declining travel insurance** — removes a processing step at checkout.

**Why there are no deep-link prefill parameters:** IRCTC's NGeT front-end publishes no documented deep-link format for prefilling origin/destination/date, and it could not be verified. Guessing parameter names would produce a URL that *looks* like it works and silently ignores them — worse than not having it. `build_booking_url()` is the single place to add one if a format is ever confirmed.

**`status='confirmed'` vs. a PNR:** recording a PNR deliberately does **not** set `status='confirmed'`. That status belongs to this app's internal mock flow; a real railway booking is evidenced only by the presence of a PNR. Conflating them would make the audit log lie about which bookings are real.

## The one legitimate path to real automation

IRCTC has a genuine, open registration process to become an **Authorized Agent** — PAN + Aadhaar + an agreement, processed through `operations.irctc.co.in`'s Agent Interface. This is how ixigo and ConfirmTkt themselves get programmatic booking access: as licensed agents with an official API, not by scripting the consumer site. ([Agent Interface - operations.irctc.co.in](https://www.operations.irctc.co.in/AgentInterface/loginHome.jsf), [Rules & Regulations for e-Ticketing Service Providers](https://contents.irctc.co.in/en/Rules%20&%20Regulations%20for%20the%20Agents.pdf))

If that registration is completed and real API credentials are issued to you by IRCTC:
- That is a legitimate, ToS-compliant integration.
- The codebase is already structured for this: `irctc_agent.py`'s `search()` method gets swapped for real API calls, and the FRD (§FR-7) already anticipates the human-confirmation gate becoming optional *for that one licensed integration path only*.
- This is a business/legal process you'd complete outside of this codebase (IRCTC KYC + agreement) — it can't be shortcut by writing more code here.

Until that registration exists, the system stays exactly as built: real orchestration/scheduling/notification infrastructure around mock search data, with you doing the actual login/selection/payment yourself, manually, using the recommendations the system surfaces.
