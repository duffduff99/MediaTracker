"""Sign-in, sign-out, the current user's profile/preferences, and user management."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..db import now, tx
from ..security import (
    SESSION_COOKIE,
    check_password_strength,
    create_session,
    current_user,
    delete_session,
    get_db,
    hash_password,
    require,
    verify_password,
)

router = APIRouter(prefix="/api")

Role = Literal["admin", "editor", "viewer"]


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "prefs": json.loads(row["prefs"] or "{}"),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


class LoginIn(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=500)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    throttle = request.app.state.throttle
    ip = request.client.host if request.client else "unknown"
    keys = (f"user:{body.username.lower()}", f"ip:{ip}")
    if throttle.blocked(*keys):
        raise HTTPException(429, "Too many failed sign-ins. Try again in 15 minutes.")
    row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username.strip(),)).fetchone()
    if row is None or not verify_password(row["password_hash"], body.password):
        throttle.fail(*keys)
        raise HTTPException(401, "Wrong username or password.")
    throttle.clear(*keys)
    settings = request.app.state.settings
    with tx(conn):
        token, expires = create_session(conn, row["id"], settings.session_days)
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now(), row["id"]))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return public_user(row)


@router.post("/auth/logout")
def logout(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(conn, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: sqlite3.Row = Depends(current_user)):
    return public_user(user)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=500)
    new_password: str = Field(max_length=500)


@router.post("/auth/password")
def change_password(
    body: PasswordIn, user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
):
    if not verify_password(user["password_hash"], body.current_password):
        raise HTTPException(400, "Current password is wrong.")
    check_password_strength(body.new_password)
    with tx(conn):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), user["id"]))
    return {"ok": True}


@router.put("/auth/prefs")
def update_prefs(body: dict, user: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    prefs = json.loads(user["prefs"] or "{}")
    prefs.update(body)
    encoded = json.dumps(prefs)
    if len(encoded) > 50_000:
        raise HTTPException(400, "Preferences too large.")
    conn.execute("UPDATE users SET prefs = ? WHERE id = ?", (encoded, user["id"]))
    return prefs


# ------------------------------------------------------------------ users (admin)


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    role: Role
    password: str = Field(max_length=500)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    password: str | None = Field(default=None, max_length=500)


@router.get("/users")
def list_users(_: sqlite3.Row = Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    return [public_user(r) for r in conn.execute("SELECT * FROM users ORDER BY username")]


@router.post("/users")
def create_user(body: UserIn, _: sqlite3.Row = Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    check_password_strength(body.password)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(409, "That username is taken.")
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (body.username, body.display_name.strip(), hash_password(body.password), body.role, now()),
        )
    return public_user(conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


def _admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]


@router.put("/users/{user_id}")
def update_user(
    user_id: int, body: UserUpdate, me_: sqlite3.Row = Depends(require("admin")),
    conn: sqlite3.Connection = Depends(get_db),
):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "User not found.")
    if body.role and body.role != "admin" and row["role"] == "admin" and _admin_count(conn) <= 1:
        raise HTTPException(400, "There must be at least one admin.")
    with tx(conn):
        if body.display_name:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (body.display_name.strip(), user_id))
        if body.role:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (body.role, user_id))
        if body.password:
            check_password_strength(body.password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.password), user_id))
            if user_id != me_["id"]:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return public_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


@router.delete("/users/{user_id}")
def delete_user(user_id: int, me_: sqlite3.Row = Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if user_id == me_["id"]:
        raise HTTPException(400, "You can't delete your own account.")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "User not found.")
    if row["role"] == "admin" and _admin_count(conn) <= 1:
        raise HTTPException(400, "There must be at least one admin.")
    with tx(conn):
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True}
