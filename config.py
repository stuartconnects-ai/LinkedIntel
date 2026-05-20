# config.py
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file (fix: previously imported but never called)
load_dotenv()

# Project paths
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
TEMPLATES_DIR = ROOT_DIR / "templates"

# LinkedIn URLs
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"
LINKEDIN_NOTIFICATIONS_URL = "https://www.linkedin.com/notifications/"

# Google Gemini Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# OpenAI Configuration (optional, for message refinement only)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Browser settings
HEADLESS_MODE = False  # Set to True to run browser in background

# Action limits (for safety and to avoid being detected as a bot)
MAX_LIKES_PER_DAY = 20
MAX_COMMENTS_PER_DAY = 10
MAX_CONNECTION_REQUESTS_PER_DAY = 15
MAX_MESSAGES_PER_DAY = 10

# Delay settings (in seconds)
MIN_ACTION_DELAY = 1.5
MAX_ACTION_DELAY = 4.5
MIN_SCROLL_DELAY = 1.0
MAX_SCROLL_DELAY = 3.0

# Feed scraping settings
MAX_POSTS_TO_SCRAPE = 10
MAX_SCROLL_ITERATIONS = 10

# Reply tracking settings
MAX_REPLY_CHECK_POSTS = 20  # Max posts to check replies on per run
REPLY_CHECK_INTERVAL_HOURS = 6  # Min hours between reply checks on same post

# Target audience filtering (ICP — Ideal Customer Profile)
# Keywords to match in author headline/profile (case-insensitive)
TARGET_KEYWORDS = [
    "founder", "ceo", "coach", "agency owner", "entrepreneur",
    "business owner", "managing director", "co-founder", "owner",
    "president", "managing partner"
]

# Keywords to EXCLUDE from target audience (case-insensitive)
EXCLUDE_KEYWORDS = [
    "intern", "student", "graduate", "fresher", "junior",
    "seeking opportunities", "open to work", "looking for"
]

# Minimum match score to engage with post (0-100)
MIN_TARGET_MATCH_SCORE = 40
