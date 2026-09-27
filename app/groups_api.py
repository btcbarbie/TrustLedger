"""Sign-up (simulated), group creation, invites, contributions and WhatsApp import."""
import json
import math
import secrets
import time
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from . import db, schedule, whatsapp
from .deps import membership, require_approver, viewer
from .money import format_naira, parse_naira

router = APIRouter(prefix="/api")
OTHER = {"treasurer": "president", "president": "treasurer"}


def _kobo(text: str, what: str = "amount") -> int:
    k = parse_naira(text)
    if k is None:
        raise HTTPException(422, f"Enter a valid {what}, for example 5000 or 5,000.")
    return k


def _new_user(conn, name: str, aliases: list[str] | None = None) -> int:
    return conn.execute("INSERT INTO users(name, aliases) VALUES (?,?)",
                        (name.strip()[:60], json.dumps(aliases or []))).lastrowid


def _new_group(conn, name: str, creator: int, origin: str) -> int:
    return conn.execute("INSERT INTO groups(name, invite_code, origin, created_by, created_at) VALUES (?,?,?,?,?)",
                        (name.strip()[:80], secrets.token_urlsafe(6), origin, creator, db.now_iso())).lastrowid


def _add_member(conn, gid: int, uid: int, role: str, actor: int) -> None:
    conn.execute("INSERT INTO memberships(group_id,user_id,role) VALUES (?,?,?)", (gid, uid, role))
    db.append_event(conn, gid, "member_added", {"user_id": uid, "role": role}, actor_id=actor)


# ---------- simulated sign-up ----------

class SignupIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)


@router.post("/signup")
def signup(body: SignupIn, request: Request):
    """MVP: no password or phone. Real sign-up (phone OTP) replaces this later."""
    name = " ".join(body.name.split())
    if len(name) < 2:
        raise HTTPException(422, "Enter your name.")
    with db.tx() as conn:
        uid = _new_user(conn, name)
    request.session["uid"] = uid
    return {"user": {"id": uid, "name": name}}


@router.get("/showcase")
def showcase():
    """Public: the preloaded DEMO groups only (synthetic data), for the landing page."""
    with db.tx() as conn:
        groups = conn.execute("SELECT id, name, kind, blurb FROM groups WHERE invite_code LIKE '%-demo' ORDER BY id").fetchall()
        out = []
        for g in groups:
            people = [dict(r) for r in conn.execute(
                "SELECT u.id, u.name, m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.group_id=? "
                "ORDER BY CASE m.role WHEN 'president' THEN 0 WHEN 'treasurer' THEN 1 ELSE 2 END, u.name", (g["id"],))]
            t = conn.execute("SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount_kobo ELSE -amount_kobo END),0) bal, "
                             "COUNT(*) n FROM entries WHERE group_id=? AND status='verified'", (g["id"],)).fetchone()
            out.append({**dict(g), "people": people, "balance_kobo": t["bal"], "verified_entries": t["n"]})
    return out


@router.post("/signout")
def signout(request: Request):
    request.session.clear()
    return {"ok": True}


# ---------- create a group ----------

class ContributionIn(BaseModel):
    amount: str
    frequency: Literal["weekly", "monthly"]
    first_due: date
    periods: int = Field(ge=1, le=schedule.MAX_PERIODS)


