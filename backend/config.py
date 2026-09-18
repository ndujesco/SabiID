"""Single place for names and tunables so a rename is one edit."""
import os
from pathlib import Path

PRODUCT_NAME = "SabiID"
PRODUCT_TAGLINE = "Prove the fact. Not the file."
GATEWAY_ISSUER = "sabiid-gateway"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SOURCES_DIR = DATA_DIR / "sources"
FRONTEND_DIR = ROOT / "frontend"
DB_PATH = DATA_DIR / "sabiid.db"
GATEWAY_KEY_PATH = DATA_DIR / "gateway_ed25519.key"

# A scoped answer is valid for this many seconds after it is issued.
ATTESTATION_TTL_SECONDS = 15 * 60

# A living-person check is only "fresh" if it was answered within this window.
LIVENESS_WINDOW_SECONDS = 24 * 60 * 60

# How many payroll cycles a line can miss its living-person check before the
# money is held back for manual review.
GHOST_MISS_THRESHOLD = 3

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8099"))
