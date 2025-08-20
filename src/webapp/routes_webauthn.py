import os
import base64
from typing import Dict, Any, List
import sqlite3

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
import json

# Optional dependency: python-fido2
try:
    from fido2.server import Fido2Server
    from fido2.webauthn import (
        PublicKeyCredentialRpEntity,
        PublicKeyCredentialUserEntity,
        PublicKeyCredentialDescriptor,
    )
    WEBAUTHN_AVAILABLE = True
except Exception:
    WEBAUTHN_AVAILABLE = False

from src.database import get_db_connection, init_db

router = APIRouter(prefix="/webauthn")


def _rp_entity():
    rp_id = os.getenv("WEB_RP_ID", "localhost")
    rp_name = os.getenv("WEB_RP_NAME", "War&Peace Admin")
    if not WEBAUTHN_AVAILABLE:
        return None
    return PublicKeyCredentialRpEntity(id=rp_id, name=rp_name)


def _get_server():
    if not WEBAUTHN_AVAILABLE:
        return None
    return Fido2Server(_rp_entity())


def _admin_user_entity():
    # Single-admin variant. Use stable user id from env or default.
    user_id = (os.getenv("WEB_ADMIN_USER_ID", "admin")).encode("utf-8")
    if not WEBAUTHN_AVAILABLE:
        return None
    return PublicKeyCredentialUserEntity(id=user_id, name="admin", display_name="Administrator")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _from_b64url(data: str) -> bytes:
    pad = "=" * ((4 - (len(data) % 4)) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _list_credential_ids_for_user(user_id: str) -> List[bytes]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT credential_id FROM webauthn_credential WHERE user_id = ?", (user_id,))
        return [bytes(row[0]) for row in cur.fetchall()]


def _sanitize_for_json(value):
    """Recursively convert complex structures to JSON-safe (base64url for bytes)."""
    # Bytes-like
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _b64url(bytes(value))
    # Mapping
    try:
        from collections.abc import Mapping
    except Exception:
        Mapping = dict  # type: ignore
    if isinstance(value, Mapping):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    # Sequences (but not str/bytes handled above)
    if isinstance(value, (list, tuple, set)):
        seq = [_sanitize_for_json(v) for v in value]
        return seq if not isinstance(value, tuple) else tuple(seq)
    # Namedtuple
    if hasattr(value, "_asdict") and callable(getattr(value, "_asdict")):
        return _sanitize_for_json(value._asdict())
    # Objects with to_json/dict
    if hasattr(value, "to_json") and callable(getattr(value, "to_json")):
        try:
            return _sanitize_for_json(value.to_json())
        except Exception:
            pass
    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        try:
            return _sanitize_for_json(value.dict())
        except Exception:
            pass
    # Generic object -> attempt vars()
    try:
        return _sanitize_for_json(vars(value))
    except Exception:
        return value


@router.post("/register/options")
async def register_options(request: Request):
    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(status_code=501, detail="WebAuthn not available: install python-fido2")
    server = _get_server()
    user = _admin_user_entity()
    # Ensure DB schema exists and fetch existing credential ids
    try:
        existing_ids = _list_credential_ids_for_user(user_id=user.name)
    except sqlite3.OperationalError:
        # Likely missing table; initialize schema and retry once
        init_db()
        existing_ids = _list_credential_ids_for_user(user_id=user.name)

    # Build credential descriptors to exclude (compat with fido2 1.1.x)
    descriptors = [PublicKeyCredentialDescriptor(id=cid, type="public-key") for cid in existing_ids]

    # Compatibility with multiple python-fido2 versions
    # Try the most feature-complete call first, then progressively simplify
    try:
        options, state = server.register_begin(
            user,
            credentials=descriptors,
            user_verification="preferred",
        )
    except TypeError:
        try:
            options, state = server.register_begin(user, credentials=descriptors)
        except TypeError:
            options, state = server.register_begin(user)

    request.session["webauthn_state"] = state
    # Sanitize any remaining bytes deeply to ensure JSON-safe
    options = _sanitize_for_json(options)
    return Response(content=json.dumps(options), media_type="application/json")


@router.post("/register/verify")
async def register_verify(request: Request, attestation: Dict[str, Any]):
    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(status_code=501, detail="WebAuthn not available: install python-fido2")
    server = _get_server()
    state = request.session.get("webauthn_state")
    if state is None:
        raise HTTPException(status_code=400, detail="No registration in progress")

    # Convert base64url fields back to bytes
    try:
        attestation["response"]["attestationObject"] = _from_b64url(attestation["response"]["attestationObject"])
        attestation["response"]["clientDataJSON"] = _from_b64url(attestation["response"]["clientDataJSON"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid attestation data")

    auth_data = server.register_complete(state, attestation)

    # Persist credential
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO webauthn_credential (user_id, credential_id, public_key, sign_count, transports, aaguid)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "admin",
                auth_data.credential_id,
                auth_data.credential_public_key,
                auth_data.sign_count or 0,
                None,
                getattr(auth_data, "aaguid", None).hex if getattr(auth_data, "aaguid", None) else None,
            ),
        )
        conn.commit()

    request.session.pop("webauthn_state", None)
    return {"status": "ok"}


@router.post("/login/options")
async def login_options(request: Request):
    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(status_code=501, detail="WebAuthn not available: install python-fido2")
    server = _get_server()
    user = _admin_user_entity()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT credential_id FROM webauthn_credential WHERE user_id = ?", (user.name,))
        allow = [bytes(row[0]) for row in cur.fetchall()]

    if not allow:
        raise HTTPException(status_code=400, detail="No credentials registered")

    # Compatibility with multiple python-fido2 versions
    allow_descriptors = [PublicKeyCredentialDescriptor(id=cid, type="public-key") for cid in allow]
    try:
        options, state = server.authenticate_begin(
            credentials=allow_descriptors,
            user_verification="preferred",
        )
    except TypeError:
        try:
            options, state = server.authenticate_begin(credentials=allow_descriptors)
        except TypeError:
            options, state = server.authenticate_begin()
    request.session["webauthn_state"] = state
    # Sanitize any remaining bytes deeply to ensure JSON-safe
    options = _sanitize_for_json(options)
    return Response(content=json.dumps(options), media_type="application/json")


@router.post("/login/verify")
async def login_verify(request: Request, assertion: Dict[str, Any]):
    if not WEBAUTHN_AVAILABLE:
        raise HTTPException(status_code=501, detail="WebAuthn not available: install python-fido2")
    server = _get_server()
    state = request.session.get("webauthn_state")
    if state is None:
        raise HTTPException(status_code=400, detail="No login in progress")

    try:
        assertion["rawId"] = _from_b64url(assertion["rawId"]) if isinstance(assertion.get("rawId"), str) else assertion.get("rawId")
        assertion["response"]["authenticatorData"] = _from_b64url(assertion["response"]["authenticatorData"])
        assertion["response"]["clientDataJSON"] = _from_b64url(assertion["response"]["clientDataJSON"])
        assertion["response"]["signature"] = _from_b64url(assertion["response"]["signature"])
        if assertion["response"].get("userHandle"):
            uh = assertion["response"]["userHandle"]
            assertion["response"]["userHandle"] = _from_b64url(uh) if isinstance(uh, str) else uh
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid assertion data")

    # Load credential public key by ID
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT public_key, sign_count FROM webauthn_credential WHERE credential_id = ?", (assertion["rawId"],))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Unknown credential")
        stored_public_key, stored_sign_count = bytes(row[0]), int(row[1] or 0)

    auth_data = server.authenticate_complete(state, [
        {
            "type": "public-key",
            "id": assertion["rawId"],
            "publicKey": stored_public_key,
            "signCount": stored_sign_count,
        }
    ], assertion)

    # Update sign count and set session
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE webauthn_credential SET sign_count = ?, last_used_at = CURRENT_TIMESTAMP WHERE credential_id = ?",
            (auth_data.new_sign_count or stored_sign_count, auth_data.credential_id),
        )
        conn.commit()

    # Mark admin session
    request.session["admin"] = True
    request.session.pop("webauthn_state", None)
    return {"status": "ok"}