class GoalIn(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    amount: str
    due_date: date


class GroupIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    my_role: Literal["treasurer", "president"]
    members: list[str] = Field(default_factory=list, max_length=40)
    second_leader: str
    contribution: ContributionIn | None = None
    goal: GoalIn | None = None


@router.post("/groups")
def create_group(body: GroupIn, user=Depends(viewer)):
    members = [" ".join(m.split())[:60] for m in body.members if m and m.strip()]
    if len({m.lower() for m in members}) != len(members):
        raise HTTPException(422, "Each member name must be different.")
    leader = " ".join(body.second_leader.split())
    if leader.lower() not in {m.lower() for m in members}:
        raise HTTPException(422, f"Choose a {OTHER[body.my_role]} from your members, so someone else can confirm your entries.")
    with db.tx() as conn:
        gid = _new_group(conn, body.name, user["id"], "app")
        db.append_event(conn, gid, "group_created", {"name": body.name.strip()}, actor_id=user["id"])
        _add_member(conn, gid, user["id"], body.my_role, user["id"])
        for m in members:
            role = OTHER[body.my_role] if m.lower() == leader.lower() else "member"
            _add_member(conn, gid, _new_user(conn, m), role, user["id"])
        if body.contribution:
            c = body.contribution
            ids = schedule.create_series(conn, gid, f"{c.frequency.title()} contribution", c.frequency,
                                         _kobo(c.amount), c.first_due, c.periods)
            db.append_event(conn, gid, "obligation_added", {"series": f"{c.frequency.title()} contribution",
                            "amount_kobo": _kobo(c.amount), "periods": len(ids)}, actor_id=user["id"])
        if body.goal:
            _add_goal(conn, gid, body.goal, user["id"])
        code = conn.execute("SELECT invite_code FROM groups WHERE id=?", (gid,)).fetchone()["invite_code"]
    return {"group_id": gid, "invite_code": code}


def _add_goal(conn, gid: int, g: GoalIn, actor: int) -> int:
    oid = conn.execute("INSERT INTO obligations(group_id,title,category,amount_due_kobo,due_date) VALUES (?,?,?,?,?)",
                       (gid, g.title.strip(), "goal", _kobo(g.amount), g.due_date.isoformat())).lastrowid
    db.append_event(conn, gid, "obligation_added", {"title": g.title.strip(), "amount_kobo": _kobo(g.amount),
                    "due_date": g.due_date.isoformat()}, actor_id=actor)
    return oid


# ---------- add a contribution to an existing group ----------

class ObligationIn(BaseModel):
    kind: Literal["goal", "recurring"]
    goal: GoalIn | None = None
    contribution: ContributionIn | None = None
    series_name: str | None = Field(default=None, max_length=60)


@router.post("/groups/{group_id}/obligations")
def add_obligation(group_id: int, body: ObligationIn, user=Depends(viewer)):
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        if body.kind == "goal":
            if not body.goal:
                raise HTTPException(422, "Add the goal's name, amount and due date.")
            return {"created": [_add_goal(conn, group_id, body.goal, user["id"])]}
        c = body.contribution
        if not c:
            raise HTTPException(422, "Add the contribution amount, how often, and the first due date.")
        series = (body.series_name or f"{c.frequency.title()} contribution").strip()
        if conn.execute("SELECT 1 FROM obligations WHERE group_id=? AND series=?", (group_id, series)).fetchone():
            series = f"{series} ({date.today():%b %Y})"
        ids = schedule.create_series(conn, group_id, series, c.frequency, _kobo(c.amount), c.first_due, c.periods)
        db.append_event(conn, group_id, "obligation_added", {"series": series, "amount_kobo": _kobo(c.amount),
                        "periods": len(ids)}, actor_id=user["id"])
        return {"created": ids}


# ---------- invites ----------

@router.get("/groups/{group_id}/invite")
def invite(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        return {"code": conn.execute("SELECT invite_code FROM groups WHERE id=?", (group_id,)).fetchone()["invite_code"]}


@router.get("/join/{code}")
def join_info(code: str):
    with db.tx() as conn:
        g = conn.execute("SELECT g.id, g.name, (SELECT COUNT(*) FROM memberships m WHERE m.group_id=g.id) n "
                         "FROM groups g WHERE invite_code=?", (code,)).fetchone()
    if not g:
        raise HTTPException(404, "This invite link is not valid.")
    return {"group": g["name"], "members": g["n"]}


@router.post("/join/{code}")
def join(code: str, user=Depends(viewer)):
    with db.tx() as conn:
        g = conn.execute("SELECT id FROM groups WHERE invite_code=?", (code,)).fetchone()
        if not g:
            raise HTTPException(404, "This invite link is not valid.")
        if not conn.execute("SELECT 1 FROM memberships WHERE group_id=? AND user_id=?", (g["id"], user["id"])).fetchone():
            _add_member(conn, g["id"], user["id"], "member", user["id"])
    return {"group_id": g["id"]}


# ---------- WhatsApp import: preview, then create ----------

_PREVIEWS: dict[str, dict] = {}
PREVIEW_TTL_S = 30 * 60


@router.post("/import/whatsapp/preview")
def import_preview(chat_file: UploadFile = File(...), user=Depends(viewer)):
    raw = chat_file.file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise HTTPException(413, "The chat export must be 1 MB or smaller.")
    msgs = whatsapp.parse_chat(raw.decode("utf-8", errors="replace"))
    if not msgs:
        raise HTTPException(422, "This doesn't look like a WhatsApp chat export. In WhatsApp, open the group, "
                                 "tap More, then Export chat, and choose Without media.")
    now = time.time()
    for t in [t for t, v in _PREVIEWS.items() if now - v["at"] > PREVIEW_TTL_S]:
        _PREVIEWS.pop(t, None)
    token = secrets.token_urlsafe(16)
    _PREVIEWS[token] = {"uid": user["id"], "msgs": msgs, "at": now}
    return {"token": token, "participants": whatsapp.participants(msgs), "messages": len(msgs),
            "first_date": msgs[0].day.isoformat(), "last_date": msgs[-1].day.isoformat(),
            "flagged": sum(m.flagged for m in msgs)}


class ImportIn(BaseModel):
    token: str
    group_name: str = Field(min_length=2, max_length=80)
    me: str | None = None
    my_role: Literal["treasurer", "president"] = "treasurer"
    second_leader: str
    amount: str
    frequency: Literal["weekly", "monthly"] = "weekly"


@router.post("/import/whatsapp/create")
def import_create(body: ImportIn, user=Depends(viewer)):
    prev = _PREVIEWS.get(body.token)
    if not prev or prev["uid"] != user["id"] or time.time() - prev["at"] > PREVIEW_TTL_S:
        raise HTTPException(410, "This upload has expired. Please upload the chat again.")
    msgs: list[whatsapp.Message] = prev["msgs"]
    people = [p["name"] for p in whatsapp.participants(msgs)]
    if body.second_leader not in people or body.second_leader == body.me:
        raise HTTPException(422, f"Choose a {OTHER[body.my_role]} from the chat, other than you.")
    if body.me is not None and body.me not in people:
        raise HTTPException(422, "Choose your own name from the chat, or say you are not in it.")
    due_kobo = _kobo(body.amount, "contribution amount")
    extracted = whatsapp.extract_claims(msgs)  # AI (or rule-based fallback) - outside the transaction
    accepted, dropped = whatsapp.verify_claims(msgs, extracted["claims"], people)
    _PREVIEWS.pop(body.token, None)

    first, today = msgs[0].day, date.today()
    step = 7 if body.frequency == "weekly" else 30
    first_due = first + timedelta(days=step - 1)
    count = min(schedule.MAX_PERIODS, max(1, math.ceil((today - first_due).days / step) + 1) + (8 if step == 7 else 3))
    with db.tx() as conn:
        gid = _new_group(conn, body.group_name, user["id"], "whatsapp_import")
        db.append_event(conn, gid, "group_created", {"name": body.group_name.strip(), "from": "whatsapp",
                        "messages": len(msgs), "read_by": extracted["provider"]}, actor_id=user["id"])
        ids = {}
        for name in people:
            if name == body.me:
                ids[name] = user["id"]
                conn.execute("UPDATE users SET aliases=? WHERE id=?", (json.dumps([name]), user["id"]))
            else:
                ids[name] = _new_user(conn, name)
            role = body.my_role if name == body.me else OTHER[body.my_role] if name == body.second_leader else "member"
            _add_member(conn, gid, ids[name], role, user["id"])
        if body.me is None:
            _add_member(conn, gid, user["id"], body.my_role, user["id"])
        series = f"{body.frequency.title()} contribution"
        ob_ids = schedule.create_series(conn, gid, series, body.frequency, due_kobo, first_due, count)
        dues = [(oid, first_due + timedelta(days=step * k)) for k, oid in enumerate(ob_ids)] if step == 7 else \
               [(oid, date.fromisoformat(conn.execute("SELECT due_date FROM obligations WHERE id=?", (oid,)).fetchone()[0]))
                for oid in ob_ids]
        seen: dict[tuple, int] = {}
        stats = {"reported": 0, "needs_review": 0}
        for a in accepted:
            msg = a["message"]
            oid = next((o for o, d in dues if d >= msg.day), dues[-1][0])
            member_id = ids.get(a["payer"]) if a["payer"] else None
            reasons, status = [f"Claimed in the WhatsApp chat on {msg.day:%d %b %Y} - no receipt attached."], "reported"
            if member_id is None:
                status = "needs_review"
                reasons.insert(0, f"Could not match \"{a['claimed_name']}\" to a group member.")
            elif a["amount_kobo"] != due_kobo:
                reasons.append(f"Chat says {format_naira(a['amount_kobo'])} but the contribution is {format_naira(due_kobo)}.")
            key = (member_id, oid, a["amount_kobo"])
            if member_id and key in seen:
                status = "needs_review"
                reasons.insert(0, f"Looks like the same payment twice (messages #{seen[key]} and #{msg.id}).")
            seen.setdefault(key, msg.id)
            stats[status] += 1
            extraction = {"ok": True, "provider": extracted["provider"], "ms": extracted["ms"],
                          "extraction": {"message_id": msg.id, "amount_text": a["amount_text"],
                                         "claimed_name": a["claimed_name"], "note": a["note"]}}
            eid = conn.execute(
                "INSERT INTO entries(group_id,direction,obligation_id,member_id,claimed_name,amount_kobo,occurred_on,"
                "source,status,reasons,extraction,source_text,created_by,created_at) "
                "VALUES (?, 'in', ?,?,?,?,?, 'whatsapp_import', ?,?,?,?,?,?)",
                (gid, oid, member_id, a["claimed_name"], a["amount_kobo"], msg.day.isoformat(), status,
                 json.dumps(reasons), json.dumps(extraction), msg.text[:500], user["id"], db.now_iso())).lastrowid
            db.append_event(conn, gid, "entry_imported", {"message_id": msg.id, "amount_kobo": a["amount_kobo"],
                            "member_id": member_id, "status": status}, entry_id=eid, actor_id=user["id"])
    return {"group_id": gid, "messages": len(msgs), "participants": len(people), "payments_found": len(accepted),
            **stats, "flagged": [m.text[:160] for m in msgs if m.flagged], "dropped": dropped,
            "read_by": extracted["provider"], "ai_error": extracted["ai_error"]}
