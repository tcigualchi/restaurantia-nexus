"""Password hashing and access tokens."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from nexus.config import Settings
from nexus.domain.errors import Unauthorized

ISSUER = "restaurantia-nexus"
AUDIENCE = "restaurantia-web"
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Constant-ish work even for unknown users to reduce user-enumeration timing signals.
        bcrypt.checkpw(b"invalid", bcrypt.hashpw(b"x", bcrypt.gensalt(rounds=4)))
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    is_demo: bool
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, *, is_demo: bool, settings: Settings, ttl_minutes: int | None = None
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes or settings.jwt_ttl_minutes)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "nbf": now,
            "exp": expires,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "jti": uuid.uuid4().hex,
            "demo": is_demo,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )
    return token, expires


def decode_access_token(token: str, settings: Settings) -> TokenClaims:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        return TokenClaims(
            user_id=uuid.UUID(claims["sub"]),
            is_demo=bool(claims.get("demo")),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Unauthorized("Sessão inválida ou expirada.", code="invalid_token") from exc


def hash_ip(ip: str, settings: Settings) -> str:
    """Keyed hash so raw IPs are never stored."""
    return hmac.new(settings.jwt_secret.get_secret_value().encode(), ip.encode(), hashlib.sha256).hexdigest()
