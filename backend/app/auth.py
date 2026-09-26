"""Authentication and role-based access control.

Stateless HMAC-signed bearer tokens (no extra dependency), PBKDF2 password hashes, and
site scoping: a Mine Manager may approve or reject only actions for mines in their scope.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Boolean, String, select
from sqlalchemy.orm import Mapped, mapped_column

from ml.reference import MINES

from .db import DATA_DIR, Base, SessionLocal

TOKEN_TTL_S = int(os.getenv("MH_TOKEN_TTL_HOURS", "12")) * 3600
DEMO_PASSWORD = os.getenv("MH_DEMO_PASSWORD", "demo123")
DEMO_ACCOUNTS_ENABLED = os.getenv("MH_DEMO_ACCOUNTS", "1") == "1"

ROLES = {
    "ADMIN": {"label": "Administrator", "perms": {"read", "decide", "defer", "upload_data", "run_pipeline", "manage_users"}},
    "MINE_MANAGER": {"label": "Mine Manager", "perms": {"read", "decide", "defer"}},
    "PLANNER": {"label": "Mine Planning Engineer", "perms": {"read", "defer", "upload_data"}},
    "GEOLOGIST": {"label": "Exploration Geologist", "perms": {"read", "upload_data"}},
    "VIEWER": {"label": "Viewer (read-only)", "perms": {"read"}},
}


class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    site_scope: Mapped[str] = mapped_column(String(16), default="ALL")  # ALL | cluster id | mine id
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


DEMO_USERS = [
    ("admin", "Control Room Administrator", "ADMIN", "ALL"),
    ("manager.balaghat", "Mine Manager, Balaghat cluster", "MINE_MANAGER", "BLG"),
    ("manager.bhandara", "Mine Manager, Bhandara cluster", "MINE_MANAGER", "BHD"),
    ("manager.nagpur", "Mine Manager, Nagpur cluster", "MINE_MANAGER", "NGP"),
    ("planner", "Mine Planning Engineer", "PLANNER", "ALL"),
    ("geologist", "Exploration Geologist", "GEOLOGIST", "ALL"),
    ("viewer", "Ministry / Corporate Viewer", "VIEWER", "ALL"),
]


def _secret() -> bytes:
    env = os.getenv("MH_SECRET")
    if env:
        return env.encode()
    f = DATA_DIR / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip().encode()


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)).split("$")[2], dk)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user: User) -> str:
    payload = _b64(json.dumps({"sub": user.username, "role": user.role, "site": user.site_scope, "exp": int(time.time()) + TOKEN_TTL_S}).encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def decode_token(token: str) -> dict:
    try:
        payload, sig = token.split(".")
    except ValueError as e:
        raise HTTPException(401, "Malformed token") from e
    good = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        raise HTTPException(401, "Invalid token")
    data = json.loads(_unb64(payload))
    if data["exp"] < time.time():
        raise HTTPException(401, "Session expired — please sign in again")
    return data


def seed_users():
    with SessionLocal() as s:
        if s.scalar(select(User).limit(1)):
            return
        for username, name, role, scope in DEMO_USERS:
            s.add(User(username=username, full_name=name, role=role, site_scope=scope, password_hash=hash_password(DEMO_PASSWORD)))
        s.commit()


def authenticate(username: str, password: str) -> User:
    with SessionLocal() as s:
        u = s.get(User, username)
    if not u or not u.active or not verify_password(password, u.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return u


def public_user(u: User) -> dict:
    return {"username": u.username, "full_name": u.full_name, "role": u.role, "role_label": ROLES[u.role]["label"],
            "site_scope": u.site_scope, "permissions": sorted(ROLES[u.role]["perms"])}


def current_user(authorization: str | None = Header(None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    data = decode_token(authorization.split(" ", 1)[1])
    with SessionLocal() as s:
        u = s.get(User, data["sub"])
    if not u or not u.active:
        raise HTTPException(401, "Account disabled")
    return u


def require(perm: str):
    def dep(user: User = Depends(current_user)) -> User:
        if perm not in ROLES[user.role]["perms"]:
            raise HTTPException(403, f"Your role ({ROLES[user.role]['label']}) cannot perform this action")
        return user
    return dep


def in_scope(user: User, mine_id: str | None) -> bool:
    if user.site_scope == "ALL":
        return True
    if mine_id is None:
        return False
    mine = next((m for m in MINES if m["mine_id"] == mine_id), None)
    return bool(mine) and user.site_scope in (mine["mine_id"], mine["cluster_id"])
