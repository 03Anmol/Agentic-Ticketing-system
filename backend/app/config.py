import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'ticket_agent.db'}")

CONFIRMATION_TOKEN_TTL_SECONDS = int(os.environ.get("CONFIRMATION_TOKEN_TTL_SECONDS", "120"))
DEFAULT_LEAD_TIME_SECONDS = int(os.environ.get("DEFAULT_LEAD_TIME_SECONDS", "120"))

PLATFORM_SEARCH_TIMEOUT_SECONDS = float(os.environ.get("PLATFORM_SEARCH_TIMEOUT_SECONDS", "8"))

# Rate limiting: max login/search attempts per platform per this window (FR-9)
GUARDRAIL_RATE_LIMIT_WINDOW_SECONDS = 60
GUARDRAIL_RATE_LIMIT_MAX_CALLS = 10

# FR-8 email channel. This is YOUR email account's own SMTP credentials
# (e.g. a Gmail address + an "app password" you generate for it), used only
# to send status notifications to yourself - never IRCTC/platform credentials.
# If unset, email sending is skipped and notifications stay in-app only.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
NOTIFY_EMAIL_TO = os.environ.get("NOTIFY_EMAIL_TO", "s.faridi007@gmail.com")

# Optional - real train identities (numbers/names) from India's open
# government data portal, replacing the fictional catalog in mock_data.py.
# Free key: https://api.data.gov.in/signup/ . The resource ID is specific to
# the "Indian Railways Train Time Table" dataset and must be copied from
# that dataset's page on data.gov.in (its "API" tab shows the exact ID and
# a sample call) - see agents/real_train_catalog.py for why this couldn't
# be hardcoded here. Availability/fare/exact timing stay simulated either
# way - see docs/AUTOMATION_LIMITS.md for why.
DATA_GOV_IN_API_KEY = os.environ.get("DATA_GOV_IN_API_KEY", "")
DATA_GOV_IN_TRAIN_RESOURCE_ID = os.environ.get("DATA_GOV_IN_TRAIN_RESOURCE_ID", "")
