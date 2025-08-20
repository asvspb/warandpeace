from fastapi import APIRouter

# Placeholder router for WebAuthn endpoints to be implemented
router = APIRouter(prefix="/webauthn")

@router.get("/status")
async def webauthn_status():
    return {"status": "webauthn-not-implemented"}
