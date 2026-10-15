"""Statement check: leaders upload a bank or mobile-money statement and see where it disagrees with the ledger."""
import hashlib
import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from . import db, llm, statement
from .deps import require_approver, viewer
from .money import format_naira

router = APIRouter(prefix="/api/groups/{group_id}")
MAX_STATEMENT_BYTES = 1024 * 1024


def _people(conn, group_id: int) -> dict[int, dict]:
    rows = conn.execute("SELECT u.id, u.name, u.aliases FROM memberships m JOIN users u ON u.id=m.user_id "
                        "WHERE m.group_id=?", (group_id,))
    return {r["id"]: {"name": r["name"], "aliases": json.loads(r["aliases"] or "[]")} for r in rows}


def _ledger(conn, group_id: int) -> tuple[list[dict], dict[int, str]]:
    entries = [dict(r) for r in conn.execute("SELECT * FROM entries WHERE group_id=?", (group_id,))]
    titles = {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM obligations WHERE group_id=?", (group_id,))}
    return entries, titles


def _sample(conn, group_id: int) -> str:
    entries, _ = _ledger(conn, group_id)
    people = _people(conn, group_id)
    name = conn.execute("SELECT name FROM groups WHERE id=?", (group_id,)).fetchone()["name"]
    who = lambda e: people.get(e["member_id"], {}).get("name") or e["claimed_name"] or "Unknown"
    return statement.sample_csv(entries, who, name, date.today())


@router.get("/statement/sample", response_class=PlainTextResponse)
def sample_statement(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        csv_text = _sample(conn, group_id)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="sample-statement.csv"'})


@router.post("/statement/check")
def check_statement(group_id: int, statement_file: UploadFile | None = File(None), sample: bool = Form(False),
                    user=Depends(viewer)):
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        if sample:
            raw, source = _sample(conn, group_id), "Sample statement made from this ledger (3 planted problems)"
        elif statement_file is not None:
            data = statement_file.file.read(MAX_STATEMENT_BYTES + 1)
            if len(data) > MAX_STATEMENT_BYTES:
                raise HTTPException(413, "The statement must be 1 MB or smaller.")
            if b"\x00" in data[:4096]:
                raise HTTPException(422, "Upload the statement as a CSV or text file (export it from your bank app, "
                                         "or copy the lines into a .txt file).")
            raw, source = data.decode("utf-8", errors="replace"), (statement_file.filename or "statement")[:80]
        else:
            raise HTTPException(422, "Choose a statement file, or try the sample statement.")
        people = _people(conn, group_id)
        entries, titles = _ledger(conn, group_id)

    lines = statement.split_lines(raw)
    if not lines:
        raise HTTPException(422, "The statement file is empty.")
    ai_error, reader = None, None
    try:  # outside the transaction: the AI can take a while
        read = statement.read_with_ai(lines)
        txns, dropped = statement.verify_txns(lines, read["txns"])
        reader = read["provider"]
    except llm.LLMError as e:
        ai_error, txns, dropped = str(e)[:200], [], []
    if not txns:
        txns, dropped2 = statement.verify_txns(lines, statement.read_with_rules(lines))
        if txns:
            reader, dropped = "Rule-based CSV reader (AI unavailable)" if ai_error else "Rule-based CSV reader", dropped + dropped2
    if not txns:
        raise HTTPException(422, "No transactions could be read from this statement. Export it as CSV from your bank "
                                 "or mobile-money app, or copy the transaction lines into a .txt file.")

    def names_for(e):
        if e["direction"] == "out":
            return [e["counterparty"] or ""]
        p = people.get(e["member_id"], {})
        return [n for n in [p.get("name"), *p.get("aliases", []), e["claimed_name"]] if n]

    def describe(e):
        who = people.get(e["member_id"], {}).get("name") or e["claimed_name"] or e["counterparty"] or "someone"
        what = titles.get(e["obligation_id"], e["description"] or "")
        verb = "payment" if e["direction"] == "in" else "payout to"
        lead = f"{who}'s {format_naira(e['amount_kobo'])} {verb}" if e["direction"] == "in" else \
               f"the {format_naira(e['amount_kobo'])} {verb} {who}"
        return f"{lead} on {date.fromisoformat(e['occurred_on']):%d %b %Y}" + (f" ({what})" if what else "")

    result = statement.match(txns, entries, names_for)
    problems = []
    for it in result["items"]:
        it["id"] = it["txn"]["id"] if it["txn"] else f"E{it['entry']['id']}"
        it["reason"] = statement.reason(it, describe)
        if it["kind"] != "match":
            problems.append({"id": it["id"], "summary": it["reason"] +
                             (f" Statement line: \"{it['txn']['text']}\"" if it["txn"] else "")})
    explained = statement.explain(problems, [p["name"] for p in people.values()])

    items = []
    for it in result["items"]:
        t, e = it["txn"], it["entry"]
        items.append({
            "id": it["id"], "kind": it["kind"], "reason": it["reason"], "note": explained["notes"].get(it["id"]),
            "txn": t and {"line": t["line"], "date": t["date"].isoformat(), "amount_kobo": t["amount_kobo"],
                          "direction": t["direction"], "counterparty": t["counterparty"], "text": t["text"]},
            "entry": e and {"id": e["id"], "status": e["status"], "amount_kobo": e["amount_kobo"],
                            "occurred_on": e["occurred_on"], "direction": e["direction"], "member_id": e["member_id"],
                            "title": titles.get(e["obligation_id"]), "description": describe(e)},
        })
    order = {"amount_differs": 0, "not_in_ledger": 1, "not_on_statement": 2, "name_differs": 3, "match": 4}
    items.sort(key=lambda i: (order[i["kind"]], (i["txn"] or {}).get("date") or (i["entry"] or {}).get("occurred_on")))
    sha = hashlib.sha256(raw.encode()).hexdigest()
    report = {"source": source, "period": result["period"], "counts": result["counts"], "items": items,
              "lines": len(lines), "transactions": len(txns), "dropped": dropped[:20],
              "read_by": reader, "explained_by": explained["provider"], "ai_error": ai_error or explained["error"],
              "checked_at": db.now_iso(), "checked_by": user["name"]}
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        report["id"] = conn.execute(
            "INSERT INTO statement_checks(group_id, created_by, created_at, file_sha256, report) VALUES (?,?,?,?,?)",
            (group_id, user["id"], report["checked_at"], sha, json.dumps(report))).lastrowid
        db.append_event(conn, group_id, "statement_checked",
                        {"file_sha256": sha, "period": result["period"], "transactions": len(txns),
                         **result["counts"], "read_by": reader}, actor_id=user["id"])
    return report


@router.get("/statement/latest")
def latest_statement(group_id: int, user=Depends(viewer)):
    with db.tx() as conn:
        require_approver(conn, group_id, user["id"])
        row = conn.execute("SELECT report FROM statement_checks WHERE group_id=? ORDER BY id DESC LIMIT 1",
                           (group_id,)).fetchone()
    return json.loads(row["report"]) if row else None
