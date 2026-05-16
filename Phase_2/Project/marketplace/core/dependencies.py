from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, joinedload
#from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import os
import bcrypt
import logging

# ── Settings ──────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/marketplace_db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-use-a-long-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# ── Database ──────────────────────────────────────────────────────────────────

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Password hashing ──────────────────────────────────────────────────────────

#pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


#def hash_password(password: str) -> str:
#    return pwd_context.hash(password)

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


#def verify_password(plain: str, hashed: str) -> bool:
#    return pwd_context.verify(plain, hashed)

def verify_password(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(
        plain.encode("utf-8"),
        hashed.encode("utf-8"),
    )


# ── JWT ───────────────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from models.models import User
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: int = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as e:
        logging.warning(e)
        raise credentials_exception

    user = db.query(User).options(joinedload(User.roles)).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user
