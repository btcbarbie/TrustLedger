import hashlib
import io
import json
import uuid
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import ask, config, db, proof, rules
from .deps import membership, viewer
from .groups_api import router as groups_router
from .money import format_naira, parse_naira

app = FastAPI(title="TrustLedger")
app.include_router(groups_router)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET, same_site="lax",
                   https_only=config.SECURE_COOKIES, max_age=60 * 60 * 12)

@app.middleware("http")
async def no_stale_frontend(request: Request, call_next):
    # The demo changes often; never let a browser mix an old page with new scripts.
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


PIL_TO_MIME = {"PNG": ("image/png", ".png"), "JPEG": ("image/jpeg", ".jpg"), "WEBP": ("image/webp", ".webp")}


@app.on_event("startup")
def _startup():
    db.init_db()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ---------- identity & access: see deps.py ----------

def _names(conn) -> dict[int, str]:
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users")}


def _entries(conn, group_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM entries WHERE group_id=? ORDER BY occurred_on DESC, id DESC",
                                          (group_id,))]


def _obligations(conn, group_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM obligations WHERE group_id=? ORDER BY due_date",
                                          (group_id,))]


def _member_count(conn, group_id: int) -> int:
    return conn.execute("SELECT COUNT(*) c FROM memberships WHERE group_id=?", (group_id,)).fetchone()["c"]


# ---------- session ----------

@app.get("/api/people")
def people():
    """Demo-only list for the 'Viewing as' switcher: one row per person."""
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT u.id, u.name, m.role, g.name AS group_name, g.id AS group_id FROM users u "
            "LEFT JOIN memberships m ON m.user_id=u.id LEFT JOIN groups g ON g.id=m.group_id ORDER BY u.id, g.id").fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        p = out.setdefault(r["id"], {"id": r["id"], "name": r["name"], "role": r["role"] or "member",
                                     "group_name": r["group_name"] or "No group yet", "groups": 0, "leader": False,
                                     "memberships": []})
        if r["group_id"]:
            p["groups"] += 1
            p["leader"] = p["leader"] or r["role"] in ("president", "treasurer")
            p["memberships"].append({"group_id": r["group_id"], "group_name": r["group_name"], "role": r["role"]})
    return list(out.values())


class ViewAs(BaseModel):
    user_id: int


@app.post("/api/view-as")
def view_as(body: ViewAs, request: Request):
    with db.tx() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (body.user_id,)).fetchone():
            raise HTTPException(404, "Unknown person.")
    request.session["uid"] = body.user_id
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(viewer)):
    with db.tx() as conn:
        groups = conn.execute("SELECT g.id, g.name, m.role FROM groups g JOIN memberships m ON m.group_id=g.id "
                              "WHERE m.user_id=? ORDER BY g.id", (user["id"],)).fetchall()
    return {"user": user, "groups": [dict(g) for g in groups]}


# ---------- group overview ----------

