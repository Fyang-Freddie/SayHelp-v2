from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    cred = HTTPException(status.HTTP_401_UNAUTHORIZED, "无效或过期的凭证", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(token)
    except Exception:
        raise cred
    user_id = payload.get("sub")
    if user_id is None:
        raise cred
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise cred
    return user

def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return user
    return checker
