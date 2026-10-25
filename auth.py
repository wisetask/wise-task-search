import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)

DEFAULT_PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "certs" / "public.pem"
DEFAULT_ISSUER = "wise-task"
ALGORITHMS = ["RS256"]


@lru_cache
def _load_public_key() -> str:
    path = Path(os.getenv("JWT_PUBLIC_KEY", str(DEFAULT_PUBLIC_KEY_PATH)))
    return path.read_text()


def _issuer() -> Optional[str]:
    return os.getenv("JWT_ISSUER", DEFAULT_ISSUER) or None


def verify_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            _load_public_key(),
            algorithms=ALGORITHMS,
            issuer=_issuer(),
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен истёк",
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Невалидный токен: {exc}",
        ) from exc


async def require_authenticated_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется Bearer токен",
        )
    return verify_access_token(credentials.credentials)
