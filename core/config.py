"""
SkinCoach — centralized configuration loaded from environment variables.

All modules import from here instead of calling os.getenv directly.
"""
import os


def _split_models(value: str | None, default: str) -> list[str]:
    if value is None:
        value = default
    return [m.strip() for m in value.split(",") if m.strip()]


# ─── API Key ──────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()

# ─── Model names ──────────────────────────────────────────────────────────────
VISION_MODEL = os.environ.get("VISION_MODEL", "openai/gpt-4o-mini").strip()
REASON_MODEL = os.environ.get("REASON_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
STRONG_MODEL = os.environ.get("STRONG_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
REASONER_A_MODEL = os.environ.get(
    "REASONER_A_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
).strip()
REASONER_B_MODEL = os.environ.get(
    "REASONER_B_MODEL", "qwen/qwen3-next-80b-a3b-instruct:free"
).strip()
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "openai/gpt-oss-120b:free").strip()

# ─── Fallback lists ───────────────────────────────────────────────────────────
_VISION_FALLBACKS_DEFAULT = "google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free"
_TEXT_FALLBACKS_DEFAULT = (
    "qwen/qwen3-next-80b-a3b-instruct:free,"
    "openai/gpt-oss-120b:free,"
    "nvidia/nemotron-3-super-120b-a12b:free"
)

VISION_FALLBACKS = _split_models(
    os.environ.get("VISION_FALLBACKS"), _VISION_FALLBACKS_DEFAULT
)
TEXT_FALLBACKS = _split_models(
    os.environ.get("TEXT_FALLBACKS"), _TEXT_FALLBACKS_DEFAULT
)

# ─── Other settings ───────────────────────────────────────────────────────────
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.3"))
TIMEOUT = int(os.environ.get("TIMEOUT", "120"))

# ─── Derived convenience flags ────────────────────────────────────────────────
LLM_AVAILABLE = bool(OPENROUTER_API_KEY)
