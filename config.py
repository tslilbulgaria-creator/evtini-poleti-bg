"""Settings for the deal scanner. Edit these numbers to tune what counts as a deal."""
import os

# Airports scanned (IATA codes)
ORIGINS = ["SOF", "PDV", "VAR", "BOJ"]

# How many months ahead to scan (current month included)
MONTHS_AHEAD = 4

# Currency shown in posts
CURRENCY = "eur"

# Travelpayouts market (whose user searches fill the cache). Falls back to default if empty.
MARKET = "bg"

# --- Deal rules ---
# A price is a deal if it is at least this much below the route's typical price...
MIN_DROP = 0.40          # 40% below typical
# ...and saves at least this many euros
MIN_SAVING_EUR = 15
# Anything at or below this price is always a deal (one-way)
ALWAYS_DEAL_EUR = 19
# Need at least this many price points to judge "typical"
MIN_SAMPLES = 4
# Ignore departures sooner than this (too late to book)
MIN_DAYS_AHEAD = 3

# --- Posting rules ---
MAX_POSTS_PER_DAY = 8
MAX_POSTS_PER_RUN = 2
POST_HOUR_START = 8      # Sofia time
POST_HOUR_END = 22
# Don't repost the same route for this many days unless the price drops again
REPOST_AFTER_DAYS = 4
REPOST_EXTRA_DROP = 0.10

# --- Live verification (SerpApi / Google Flights), optional ---
MAX_VERIFY_PER_RUN = 3
MAX_VERIFY_PER_DAY = 8   # ~240/month fits SerpApi free plan (250)
VERIFY_TOLERANCE = 1.20  # live price may be up to 20% above cached and still count

# --- Secrets (set in GitHub -> Settings -> Secrets) ---
TP_TOKEN = os.environ.get("TP_TOKEN", "")
TP_MARKER = os.environ.get("TP_MARKER", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHANNEL = os.environ.get("TG_CHANNEL", "@evtini_poleti_bg")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")

DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