@app.get("/api/groups/{group_id}")
def group_overview(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        me_role = membership(conn, group_id, user["id"])["role"]
        group = dict(conn.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone())
        members = [dict(r) for r in conn.execute(
            "SELECT u.id, u.name, m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.group_id=? "
            "ORDER BY CASE m.role WHEN 'president' THEN 0 WHEN 'treasurer' THEN 1 ELSE 2 END, u.name",
            (group_id,))]
        obligations, entries = _obligations(conn, group_id), _entries(conn, group_id)
        n = len(members)
    for ob in obligations:
        ob["summary"] = rules.obligation_summary(ob, n, entries)
    totals = {
        "in_kobo": sum(e["amount_kobo"] for e in entries if e["direction"] == "in" and e["status"] == "verified"),
        "out_kobo": sum(e["amount_kobo"] for e in entries if e["direction"] == "out" and e["status"] == "verified"),
        "needs_review": sum(1 for e in entries if e["status"] == "needs_review"),
        "awaiting": sum(1 for e in entries if e["status"] in ("reported", "documented", "needs_review", "requested", "approved")),
    }
    totals["balance_kobo"] = totals["in_kobo"] - totals["out_kobo"]
    group.pop("invite_code", None)
    return {"group": group, "my_role": me_role, "members": members, "obligations": obligations,
            "totals": totals, "today": date.today().isoformat(),
            "ai": {"primary": config.PRIMARY["label"], "model": config.PRIMARY["model"],
                   "fallback": config.FALLBACK["label"] if config.FALLBACK else None}}


@app.get("/api/groups/{group_id}/entries")
def list_entries(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        role = membership(conn, group_id, user["id"])["role"]
        names, entries = _names(conn), _entries(conn, group_id)
        titles = {o["id"]: o["title"] for o in _obligations(conn, group_id)}
    out = []
    for e in entries:
        ok, why = rules.can_decide(actor_id=user["id"], actor_role=role, entry=e)
        ok_ap, why_ap = rules.can_approve_payout(actor_id=user["id"], actor_role=role, entry=e)
        ok_rc, why_rc = rules.can_add_receipt(actor_role=role, entry=e)
        extraction = json.loads(e["extraction"]) if e["extraction"] else None
        out.append({
            "id": e["id"], "direction": e["direction"], "status": e["status"],
            "reasons": json.loads(e["reasons"]), "amount_kobo": e["amount_kobo"],
            "amount": format_naira(e["amount_kobo"]), "occurred_on": e["occurred_on"],
            "obligation": titles.get(e["obligation_id"]), "obligation_id": e["obligation_id"],
            "member": names.get(e["member_id"]) or e["claimed_name"], "member_id": e["member_id"],
            "matched": e["member_id"] is not None or e["direction"] == "out", "source_text": e["source_text"],
            "counterparty": e["counterparty"], "description": e["description"], "source": e["source"],
            "has_proof": bool(e["proof_path"]), "created_by": names.get(e["created_by"]),
            "decided_by": names.get(e["decided_by"]), "decided_at": e["decided_at"],
            "decision_note": e["decision_note"],
            "read_by": (extraction or {}).get("provider"), "read_ms": (extraction or {}).get("ms"),
            "extracted": (extraction or {}).get("extraction"),
            "can_decide": ok, "cannot_decide_reason": why,
            "can_approve": ok_ap, "cannot_approve_reason": why_ap, "can_add_receipt": ok_rc,
            "approved_by": names.get(e["approved_by"]), "approval_note": e["approval_note"],
            "receipt_by": names.get(e["receipt_by"]),
        })
    return out


# ---------- recording money in / out ----------

def _load_proof(upload: UploadFile | None) -> tuple[bytes, str, str] | None:
    if upload is None or not upload.filename:
        return None
    data = upload.file.read(config.MAX_PROOF_BYTES + 1)
    if len(data) > config.MAX_PROOF_BYTES:
        raise HTTPException(413, "Proof image must be 5 MB or smaller.")
    try:  # trust the bytes, not the filename or content-type header
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "Proof must be a PNG, JPEG or WEBP image.")
    if fmt not in PIL_TO_MIME:
        raise HTTPException(415, "Proof must be a PNG, JPEG or WEBP image.")
    mime, ext = PIL_TO_MIME[fmt]
    return data, mime, ext


def _parse_amount(text: str) -> int:
    kobo = parse_naira(text)
    if kobo is None:
        raise HTTPException(422, "Enter a valid amount, for example 5000 or 5,000.")
    return kobo


def _parse_date(text: str) -> date:
    try:
        d = date.fromisoformat(text)
    except ValueError:
        raise HTTPException(422, "Enter a valid date.")
    if d > date.today():
        raise HTTPException(422, "The date cannot be in the future.")
    return d


def _record(conn, *, group_id, user, direction, obligation_id, amount_kobo, occurred_on,
            expected_names, proof_file, member_id=None, counterparty=None, description=None):
    ob = conn.execute("SELECT id FROM obligations WHERE id=? AND group_id=?", (obligation_id, group_id)).fetchone()
    if not ob:
        raise HTTPException(422, "Choose an obligation from this group.")
    loaded = _load_proof(proof_file)
    read = dup_hash = dup_ref = sha = path = ref = None
    if loaded:
        data, mime, ext = loaded
        sha = hashlib.sha256(data).hexdigest()
        prev = conn.execute("SELECT id FROM entries WHERE group_id=? AND proof_sha256=? ORDER BY id LIMIT 1",
                            (group_id, sha)).fetchone()
        dup_hash = prev["id"] if prev else None
        name = f"{uuid.uuid4().hex}{ext}"
        (config.UPLOAD_DIR / name).write_bytes(data)
        path = f"uploads/{name}"
        read = proof.read_receipt(data, mime)
        if read["ok"] and read["extraction"].get("reference"):
            ref = read["extraction"]["reference"].strip()
            prev = conn.execute("SELECT id FROM entries WHERE group_id=? AND proof_reference=? ORDER BY id LIMIT 1",
                                (group_id, ref)).fetchone()
            dup_ref = prev["id"] if prev else None
    status, reasons = rules.assess_proof(direction=direction, amount_kobo=amount_kobo, occurred_on=occurred_on,
                                         expected_names=expected_names, read=read,
                                         duplicate_of_hash=dup_hash, duplicate_of_reference=dup_ref)
    cur = conn.execute(
        "INSERT INTO entries(group_id,direction,obligation_id,member_id,counterparty,description,amount_kobo,"
        "occurred_on,source,status,reasons,proof_path,proof_sha256,proof_reference,extraction,created_by,created_at)"
        " VALUES (?,?,?,?,?,?,?,?, 'app',?,?,?,?,?,?,?,?)",
        (group_id, direction, obligation_id, member_id, counterparty, description, amount_kobo,
         occurred_on.isoformat(), status, json.dumps(reasons), path, sha, ref,
         json.dumps(read) if read else None, user["id"], db.now_iso()))
    entry_id = cur.lastrowid
    db.append_event(conn, group_id, "entry_recorded",
                    {"direction": direction, "amount_kobo": amount_kobo, "obligation_id": obligation_id,
                     "member_id": member_id, "counterparty": counterparty, "status": status,
                     "proof_sha256": sha, "read_by": read.get("provider") if read else None},
                    entry_id=entry_id, actor_id=user["id"])
    return {"id": entry_id, "status": status, "reasons": reasons,
            "read_by": read.get("provider") if read else None,
            "extracted": read.get("extraction") if read else None}


@app.post("/api/groups/{group_id}/entries/in")
def record_payment(group_id: int, obligation_id: int = Form(...), amount: str = Form(...),
                   occurred_on: str = Form(...), proof_file: UploadFile | None = File(None),
                   user=Depends(viewer)):
    """A member records their OWN payment. member_id comes from the session, never the form."""
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        aliases = json.loads(conn.execute("SELECT aliases FROM users WHERE id=?", (user["id"],)).fetchone()["aliases"])
        return _record(conn, group_id=group_id, user=user, direction="in", obligation_id=obligation_id,
                       amount_kobo=_parse_amount(amount), occurred_on=_parse_date(occurred_on),
                       expected_names=[user["name"], *aliases], proof_file=proof_file, member_id=user["id"])


class PayoutRequest(BaseModel):
    obligation_id: int
    amount: str
    counterparty: str
    description: str = ""


@app.post("/api/groups/{group_id}/payouts")
def request_payout(group_id: int, body: PayoutRequest, user=Depends(viewer)):
    """Step 1: a leader asks to pay money out. Nothing is counted yet."""
    counterparty, description = body.counterparty.strip()[:120], body.description.strip()[:300]
    if not counterparty:
        raise HTTPException(422, "Enter who will be paid.")
    amount_kobo = _parse_amount(body.amount)
    with db.tx() as conn:
        if membership(conn, group_id, user["id"])["role"] != "treasurer":
            raise HTTPException(403, "Only the treasurer can request a payout. The president approves it.")
        ob = conn.execute("SELECT * FROM obligations WHERE id=? AND group_id=?", (body.obligation_id, group_id)).fetchone()
        if not ob:
            raise HTTPException(422, "Choose an obligation from this group.")
        entries = _entries(conn, group_id)
        s = rules.obligation_summary(dict(ob), _member_count(conn, group_id), entries)
        available = s["balance_kobo"] - s["spent_pending_kobo"]
        if amount_kobo > available:
            raise HTTPException(422, f"This pot only has {format_naira(max(available, 0))} available after other pending payouts.")
        eid = conn.execute(
            "INSERT INTO entries(group_id,direction,obligation_id,counterparty,description,amount_kobo,occurred_on,source,"
            "status,reasons,created_by,created_at) VALUES (?, 'out', ?,?,?,?,?, 'app', 'requested', ?,?,?)",
            (group_id, body.obligation_id, counterparty, description or None, amount_kobo, date.today().isoformat(),
             json.dumps([f"Requested {format_naira(amount_kobo)} for {counterparty}. Another leader must approve it."]),
             user["id"], db.now_iso())).lastrowid
        db.append_event(conn, group_id, "payout_requested", {"amount_kobo": amount_kobo, "counterparty": counterparty,
                        "obligation_id": body.obligation_id}, entry_id=eid, actor_id=user["id"])
    return {"id": eid, "status": "requested"}


class Approval(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/groups/{group_id}/payouts/{entry_id}/approve")
def approve_payout(group_id: int, entry_id: int, body: Approval, user=Depends(viewer)):
    """Step 2: a different leader approves or declines before any money moves."""
    if body.decision not in ("approve", "decline"):
        raise HTTPException(422, "Decision must be approve or decline.")
    note = body.note.strip()[:300]
    with db.tx() as conn:
        role = membership(conn, group_id, user["id"])["role"]
        row = conn.execute("SELECT * FROM entries WHERE id=? AND group_id=? AND direction='out'", (entry_id, group_id)).fetchone()
        if not row:
            raise HTTPException(404, "Payout not found.")
        ok, why = rules.can_approve_payout(actor_id=user["id"], actor_role=role, entry=dict(row))
        if not ok:
            raise HTTPException(403, why)
        if body.decision == "decline" and not note:
            raise HTTPException(422, "Add a short note explaining why it is declined.")
        new = "approved" if body.decision == "approve" else "declined"
        reason = (f"Approved {format_naira(row['amount_kobo'])} for {row['counterparty']}. Pay it, then upload the receipt."
                  if new == "approved" else f"Declined: {note}")
        conn.execute("UPDATE entries SET status=?, approved_by=?, approved_at=?, approval_note=?, reasons=? WHERE id=?",
                     (new, user["id"], db.now_iso(), note or None, json.dumps([reason]), entry_id))
        db.append_event(conn, group_id, f"payout_{new}", {"note": note or None}, entry_id=entry_id, actor_id=user["id"])
    return {"id": entry_id, "status": new}


@app.post("/api/groups/{group_id}/payouts/{entry_id}/receipt")
def payout_receipt(group_id: int, entry_id: int, occurred_on: str = Form(...),
                   proof_file: UploadFile = File(...), user=Depends(viewer)):
    """Step 3: after paying, upload the receipt. AI reads it; rules compare it with what was APPROVED."""
    paid_on = _parse_date(occurred_on)
    with db.tx() as conn:
        role = membership(conn, group_id, user["id"])["role"]
        row = conn.execute("SELECT * FROM entries WHERE id=? AND group_id=? AND direction='out'", (entry_id, group_id)).fetchone()
        if not row:
            raise HTTPException(404, "Payout not found.")
        entry = dict(row)
        ok, why = rules.can_add_receipt(actor_role=role, entry=entry)
        if not ok:
            raise HTTPException(403, why)
        loaded = _load_proof(proof_file)
        if not loaded:
            raise HTTPException(422, "Attach the receipt for this payment.")
        data, mime, ext = loaded
        sha = hashlib.sha256(data).hexdigest()
        prev = conn.execute("SELECT id FROM entries WHERE group_id=? AND proof_sha256=? ORDER BY id LIMIT 1", (group_id, sha)).fetchone()
        name = f"{uuid.uuid4().hex}{ext}"
        (config.UPLOAD_DIR / name).write_bytes(data)
        read = proof.read_receipt(data, mime)
        ref = dup_ref = None
        if read["ok"] and read["extraction"].get("reference"):
            ref = read["extraction"]["reference"].strip()
            p2 = conn.execute("SELECT id FROM entries WHERE group_id=? AND proof_reference=? ORDER BY id LIMIT 1", (group_id, ref)).fetchone()
            dup_ref = p2["id"] if p2 else None
        status, reasons = rules.assess_proof(direction="out", amount_kobo=entry["amount_kobo"], occurred_on=paid_on,
                                             expected_names=[entry["counterparty"]], read=read,
                                             duplicate_of_hash=prev["id"] if prev else None, duplicate_of_reference=dup_ref)
        reasons = [r.replace("was entered", "was approved") for r in reasons]
        conn.execute("UPDATE entries SET status=?, reasons=?, proof_path=?, proof_sha256=?, proof_reference=?, extraction=?, "
                     "occurred_on=?, receipt_by=? WHERE id=?",
                     (status, json.dumps(reasons), f"uploads/{name}", sha, ref, json.dumps(read), paid_on.isoformat(),
                      user["id"], entry_id))
        db.append_event(conn, group_id, "payout_receipt", {"status": status, "proof_sha256": sha,
                        "read_by": read.get("provider")}, entry_id=entry_id, actor_id=user["id"])
    return {"id": entry_id, "status": status, "reasons": reasons, "read_by": read.get("provider"),
            "extracted": read.get("extraction")}


class Decision(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/groups/{group_id}/entries/{entry_id}/decide")
def decide(group_id: int, entry_id: int, body: Decision, user=Depends(viewer)):
    if body.decision not in ("verify", "reject"):
        raise HTTPException(422, "Decision must be verify or reject.")
    note = body.note.strip()[:300]
    with db.tx() as conn:
        role = membership(conn, group_id, user["id"])["role"]
        row = conn.execute("SELECT * FROM entries WHERE id=? AND group_id=?", (entry_id, group_id)).fetchone()
        if not row:  # scoped by group: an entry id from another group is simply not found
            raise HTTPException(404, "Entry not found.")
        entry = dict(row)
        ok, why = rules.can_decide(actor_id=user["id"], actor_role=role, entry=entry)
        if not ok:
            raise HTTPException(403, why)
        if body.decision == "reject" and not note:
            raise HTTPException(422, "Add a short note explaining the rejection.")
        new_status = "verified" if body.decision == "verify" else "rejected"
        conn.execute("UPDATE entries SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                     (new_status, user["id"], db.now_iso(), note or None, entry_id))
        db.append_event(conn, group_id, "entry_decided",
                        {"decision": new_status, "previous_status": entry["status"], "note": note or None},
                        entry_id=entry_id, actor_id=user["id"])
    return {"id": entry_id, "status": new_status}


@app.get("/api/groups/{group_id}/entries/{entry_id}/proof")
def get_proof(group_id: int, entry_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        row = conn.execute("SELECT proof_path FROM entries WHERE id=? AND group_id=?", (entry_id, group_id)).fetchone()
    if not row or not row["proof_path"]:
        raise HTTPException(404, "No proof for this entry.")
    base = config.DATA_DIR
    path = (base / row["proof_path"]).resolve()
    if base.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "No proof for this entry.")
    return FileResponse(path)


# ---------- records & history ----------

@app.get("/api/groups/{group_id}/members/{member_id}/record")
def record(group_id: int, member_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        m = conn.execute("SELECT u.id, u.name, m.role FROM memberships m JOIN users u ON u.id=m.user_id "
                         "WHERE m.group_id=? AND m.user_id=?", (group_id, member_id)).fetchone()
        if not m:
            raise HTTPException(404, "Member not found.")
        obligations, entries = _obligations(conn, group_id), _entries(conn, group_id)
    return {"member": dict(m), **rules.member_record(member_id, obligations, entries, date.today())}


@app.get("/api/groups/{group_id}/events")
def events(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        names = _names(conn)
        rows = conn.execute("SELECT * FROM ledger_events WHERE group_id=? ORDER BY id DESC LIMIT 200",
                            (group_id,)).fetchall()
    return [{"id": r["id"], "entry_id": r["entry_id"], "actor": names.get(r["actor_id"]), "action": r["action"],
             "detail": json.loads(r["detail"]), "created_at": r["created_at"], "hash": r["hash"][:12]} for r in rows]


@app.get("/api/groups/{group_id}/verify")
def verify(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        return db.verify_chain(conn, group_id)


class Question(BaseModel):
    question: str


@app.post("/api/groups/{group_id}/ask")
def ask_ledger(group_id: int, body: Question, user=Depends(viewer)):
    """The group comes from the URL and is checked against the viewer's membership - never from the question."""
    q = body.question.strip()[:500]
    if len(q) < 3:
        raise HTTPException(422, "Type a question, for example: How much has Amina paid?")
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        members = {r["id"]: r["name"] for r in conn.execute(
            "SELECT u.id, u.name FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.group_id=?", (group_id,))}
        obligations, entries = _obligations(conn, group_id), _entries(conn, group_id)
    query, reader = ask.interpret(q, date.today(), members=list(members.values()),
                                  obligations=[o["title"] for o in obligations])
    result = ask.run(query, asker=user, members=members, obligations=obligations, entries=entries, today=date.today())
    return {**result, "understood_as": query.model_dump(), "read_by": reader}


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(Path(config.ROOT) / "web"), html=True), name="web")
