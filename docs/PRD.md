# Product Requirements Document (PRD)
## Multi-Agent Train Ticket Search & Booking Assistant

| Field | Value |
|---|---|
| Author | Anmol |
| Status | v0.3 — Phase 1 + 2 built, Launch Pad shipped |
| Last updated | 2026-08-30 |
| Related doc | [FRD.md](./FRD.md), [AUTOMATION_LIMITS.md](./AUTOMATION_LIMITS.md) |

---

## 1. Purpose

Build a single natural-language interface ("book me a ticket from X to Y on this date") backed by a multi-agent system that:

- Searches train availability across **IRCTC, ixigo, ConfirmTkt** (and similar platforms).
- Compares options (price, availability, quota, class, travel time) and recommends the best.
- Schedules itself to act at the right moment for **Tatkal** and other time-gated quotas.
- Prepares and drives the booking flow as far as it legally can, then hands off to the user for final confirmation.
- Exposes all of this through a web dashboard, not a CLI.

## 2. Legal & Compliance Position — read this first

This is a hard constraint on the whole product, not a footnote.

- **Section 143 of the Railways Act, 1989** makes it a criminal offense to procure railway tickets using unauthorized software/agents — Tatkal quota is the specific, heavily-enforced target of this law. There have been real arrests over "Tatkal bot" software, including for personal use, not just resale.
- IRCTC's own terms of service prohibit automated/bot access to the booking flow (CAPTCHA-solving, scripted form submission, headless browser automation against irctc.co.in).
- **ixigo and ConfirmTkt are not scraping around IRCTC's defenses.** They are registered IRCTC-authorized booking agents with official B2B API access. That's the legitimate path to programmatic booking — not automating the consumer-facing website.

**Product decision:** this system will operate as an **assisted booking tool**, not an autonomous one.

- The agent may: search, compare, log in, pre-fill passenger/payment forms, and get everything staged and ready before a quota window opens.
- The agent may **not**: solve or bypass CAPTCHAs, submit the final booking, or complete payment without an explicit human action at that moment.
- If the user later obtains official IRCTC Agent API credentials (or a licensed partner integration), the human-confirmation gate can be removed for that specific integration path only — this is a configuration change on the Booking-Assist Agent, not a redesign (see [FRD.md §6](./FRD.md)).

Every requirement below is written under this constraint. Any future request to remove the human-confirmation gate against the consumer IRCTC site should be rejected at the design-review stage, not just at code review.

### 2a. On "agentic web browsing" of the booking sites (settled 2026-08-30)

This has now been asked four times, in four framings: fully autonomous booking; routing through ixigo/ConfirmTkt instead; taking any user's IRCTC ID and password as a service; and "actual web inference by the agent on that website... complete agentic capabilities."

**The answer does not change with the framing, because the framing was never what made it prohibited.** IRCTC's Terms & Conditions say *"Use of automation software and/or Scripting Software is strictly prohibited"* — unscoped, not limited to payment. An LLM driving a browser is automation software. Being agentic, being smart, or being careful does not exempt it; if anything an LLM-driven browser is the *most* clearly-covered case, since it is precisely software procuring tickets without authorization under Section 143 of the Railways Act, 1989.

The same applies to read-only scraping of the other two: ixigo's robots.txt disallows `/search/result/` and ConfirmTkt's disallows `/rbooking/`, which are exactly the paths a search agent would need.

**What the underlying want actually is, and how to satisfy it:** every one of those four requests is really asking for the same thing — *real trains, real availability, real fares* instead of placeholders. That is obtainable, and legitimately: through an authorized API (IRCTC Agent registration, or a licensed reseller). See §10 and [AUTOMATION_LIMITS.md](./AUTOMATION_LIMITS.md). The blocker on real data has never been the absence of a browser-driving agent; it is the absence of an API credential, and no amount of agent capability substitutes for one.

### 2b. Maximum legitimate automation — the Launch Pad

The constraint above says what the system may not do. This says how far it does go, so "we can't script IRCTC" is not mistaken for "nothing is automated."

The scarce resource at a Tatkal window is **human seconds between 10:00:00 and 10:00:40**. Everything that can legitimately be moved out of that window has been moved into the minutes before it. The system autonomously: parses the request, searches and ranks, computes the real window instant and warns on mismatch, fires prep reminders at T-30m/20m/10m, precomputes the exact selection spec, prepares passenger details, opens the real IRCTC page on one click, and captures the resulting PNR. The human does only what law and ToS reserve to them: log in, select, solve the CAPTCHA, pay.

## 3. Goals

