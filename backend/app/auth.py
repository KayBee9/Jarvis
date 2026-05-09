from fastapi import Header, HTTPException
import jwt

from app.config import get_settings


def get_current_user_id(authorization: str | None = Header(default=None)) -> str:
    settings = get_settings()

    if not settings.supabase_jwt_secret:
        return settings.dev_user_id

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Token is missing subject")

    return subject
