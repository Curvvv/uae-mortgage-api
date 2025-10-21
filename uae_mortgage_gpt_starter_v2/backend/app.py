from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .calculator import compare  # local module

# -----------------------------------------------------------------------------
# App & Logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("uae-mortgage-api")

APP_VERSION = "0.2.0"

app = FastAPI(title="UAE Mortgage Comparison API", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Health & Info
# -----------------------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, str]:
    return {"status": "ok", "service": "uae-mortgage-api", "version": APP_VERSION}

@app.get("/healthz")
def health() -> Dict[str, str]:
    return {"status": "healthy"}

# -----------------------------------------------------------------------------
# Compare endpoint
#   - Accepts either a raw object {...} or a wrapped payload { "data": {...} }
#   - Returns 422 with clear message on missing fields
# -----------------------------------------------------------------------------

REQUIRED_KEYS = {
    "principal_aed",
    "tenure_months",
    "horizon_months",
    "current_terms",
    "new_offer",
    "rate_scenarios",
}

@app.post("/compare")
def compare_endpoint(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Accepts:
      {
        ...fields...
      }
      or
      {
        "data": { ...fields... }
      }
    """
    request_id = str(uuid.uuid4())[:8]
    t0 = time.time()

    # Support both raw and wrapped payloads
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object.")

    # Basic validation
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required field(s): {', '.join(sorted(missing))}",
        )

    try:
        result = compare(data)
        log.info("req=%s status=ok elapsed_ms=%.1f", request_id, (time.time() - t0) * 1000)
        return result
    except HTTPException:
        # Bubble up explicit HTTP errors
        raise
    except Exception as e:
        # Log full details but return a safe message
        log.exception("req=%s status=error: %s", request_id, e)
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while calculating comparison. Please verify the payload or try again.",
        )

