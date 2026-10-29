"""Server-side identity for the embedded Bitrix24 personal workspace."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlparse


BITRIX_SESSION_COOKIE = "mavis_bitrix_session"


@dataclass(frozen=True)
class BitrixIdentity:
    portal: str
    user_id: str
    role: str
    expires_at: int


def portal_host(value: str) -> str:
    """Accept one configured portal host and reject paths, ports and schemes."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    try:
        has_port = parsed.port is not None
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        return ""
    if has_port or parsed.username or parsed.password:
        return ""
    return parsed.hostname.rstrip(".")


def director_ids(raw: str) -> set[str]:
    return {part.strip() for part in str(raw or "").split(",") if part.strip().isdigit()}


def _secret(secret: str) -> bytes:
    value = str(secret or "").strip()
    if len(value) < 24:
        raise ValueError("BITRIX_LOCAL_SESSION_SECRET не задан или слишком короткий")
    return value.encode("utf-8")


def issue_session(*, portal: str, user_id: str, role: str, secret: str, ttl_seconds: int, now: int | None = None) -> str:
    if role not in {"manager", "director"}:
        raise ValueError("Недопустимая роль Bitrix")
    host = portal_host(portal)
    if not host or not str(user_id).isdigit():
        raise ValueError("Некорректная Bitrix-идентичность")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "portal": host,
        "user_id": str(user_id),
        "role": role,
        "exp": issued_at + max(60, min(int(ttl_seconds), 12 * 60 * 60)),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(_secret(secret), f"mavis-bitrix:{encoded}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_session(token: str, *, secret: str, now: int | None = None) -> BitrixIdentity | None:
    try:
        encoded, supplied = str(token or "").split(".", 1)
        expected = hmac.new(_secret(secret), f"mavis-bitrix:{encoded}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(supplied, expected):
            return None
        raw = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
        identity = BitrixIdentity(
            portal=portal_host(payload.get("portal")),
            user_id=str(payload.get("user_id") or ""),
            role=str(payload.get("role") or ""),
            expires_at=int(payload.get("exp") or 0),
        )
        if not identity.portal or not identity.user_id.isdigit() or identity.role not in {"manager", "director"}:
            return None
        if identity.expires_at <= int(time.time() if now is None else now):
            return None
        return identity
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
