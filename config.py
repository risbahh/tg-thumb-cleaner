import os

def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val

API_ID          = int(_require("API_ID"))
API_HASH        = _require("API_HASH")
SESSION_STRING  = _require("SESSION_STRING")
SOURCE_CHANNEL  = _require("SOURCE_CHANNEL")   # @username or -100xxx ID
DEST_CHANNEL    = int(_require("DEST_CHANNEL"))
ADMINS          = [int(x.strip()) for x in os.environ.get("ADMINS", "").split(",") if x.strip().isdigit()]
DELAY           = float(os.environ.get("DELAY", "2"))
LOG_CHANNEL     = int(os.environ["LOG_CHANNEL"]) if os.environ.get("LOG_CHANNEL", "").strip().lstrip("-").isdigit() else None
