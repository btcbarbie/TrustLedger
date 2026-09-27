import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("trustledger")


def _provider(prefix: str, label_key: str, mode_key: str) -> dict | None:
    base = os.getenv(f"{prefix}BASE_URL", "")
    model = os.getenv(f"{prefix}MODEL", "")
    if not base or not model:
        return None
    return {
        "base_url": base,
        "api_key": os.getenv(f"{prefix}API_KEY", "") or "not-needed",
        "model": model,
        "label": os.getenv(label_key, "") or base,
        "image_mode": os.getenv(mode_key, "openai"),
    }


PRIMARY = _provider("LLM_", "LLM_PROVIDER_LABEL", "LLM_IMAGE_MODE") or {
    "base_url": "https://integrate.api.nvidia.com/v1",
    "api_key": "",
    "model": "meta/llama-3.2-11b-vision-instruct",
    "label": "NVIDIA Build",
    "image_mode": "openai",
}
FALLBACK = _provider("LLM_FALLBACK_", "LLM_FALLBACK_LABEL", "LLM_FALLBACK_IMAGE_MODE")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "60"))

SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if len(SESSION_SECRET) < 32:
    log.warning("SESSION_SECRET missing or short - using a random per-process secret")
    SESSION_SECRET = secrets.token_urlsafe(48)

DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "trustledger.db")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(ROOT / "data" / "uploads")))
SEED_PROOF_DIR = ROOT / "data" / "seed_proofs"
MAX_PROOF_BYTES = 5 * 1024 * 1024