1. One request ("Delhi to Mumbai, Friday, AC 3-tier, Tatkal") triggers parallel search across all configured platforms.
2. Results are normalized and ranked in a single comparison view (price, availability, confidence of getting a seat, refund/cancellation terms).
3. For time-gated quotas (Tatkal, premium Tatkal), the system schedules itself to log in and stage the booking just ahead of the window, then alerts the user the instant the window opens so they can complete the final step in seconds rather than racing to open five tabs.
4. Booking history, saved passenger profiles, and saved routes are persisted so repeat trips are near-instant to set up.
5. The whole thing is usable from a phone browser, since Tatkal windows are often checked on the go.

## 4. Non-Goals

- Fully unattended booking with zero human interaction (see §2).
- Reselling, bulk booking, or booking on behalf of third parties as a service — this is a personal-use tool.
- Payment processing/storage of card data inside this system — payment happens on the platform's own checkout, not ours.
- Building our own IRCTC agent-of-record relationship in v1 (that requires a formal IRCTC registration process, is a separate legal/business track, and is out of scope for the MVP).

## 5. Target User / Persona

- **Primary:** the user themself, booking personal/family train travel, frequently under Tatkal time pressure.
- Technically comfortable, wants a web dashboard rather than a script they have to babysit in a terminal.

## 6. User Stories

| # | Story |
|---|---|
| U1 | As a user, I type "book a ticket Delhi to Mumbai this Friday, 3AC" and get a normalized comparison across IRCTC/ixigo/ConfirmTkt within seconds. |
| U2 | As a user, I tell the system "Tatkal booking, train 12951, 3 passengers" the night before, and it schedules itself to be logged in and staged 2 minutes before the 10:00 AM window, then pings me to confirm. |
| U3 | As a user, when the window opens I get a push/SMS/webhook notification with a one-tap link that opens the pre-filled, CAPTCHA-ready checkout — I solve the CAPTCHA and click pay myself. |
| U4 | As a user, I can see a live status board of what each subagent is doing (searching, staged, waiting-for-window, waiting-for-confirmation, done, failed). |
| U5 | As a user, I can save passenger details and frequent routes so I don't retype them every time. |
| U6 | As a user, I can see a full audit log of every automated action taken on my behalf, timestamped. |
| U7 | As a user booking a normal (non-Tatkal) ticket, I press **Book now** and go straight to the handoff — I am never asked to invent a "window open time" for a journey that has no window. |
| U8 | As a user, the prep steps are a guided sequence: one step open at a time with its own links and tips, ticking it off advances to the next, and I can reopen any earlier step to re-read what I did. |
| U9 | As a user, my prep progress survives a page refresh or switching devices, because a Tatkal run starts 30 minutes before the window. |
| U10 | As a user, I can paste the PNR after booking and have it stored, audited and emailed, so the system's record reflects what really happened. |
| U11 | As a user, I can always tell whether what I'm looking at is real data or a placeholder, so I never act on a simulated fare believing it to be a quote. |

## 7. Scope

### MVP (Phase 1)
- Web UI: journey request form + results comparison + live agent status board.
- Orchestrator + 3 platform search subagents (IRCTC, ixigo, ConfirmTkt) — read-only search/availability, no booking automation yet.
- Gemini 2.5 Flash used for: parsing natural-language requests into structured journey queries, disambiguating station names/codes, summarizing/ranking results in plain language.
- Basic auth, saved passenger profiles, request history.

### Phase 2
- Cron/Scheduler Agent for Tatkal-window timing.
- Booking-Assist Agent: staged login + pre-fill, human-confirmation gate, notification agent (push/email/SMS).
- Guardrail/Policy Agent enforcing §2 at runtime (not just at design time).

### Phase 2b — Launch Pad (delivered 2026-08-30)
- **Two booking modes.** *Book now* for ordinary journeys (no window, goes straight to handoff) and *Schedule Tatkal* for timed quota windows. Offering only the scheduled path forced users to fabricate a window time for bookings that had none — the single most confusing thing in the app before this.
- **Guided step sequence** with live links, in-app click paths where IRCTC publishes no deep link, per-step tips, and DB-persisted progress that survives refresh or a device change.
- **Real Tatkal window computation** (day before travel; 10:00 IST AC, 11:00 non-AC) with a warning when the scheduled window contradicts the class.
- **PNR capture** — audited and emailed. Deliberately does not set `status='confirmed'`, which belongs to the internal mock flow; a real booking is evidenced only by a PNR.
- **Provenance labelling** — results carry whether each adapter is live or generated, and the UI says so where a fare is shown.

### Phase 3
- **Real search data — the top priority.** Everything above is real orchestration around placeholder trains, which is what makes the product feel hollow. Route this through an authorized API (see §10); it is not a scraping or agent-capability problem.
- Multi-passenger / multi-route batch scheduling.
- Alternate-route suggestions when the requested train has no availability (e.g. nearby dates, boarding stations, quota types).
- If pursued: formal IRCTC agent registration to unlock a fully compliant autonomous path for that one integration.

