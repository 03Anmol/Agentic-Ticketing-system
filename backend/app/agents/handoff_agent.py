"""
Booking Handoff Agent - the "Launch Pad".

WHAT THIS IS FOR:
  docs/AUTOMATION_LIMITS.md fixes a hard boundary: nothing in this project
  drives irctc.co.in with a script - no automated login, navigation, seat
  selection, CAPTCHA, or payment. That boundary is not negotiable and this
  module does not weaken it.

  What it DOES do is squeeze everything legitimately automatable into the
  minutes BEFORE that boundary, so the human's remaining share of the work is
  as small and as fast as it can possibly be. At a Tatkal window the scarce
  resource is human seconds between 10:00:00 and 10:00:40; every second this
  module removes is a second not spent losing the seat.

  Concretely, the system does all of this on its own:
    - picks and ranks the train (orchestrator + comparison agent)
    - knows the exact window-open instant and counts down against server time
    - fires staged reminders at T-30m / T-10m / T-2m (scheduler_agent)
    - precomputes the exact selection spec so there is zero deciding at 10:00
    - formats passenger details into a paste-ready block
    - opens the real IRCTC page on the user's own browser, one click
    - captures the resulting PNR and emails the confirmation

  The human does only what the law and IRCTC's ToS reserve to them: log in,
  click their pre-saved passengers, solve the CAPTCHA, pay.

ON THE BOOKING URL - WHY THERE ARE NO PREFILL PARAMS:
  IRCTC's NGeT front-end does not publish a documented deep-link format for
  prefilling origin/destination/date, and this session could not verify one.
  Guessing param names would produce a URL that LOOKS like it works and
  silently ignores them - worse than not having it. So the link goes to the
  real search page and the precomputed `selection_spec` below carries the
  values for the user to enter/select. If a verified deep-link format is
  ever confirmed, `build_booking_url()` is the single place to add it.

THE REAL SPEED LEVERS (sourced, and all things IRCTC itself provides):
  - Master List: passengers pre-saved in the IRCTC profile are selectable
    with one click instead of typed - the single biggest time saver, and it
    must be done well before the window, which is why it is a T-30m step.
  - IRCTC eWallet: prepaid balance settles in ~2s and cannot fail the way a
    payment gateway can mid-Tatkal.
  - Being logged in 5-10 minutes early.
  - Declining travel insurance - it adds a processing step.
  These come from IRCTC's own feature set; using them is ordinary user
  behaviour, not automation against the platform.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from . import orchestrator

IRCTC_BOOKING_URL = "https://www.irctc.co.in/nget/train-search"

# Links that were actually reachable when checked (2026-08-30). Anything not on
# this list is given as an in-app click path instead - see _STEP_CONTENT.
IRCTC_EWALLET_INFO_URL = "https://contents.irctc.co.in/en/AboutEwallet.html"
PNR_ENQUIRY_URL = "https://www.indianrail.gov.in/enquiry/PNR/PnrEnquiry.html"

# WHY SOME STEPS HAVE A CLICK PATH INSTEAD OF A LINK:
#   Master List and eWallet-deposit live behind login inside IRCTC's Angular
#   SPA, and IRCTC publishes no documented deep-link route to either. A guessed
#   /nget/profile/... URL can't be verified (irctc.co.in refuses connections
#   from this environment) and, being an SPA, would likely return 200 and a
#   blank screen even if wrong - the worst kind of broken, since it looks like
#   the app's fault rather than a bad link. So those steps carry the exact menu
#   path IRCTC's own docs describe, plus a link to the page that does resolve.
_STEP_CONTENT = {
    "master_list": {
        "title": "Save passengers to your IRCTC Master List",
        "detail": "Add every passenger's name, age, gender and ID proof. At booking time they become "
                  "one-click selections instead of typed fields.",
        "why": "The single biggest time saver, and useless if left until the window is open.",
        "nav_path": "Log in > My Account > My Profile > Add/Modify Master List",
        "links": [{"label": "Open IRCTC", "url": IRCTC_BOOKING_URL}],
        "help": [
            "Keep ID numbers handy - Aadhaar or PAN. Tatkal requires an ID for at least one passenger.",
            "Set each passenger's berth preference here too; it carries into booking.",
            "Do this any time - it persists on your IRCTC account, so it's a one-off, not per-trip.",
        ],
    },
    "ewallet": {
        "title": "Top up your IRCTC eWallet",
        "detail": "Load at least the total fare. eWallet settles in about 2 seconds and can't fail "
                  "the way a bank gateway can mid-window.",
        "why": "Removes the slowest and least reliable step - payment.",
        "nav_path": "Log in > IRCTC eWallet > Deposit  (left navigation bar)",
        "links": [
            {"label": "About eWallet (official)", "url": IRCTC_EWALLET_INFO_URL},
            {"label": "Open IRCTC", "url": IRCTC_BOOKING_URL},
        ],
        "help": [
            "First time only: one-off Rs 50 registration fee plus a Rs 100 minimum deposit, with PAN or Aadhaar verification.",
            "Deposits range Rs 100 to Rs 10,000; that Rs 10,000 is also the maximum balance.",
            "Not worth setting up mid-rush - do it a day ahead if you can.",
        ],
    },
    "login": {
        "title": "Log in to IRCTC and stay logged in",
        "detail": "Sign in now and leave the tab open. Don't wait for the window - the login page "
                  "itself gets slow as it approaches.",
        "why": "Login contention peaks in the last two minutes before a Tatkal window.",
        "nav_path": None,
        "links": [{"label": "Open IRCTC login", "url": IRCTC_BOOKING_URL}],
        "help": [
            "If you're logged in already, just confirm the session hasn't expired.",
            "Use a wired or reliable connection; avoid public Wi-Fi.",
            "Forgot password? Reset it now, not at 09:59.",
        ],
    },
    "open_page": {
        "title": "Open the booking page with the journey entered",
        "detail": "Enter the journey from the spec below and search, so at the window you only pick "
                  "the class and go.",
        "why": "Search fields filled ahead of time means you land straight on selection.",
        "nav_path": None,
        "links": [{"label": "Open IRCTC booking page", "url": IRCTC_BOOKING_URL}],
        "help": [
            "Use the exact station codes from the spec - typing city names costs autocomplete time.",
            "Set the quota dropdown to TATKAL before searching, not after.",
        ],
    },
    "no_insurance": {
        "title": "Decline travel insurance at checkout",
        "detail": "Uncheck it. It adds a processing step you don't need during Tatkal.",
        "why": "Shaves seconds off the final submit.",
        "nav_path": None,
        "links": [],
        "help": ["This is on the passenger-details page, just below the passenger rows."],
    },
    # --- book-now variants: same substance, no clock pressure ---
    "login_now": {
        "title": "Log in to IRCTC",
        "detail": "Open the booking page and sign in with your own account.",
        "why": "",
        "nav_path": None,
        "links": [{"label": "Open IRCTC login", "url": IRCTC_BOOKING_URL}],
        "help": ["If you don't have an account yet, register on the same page - it takes a few minutes."],
    },
    "passengers_now": {
        "title": "Have passenger details ready",
        "detail": "Either pick them from your IRCTC Master List, or copy the block below.",
        "why": "",
        "nav_path": "Log in > My Account > My Profile > Add/Modify Master List",
        "links": [{"label": "Open IRCTC", "url": IRCTC_BOOKING_URL}],
        "help": [
            "Master List is worth setting up once even outside Tatkal - it saves typing on every future booking.",
            "Carry the same ID proof you enter here when you travel.",
        ],
    },
    "payment_now": {
        "title": "Have a payment method ready",
        "detail": "UPI, card or IRCTC eWallet - anything works when you're not racing a Tatkal clock.",
        "why": "",
        "nav_path": None,
        "links": [{"label": "About eWallet (official)", "url": IRCTC_EWALLET_INFO_URL}],
        "help": ["UPI is usually the quickest if you haven't set up eWallet."],
    },
    "insurance_now": {
        "title": "Decide on travel insurance",
        "detail": "Optional, and offered at checkout. No time pressure here, so take it if you want it.",
        "why": "",
        "nav_path": None,
        "links": [],
        "help": ["It's a small per-passenger amount covering accidents during the journey."],
    },
}

_IMMEDIATE_SEQUENCE = ["login_now", "passengers_now", "payment_now", "insurance_now"]
_SCHEDULED_SEQUENCE = ["master_list", "ewallet", "login", "open_page", "no_insurance"]

# Quota windows, IST, opening one day before the journey date.
TATKAL_AC_CLASSES = {"1A", "2A", "3A", "CC", "EC", "3E"}
TATKAL_AC_OPEN_HOUR = 10
TATKAL_NON_AC_OPEN_HOUR = 11


def build_booking_url(platform: str) -> str:
    """
    Single place a verified deep-link format would go. Deliberately returns a
    plain page URL rather than inventing query params - see module docstring.
    """
    return IRCTC_BOOKING_URL


def expected_tatkal_window(travel_date: str, travel_class: str | None) -> datetime | None:
    """
    Tatkal opens the day BEFORE travel: 10:00 IST for AC classes, 11:00 for
    non-AC. Returned so the UI can warn when a scheduled window doesn't match
    the class - a mismatch means showing up an hour late, which is the whole
    ballgame.
    """
    try:
        date_obj = datetime.strptime(travel_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    hour = TATKAL_AC_OPEN_HOUR if (travel_class or "").upper() in TATKAL_AC_CLASSES else TATKAL_NON_AC_OPEN_HOUR
    return (date_obj - timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)


# How long before the window each scheduled step should be done by. Ordering
# here is the order they must happen in, and it's deliberate: Master List and
# eWallet are account-level setup that can be done any time, so they come first
# and get the most slack; open_page is last because a page opened too early can
# have its session go stale.
_SCHEDULED_DEADLINES = {
    "master_list": timedelta(minutes=30),
    "ewallet": timedelta(minutes=20),
    "login": timedelta(minutes=10),
    "open_page": timedelta(minutes=2),
    "no_insurance": timedelta(0),
}


def build_checklist(
    sequence: list[str],
    progress: dict | None,
    window_open: datetime | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """
    Assembles the guided step list: content, links, help, done-state, and (for
    scheduled jobs) a deadline per step.

    `current` marks the first step not yet done - the one the UI expands. Steps
    already done stay in the list with their full content rather than being
    dropped, so the user can reopen a finished step to re-check what they did.
    """
    progress = progress or {}
    steps: list[dict] = []
    current_assigned = False

    for key in sequence:
        content = _STEP_CONTENT[key]
        done_at = progress.get(key)
        step = {
            "key": key,
            "title": content["title"],
            "detail": content["detail"],
            "why": content["why"],
            "nav_path": content["nav_path"],
            "links": content["links"],
            "help": content["help"],
            "done": bool(done_at),
            "done_at": done_at,
            "current": False,
            "due_at": None,
            "seconds_until_due": None,
            "overdue": False,
        }

        if window_open is not None and now is not None and key in _SCHEDULED_DEADLINES:
            due = window_open - _SCHEDULED_DEADLINES[key]
            step["due_at"] = due.isoformat()
            step["seconds_until_due"] = int((due - now).total_seconds())
            # A finished step can't be overdue - nagging about something already
            # done is exactly the noise that makes people ignore the list.
            step["overdue"] = (not step["done"]) and now > due

        if not step["done"] and not current_assigned:
            step["current"] = True
            current_assigned = True

        steps.append(step)

    return steps


def build_selection_spec(option: models.TrainOption | None, jr: models.JourneyRequest) -> dict:
    """
    The exact values to enter/select, precomputed so nothing has to be decided
    or looked up while the clock is running.
    """
    spec = {
        "from_station": jr.origin,
        "to_station": jr.destination,
        "journey_date": jr.travel_date,
        "quota": (jr.quota or "GENERAL").upper(),
        "passenger_count": jr.passenger_count,
    }
    if option is not None:
        spec.update({
            "train": f"{option.train_no} {option.train_name}",
            "train_no": option.train_no,
            "travel_class": option.travel_class,
            "departure_time": option.departure_time,
            "expected_fare": option.fare,
            "availability_at_search": option.availability_status,
        })
    return spec


def build_passenger_block(db: Session, passenger_count: int) -> dict:
    """
    Paste-ready passenger text. This is a fallback for anyone who hasn't set up
    the Master List yet - the Master List path is strictly faster and the
    checklist pushes it first.
    """
    profiles = db.query(models.PassengerProfile).order_by(models.PassengerProfile.created_at).all()
    lines = [
        f"{p.name} | {p.age} | {p.gender}" + (f" | {p.berth_preference}" if p.berth_preference else "")
        for p in profiles
    ]
    return {
        "profiles_on_file": len(profiles),
        "needed": passenger_count,
        "shortfall": max(0, passenger_count - len(profiles)),
        "clipboard_text": "\n".join(lines),
    }


def build_handoff(db: Session, job: models.ScheduledJob) -> dict:
    """
    Assembles everything the user needs at the window into one payload, so the
    UI is a single screen with nothing left to look up.
    """
    jr = db.get(models.JourneyRequest, job.journey_request_id)
    option = db.get(models.TrainOption, job.train_option_id) if job.train_option_id else None
    now = datetime.now()
    is_immediate = job.booking_mode == "immediate"

    seconds_to_window = int((job.window_open_time_ist - now).total_seconds())
    expected = expected_tatkal_window(jr.travel_date, option.travel_class if option else jr.travel_class)

    checklist = build_checklist(
        _IMMEDIATE_SEQUENCE if is_immediate else _SCHEDULED_SEQUENCE,
        job.checklist_progress,
        window_open=None if is_immediate else job.window_open_time_ist,
        now=now,
    )

    window_warning = None
    if not is_immediate and (jr.quota or "").upper() == "TATKAL" and expected is not None:
        drift = abs((job.window_open_time_ist - expected).total_seconds())
        if drift > 60:
            window_warning = (
                f"Scheduled window is {job.window_open_time_ist:%Y-%m-%d %H:%M}, but Tatkal for this "
                f"class normally opens {expected:%Y-%m-%d %H:%M} IST. Double-check before relying on it."
            )

    return {
        "job_id": job.id,
        "status": job.status,
        "booking_mode": job.booking_mode,
        "is_immediate": is_immediate,
        "platform": job.target_platform,
        "booking_url": build_booking_url(job.target_platform),
        "window_open_time_ist": None if is_immediate else job.window_open_time_ist.isoformat(),
        "server_time": now.isoformat(),
        "seconds_to_window": None if is_immediate else seconds_to_window,
        "window_warning": window_warning,
        "data_source": orchestrator.data_source_summary(),
        "selection_spec": build_selection_spec(option, jr),
        "checklist": checklist,
        "steps_done": sum(1 for s in checklist if s["done"]),
        "steps_total": len(checklist),
        "all_steps_done": all(s["done"] for s in checklist),
        "passengers": build_passenger_block(db, jr.passenger_count),
        "pnr": job.pnr,
        "pnr_enquiry_url": PNR_ENQUIRY_URL,
        "manual_steps_remaining": [
            "Log in, in your own browser session",
            "Search the route and pick the train + class",
            "Add passengers (Master List, or the block below)",
            "Solve the CAPTCHA",
            "Pay" + (" from your eWallet" if not is_immediate else " by UPI, card or eWallet"),
        ],
    }
