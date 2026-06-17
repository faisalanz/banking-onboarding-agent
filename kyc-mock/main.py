"""
Eastern Bank demo — KYC mock service.

Default behavior: every /v1/verify call returns Fail / ID_MISMATCH
(matches the demo runbook). Two ways to change behavior live:

1. Global mode switch (survives until changed):
     POST /admin/mode/pass | fail | manual | error
2. Per-request email override (great mid-demo, no admin call needed):
     sarah+pass@example.com   -> Pass
     sarah+manual@example.com -> Manual Review
     sarah+error@example.com  -> HTTP 503
   Anything else follows the global mode.

For the "service down" resilience path you can either set mode=error
or simply point the Named Credential at a dead URL.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="KYC Mock", version="1.0.0")

STATE = {"mode": "fail"}
VALID_MODES = {"pass", "fail", "manual", "error"}

RESPONSES = {
    "pass": {
        "result": "Pass",
        "declineCode": None,
        "declineReason": None,
    },
    "fail": {
        "result": "Fail",
        "declineCode": "ID_MISMATCH",
        "declineReason": "Government ID could not be matched to the provided name.",
    },
    "manual": {
        "result": "Manual Review",
        "declineCode": "WATCHLIST_PARTIAL",
        "declineReason": "Partial match against a review list; analyst review required.",
    },
}


class VerifyRequest(BaseModel):
    firstName: str
    lastName: str
    email: Optional[str] = None
    # The Agentforce build sends productId; the SDK build sends product. Accept both.
    product: Optional[str] = None
    productId: Optional[str] = None


def resolve_mode(email: Optional[str]) -> str:
    if email:
        local = email.split("@")[0].lower()
        for m in VALID_MODES:
            if local.endswith(f"+{m}"):
                return m
    return STATE["mode"]


@app.get("/")
def health():
    return {"status": "ok", "service": "kyc-mock", "mode": STATE["mode"]}


@app.post("/v1/verify")
def verify(req: VerifyRequest):
    mode = resolve_mode(req.email)
    if mode == "error":
        return JSONResponse(status_code=503, content={"error": "KYC backend unavailable"})
    return RESPONSES[mode]


@app.get("/admin/mode")
def get_mode():
    return {"mode": STATE["mode"]}


@app.post("/admin/mode/{mode}")
def set_mode(mode: str):
    mode = mode.lower()
    if mode not in VALID_MODES:
        raise HTTPException(400, f"mode must be one of {sorted(VALID_MODES)}")
    STATE["mode"] = mode
    return {"mode": mode}