## 8. High-Level Architecture (narrative)

```
User (web) ──> Web Backend ──> Orchestrator Agent
                                    │
        ┌───────────────┬──────────┼───────────────┬────────────────┐
        ▼               ▼          ▼                ▼                ▼
  IRCTC Search    ixigo Search  ConfirmTkt      Scheduler/Cron   Notification
     Agent           Agent        Search           Agent            Agent
        │               │        Agent               │                │
        └───────┬───────┴───────────┘                 │                │
                 ▼                                     ▼                │
        Comparison/Ranking Agent              (registers staged jobs)   │
                 │                                     │                │
                 ▼                                     ▼                │
         Results shown to user ──user confirms──> Booking-Assist Agent──┘
                                                          │
                                                   Guardrail/Policy Agent
                                                   (blocks unattended submit,
                                                    enforces human gate)
                                                          │
                                                   Audit/Logging
```

Full breakdown, agent responsibilities, and data model are in [FRD.md](./FRD.md).

## 9. Success Metrics

- Time from "user submits journey request" to "comparison results shown": < 5 seconds (p95).
- For scheduled Tatkal jobs: staged and ready (logged in, form pre-filled) within 5 seconds of window open, notification delivered within 2 seconds of that.
- Zero incidents of unattended submission (tracked via audit log — every completed booking must have a human-confirmation event immediately preceding it).
- Booking history/search accuracy: normalized results match what the source platform actually shows, spot-checked periodically.

## 10. Assumptions & Dependencies

- ~~IRCTC/ixigo/ConfirmTkt have no official public read-only search API, so search will likely require reading their consumer pages for *search/availability only*.~~ **Spike completed 2026-08-29/30 — result: negative.** ixigo's robots.txt disallows `/search/result/` and ConfirmTkt's disallows `/rbooking/`, i.e. exactly the paths a search adapter would need, and IRCTC's ToS bans automation software unscoped. Reading their pages is therefore off the table even for read-only search. The three shipped adapters return generated data, and the UI labels it as such.
- **Real data must come from an authorized API.** Two viable routes, both outside the codebase:
  1. **IRCTC Authorized Agent registration** — PAN + Aadhaar + agreement via `operations.irctc.co.in`, roughly ₹1,000–6,000 and 2–10 days. This is how ixigo and ConfirmTkt themselves get programmatic access.
  2. **A licensed reseller API** (IndiRail, RailYatri-style partner programmes) — faster to start, no KYC on your side, but a subscription/commission cut and a dependency on their uptime and terms.
  Each platform adapter implements one `search()` method behind a common interface, so swapping either in touches one file per platform and nothing else.
- **Open government data covers train identities only.** `data.gov.in`'s Indian Railways Train Time Table (~2,810 trains) gives real train numbers, names and stop-by-stop schedules, and the fetcher for it is already written (`agents/real_train_catalog.py`, needs a free API key plus the dataset's resource ID). It is a timetable, not a live seat-availability feed — it cannot tell you what is bookable right now.
- User has accounts on all three platforms already.
- Deployment target: single web app, self-hosted or small cloud VM (not a multi-tenant SaaS product).
- Gemini API key management is the user's responsibility (already in use — see [app.py](../../check/app.py)).

## 11. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Platform blocks/rate-limits automated search traffic | Respect robots.txt/ToS per platform, add backoff, keep request volume low, consider official APIs where they exist |
| Scope creep toward full autonomous booking | §2 is a standing design constraint; any PR/feature removing the human-confirmation gate against a non-licensed integration should be rejected |
| Platform HTML/flow changes break scraping-based search | Isolate each platform behind its own subagent/adapter interface so one breaking doesn't take down the others |
| Secrets (platform login, Gemini API key) leaking | Central secrets manager, never in source control, scoped per-agent credentials |
| LLM misparses a journey request (wrong date/station) | Always show the structured interpretation back to the user for confirmation before searching |

## 12. Milestones

1. **Spike (1–2 days):** confirm what each platform's search/availability flow looks like, whether an official API exists, ToS check.
2. **Phase 1 MVP:** orchestrator + search subagents + comparison UI + Gemini parsing.
3. **Phase 2:** scheduler, booking-assist agent with human-confirmation gate, notifications, guardrail agent.
4. **Phase 3:** batch/multi-route, alternate-route suggestions, optional formal IRCTC agent registration track.

## 13. Open Questions

- Do any of the three platforms offer a public/partner API the user already has or can get access to (this would remove most of the scraping risk for search)?
- Preferred notification channel(s): push (needs a mobile app or PWA), SMS (needs a provider like Twilio/MSG91), email, or a simple webhook/Telegram bot?
- Where will this be hosted (local machine only vs. a small cloud VM), since that affects the scheduler's reliability for Tatkal timing?
