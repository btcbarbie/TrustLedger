"""Share a lender-ready payment record (by the member only), and search for financing (leaders)."""
import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from . import db, lender, tavily
from .deps import membership, require_approver, viewer

router = APIRouter(prefix="/api")
SHARE_DAYS = 30


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------- lender-ready record ----------

@router.post("/groups/{group_id}/members/{member_id}/share")
def share_record(group_id: int, member_id: int, user=Depends(viewer)):
    if user["id"] != member_id:  # consent: only the member can share their own record
        raise HTTPException(403, "Only the member can share their own payment record.")
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        facts = lender.member_facts(conn, group_id, member_id, date.today())
    summary, written_by = lender.write_summary(facts)  # outside the transaction: the AI can take a while
    token = secrets.token_urlsafe(18)
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=SHARE_DAYS)).isoformat(timespec="seconds")
    snapshot = {"facts": facts, "summary": summary, "written_by": written_by, "facts_sha256": _sha(facts)}
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        conn.execute("INSERT INTO shares(token, group_id, member_id, created_at, expires_at, snapshot) VALUES (?,?,?,?,?,?)",
                     (token, group_id, member_id, now.isoformat(timespec="seconds"), expires, json.dumps(snapshot)))
        db.append_event(conn, group_id, "record_shared", {"member_id": member_id, "facts_sha256": snapshot["facts_sha256"],
                        "expires_at": expires}, actor_id=user["id"])
    return {"token": token, "url": f"/record.html?t={token}", "expires_at": expires, "summary": summary,
            "written_by": written_by}


@router.get("/groups/{group_id}/members/{member_id}/shares")
def list_shares(group_id: int, member_id: int, user=Depends(viewer)):
    if user["id"] != member_id:
        return []
    with db.tx() as conn:
        membership(conn, group_id, user["id"])
        rows = conn.execute("SELECT token, created_at, expires_at FROM shares WHERE group_id=? AND member_id=? "
                            "AND revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
                            (group_id, member_id, db.now_iso())).fetchall()
    return [{"token": r["token"], "url": f"/record.html?t={r['token']}", "created_at": r["created_at"],
             "expires_at": r["expires_at"]} for r in rows]


@router.post("/shares/{token}/revoke")
def revoke_share(token: str, user=Depends(viewer)):
    with db.tx() as conn:
        row = conn.execute("SELECT group_id, member_id FROM shares WHERE token=? AND revoked_at IS NULL", (token,)).fetchone()
        if not row or row["member_id"] != user["id"]:
            raise HTTPException(404, "Share link not found.")
        conn.execute("UPDATE shares SET revoked_at=? WHERE token=?", (db.now_iso(), token))
        db.append_event(conn, row["group_id"], "record_share_revoked", {"member_id": user["id"]}, actor_id=user["id"])
    return {"ok": True}


@router.get("/shared/{token}")
def shared_record(token: str):
    """Public on purpose: this is the link the member chose to give a lender. Expired or revoked links return 404."""
    with db.tx() as conn:
        row = conn.execute("SELECT * FROM shares WHERE token=?", (token,)).fetchone()
        if not row or row["revoked_at"] or row["expires_at"] <= db.now_iso():
            raise HTTPException(404, "This record link has expired or was withdrawn by the member.")
        snap = json.loads(row["snapshot"])
        sealed = conn.execute("SELECT hash, created_at FROM ledger_events WHERE group_id=? AND action='record_shared' "
                              "AND detail LIKE ? ORDER BY id DESC LIMIT 1",
                              (row["group_id"], f'%{snap["facts_sha256"]}%')).fetchone()
        intact = db.verify_chain(conn, row["group_id"])["intact"]
    return {**snap, "created_at": row["created_at"], "expires_at": row["expires_at"],
            "seal": sealed["hash"][:16] if sealed else None, "ledger_intact_now": intact,
            "facts_match_seal": _sha(snap["facts"]) == snap["facts_sha256"]}


# ---------- financing search ----------

@router.post("/groups/{group_id}/financing")
def find_financing(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        facts = lender.group_facts(conn, group_id, date.today())
    results, seen, search_error = [], set(), None
    for q in lender.queries(facts):
        try:
            for r in tavily.search(q):
                if r["url"] not in seen:
                    seen.add(r["url"]); results.append(r)
        except tavily.SearchError as e:
            search_error = str(e)
            break
    if not results:
        raise HTTPException(503, search_error or "The web search found nothing. Try again later.")
    ranked = lender.rank_options(facts, results)
    report = {"facts": facts, "queries": lender.queries(facts), "options": ranked["options"],
              "sources": [{"title": r["title"], "url": r["url"]} for r in results],
              "searched_by": "Tavily", "written_by": ranked["written_by"], "ai_error": ranked["error"],
              "created_at": db.now_iso(), "created_by": user["name"]}
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        conn.execute("INSERT INTO financing_searches(group_id, created_by, created_at, report) VALUES (?,?,?,?)",
                     (group_id, user["id"], report["created_at"], json.dumps(report)))
        db.append_event(conn, group_id, "financing_searched", {"sources": len(results), "options": len(ranked["options"])},
                        actor_id=user["id"])
    return report


@router.get("/groups/{group_id}/financing/latest")
def latest_financing(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        row = conn.execute("SELECT report FROM financing_searches WHERE group_id=? ORDER BY id DESC LIMIT 1",
                           (group_id,)).fetchone()
    return json.loads(row["report"]) if row else None
