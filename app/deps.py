"""Identity and access helpers shared by every router."""
from fastapi import HTTPException, Request

from . import db

APPROVER_ROLES = {"president", "treasurer"}


def viewer(request: Request) -> dict:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "Choose who you are viewing as, or sign up.")
    with db.tx() as conn:
        row = conn.execute("SELECT id, name FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        request.session.clear()
        raise HTTPException(401, "Choose who you are viewing as, or sign up.")
    return dict(row)


def membership(conn, group_id: int, user_id: int) -> dict:
    row = conn.execute("SELECT role FROM memberships WHERE group_id=? AND user_id=?",
                       (group_id, user_id)).fetchone()
    if not row:  # 404, not 403: don't reveal that the group exists
        raise HTTPException(404, "Group not found.")
    return {"role": row["role"]}


def require_approver(conn, group_id: int, user_id: int) -> str:
    role = membership(conn, group_id, user_id)["role"]
    if role not in APPROVER_ROLES:
        raise HTTPException(403, "Only the president or treasurer can do this.")
    return role


def require_role(conn, group_id: int, user_id: int, role: str, message: str) -> None:
    if membership(conn, group_id, user_id)["role"] != role:
        raise HTTPException(403, message)
