"""All tunable knobs in one place. Override any of them with environment variables / .env."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def _f(name, default):
    return float(os.getenv(name, default))


def _i(name, default):
    return int(os.getenv(name, default))


# ---- Models (swap with one line in .env; any provider supported by langchain's init_chat_model)
MODEL = os.getenv("MODEL", "google_genai:gemini-2.5-flash")
MODEL_FINDER = os.getenv("MODEL_FINDER", MODEL)   # proposes promos
MODEL_JUDGE = os.getenv("MODEL_JUDGE", MODEL)     # scores promos (can be a different / stronger model)
TEMPERATURE = _f("TEMPERATURE", 0.2)
REQUESTS_PER_SECOND = _f("REQUESTS_PER_SECOND", 0.15)  # ~9 req/min: safe for free tiers
MAX_CONCURRENCY = _i("MAX_CONCURRENCY", 4)

# ---- Promo rules from the brief
MIN_SEC = _f("PROMO_MIN_SEC", 20)
MAX_SEC = _f("PROMO_MAX_SEC", 60)
HOOK_WINDOW_SEC = _f("HOOK_WINDOW_SEC", 3)        # hook must start within the first 3 s
CLIFF_TAIL_SEC = _f("CLIFF_TAIL_SEC", 3)          # clip must end within 3 s after the cliffhanger beat
MAX_SEGMENTS = _i("MAX_SEGMENTS", 3)
MIN_SEGMENT_SEC = _f("MIN_SEGMENT_SEC", 3)

# ---- Pipeline sizes
PROMOS_PER_EPISODE = _i("PROMOS_PER_EPISODE", 3)
STITCH_POOL = _i("STITCH_POOL", 20)              # best single-episode candidates shown to the stitcher
STITCHED_PROMOS = _i("STITCHED_PROMOS", 5)
MAX_REFINE_ROUNDS = _i("MAX_REFINE_ROUNDS", 2)
DEDUPE_IOU = _f("DEDUPE_IOU", 0.5)
MAX_JUDGED = _i("MAX_JUDGED", 60)              # judge only the best N unique promos (free-tier budget)
INCLUDE_CAMERA = os.getenv("INCLUDE_CAMERA", "0") == "1"  # camera lines double tokens; actions carry visuals
PROMPT_VERSION = "v1"

# ---- Ranking (weights sum to 1)
W_HOOK = _f("W_HOOK", 0.35)
W_CLIFF = _f("W_CLIFF", 0.30)
W_STANDALONE = _f("W_STANDALONE", 0.25)
W_SPOILER = _f("W_SPOILER", 0.10)                 # applied as (10 - spoiler_risk)
EARLY_EP_BONUS = _f("EARLY_EP_BONUS", 5)          # points for promos from early episodes (funnel entry)
MAX_PER_EPISODE_IN_TOP = _i("MAX_PER_EPISODE_IN_TOP", 2)
TOP_N = _i("TOP_N", 10)
