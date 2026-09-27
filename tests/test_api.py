import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, db, proof


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "SEED_PROOF_DIR", tmp_path / "seed_proofs")
    from scripts import seed
    seed.main()
    with db.tx() as conn:  # a second, unrelated group for cross-group checks
        outsider = conn.execute("INSERT INTO users(name) VALUES ('Outsider Olu')").lastrowid
        g2 = conn.execute("INSERT INTO groups(name, invite_code, created_at) VALUES ('Other Group', 'other-code', '2026-01-01')").lastrowid
        conn.execute("INSERT INTO memberships VALUES (?,?, 'treasurer')", (g2, outsider))
        ob2 = conn.execute("INSERT INTO obligations(group_id,title,category,amount_due_kobo,due_date) "
                           "VALUES (?, 'X', 'weekly', 100, '2026-09-01')", (g2,)).lastrowid
        conn.execute("INSERT INTO entries(group_id,direction,obligation_id,member_id,amount_kobo,occurred_on,source,"
                     "status,created_by,created_at) VALUES (?, 'in', ?, ?, 100, '2026-09-01', 'app', 'documented', ?, "
                     "'2026-09-01')", (g2, ob2, outsider, outsider))
    from app.main import app
    with TestClient(app) as c:
        c.ids = {r["name"]: r["id"] for r in c.get("/api/people").json()}
        c.ids["Outsider Olu"] = outsider
        yield c


def as_(c, name):
    assert c.post("/api/view-as", json={"user_id": c.ids[name]}).status_code == 200


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(b, "PNG")
    return b.getvalue()


def fake_read(amount, sender="AMINA BELLO", recipient="IRETI WOMEN'S COOPERATIVE"):
    from datetime import date
    return lambda data, mime: {"ok": True, "provider": "mock", "model": "m", "ms": 1, "error": None,
                               "extraction": {"is_transfer_receipt": True, "amount_text": amount,
                                              "date_text": f"{date.today():%d %b %Y}", "sender_name": sender,
                                              "recipient_name": recipient, "reference": None, "confidence": 0.9}}


def ob_id(c, word):
    return next(o["id"] for o in c.get("/api/groups/1").json()["obligations"] if word in o["title"])


def today():
    from datetime import date
    return date.today().isoformat()


def test_requires_viewer(client):
    assert client.get("/api/groups/1").status_code == 401


def test_other_groups_are_invisible(client):
    as_(client, "Amina Bello")
    assert client.get("/api/groups/1").status_code == 200
    assert client.get("/api/groups/2").status_code == 404
    assert client.get("/api/groups/2/entries").status_code == 404
    as_(client, "Outsider Olu")
    assert client.get("/api/groups/1/entries").status_code == 404
    assert client.get("/api/groups/1/entries/1/proof").status_code == 404


def test_member_payment_flow_and_no_self_approval(client, monkeypatch):
    monkeypatch.setattr(proof, "read_receipt", fake_read("₦45,000.00"))
    as_(client, "Amina Bello")
    r = client.post("/api/groups/1/entries/in",
                    data={"obligation_id": ob_id(client, "Inventory"), "amount": "50,000", "occurred_on": today(),
                          "member_id": client.ids["Ngozi Eze"]},  # spoof attempt: must be ignored
                    files={"proof_file": ("r.png", png(), "image/png")}).json()
    assert r["status"] == "needs_review" and "₦45,000" in r["reasons"][0]
    entry = next(e for e in client.get("/api/groups/1/entries").json() if e["id"] == r["id"])
    assert entry["member"] == "Amina Bello"
    assert client.post(f"/api/groups/1/entries/{r['id']}/decide", json={"decision": "verify"}).status_code == 403
    as_(client, "Ngozi Eze")
    assert client.post(f"/api/groups/1/entries/{r['id']}/decide",
                       json={"decision": "reject"}).status_code == 422  # rejection needs a note
    ok = client.post(f"/api/groups/1/entries/{r['id']}/decide", json={"decision": "verify", "note": "Checked"})
    assert ok.json()["status"] == "verified"
    assert client.post(f"/api/groups/1/entries/{r['id']}/decide", json={"decision": "verify"}).status_code == 403


def test_payout_needs_second_person(client, monkeypatch):
    monkeypatch.setattr(proof, "read_receipt", fake_read("₦110,000.00", sender="IRETI", recipient="GRACE HOSPITAL YABA"))
    as_(client, "Amina Bello")
    assert client.post("/api/groups/1/entries/out", data={"obligation_id": ob_id(client, "Medical"), "amount": "120000",
                       "occurred_on": today(), "counterparty": "Grace Hospital Yaba"}).status_code == 403
    as_(client, "Ngozi Eze")
    r = client.post("/api/groups/1/entries/out",
                    data={"obligation_id": ob_id(client, "Medical"), "amount": "120,000", "occurred_on": today(),
                          "counterparty": "Grace Hospital Yaba"},
                    files={"proof_file": ("r.png", png(), "image/png")}).json()
    assert r["status"] == "needs_review"
    d = client.post(f"/api/groups/1/entries/{r['id']}/decide", json={"decision": "verify"})
    assert d.status_code == 403 and "someone else" in d.json()["detail"]
    as_(client, "Halima Yusuf")
    assert client.post(f"/api/groups/1/entries/{r['id']}/decide",
                       json={"decision": "reject", "note": "Receipt shows 110,000"}).json()["status"] == "rejected"


def test_cannot_decide_entry_from_another_group(client):
    as_(client, "Ngozi Eze")
    with db.tx() as conn:
        foreign = conn.execute("SELECT id FROM entries WHERE group_id=2").fetchone()["id"]
    assert client.post(f"/api/groups/1/entries/{foreign}/decide", json={"decision": "verify"}).status_code == 404


def test_rejects_non_images_and_bad_input(client):
    as_(client, "Amina Bello")
    base = {"obligation_id": ob_id(client, "Wedding"), "occurred_on": today()}
    assert client.post("/api/groups/1/entries/in", data={**base, "amount": "5000"},
                       files={"proof_file": ("x.png", b"<script>alert(1)</script>", "image/png")}).status_code == 415
    assert client.post("/api/groups/1/entries/in", data={**base, "amount": "lots"}).status_code == 422
    assert client.post("/api/groups/1/entries/in", data={**base, "amount": "5000",
                       "occurred_on": "2999-01-01"}).status_code == 422
    with db.tx() as conn:
        foreign_ob = conn.execute("SELECT id FROM obligations WHERE group_id=2").fetchone()["id"]
    assert client.post("/api/groups/1/entries/in", data={**base, "amount": "5000",
                       "obligation_id": foreign_ob}).status_code == 422


def test_ledger_is_tamper_evident(client):
    as_(client, "Amina Bello")
    assert client.get("/api/groups/1/verify").json()["intact"] is True
    with db.tx() as conn:  # someone edits history directly in the database
        conn.execute("UPDATE ledger_events SET detail=replace(detail, '500000', '5000000') "
                     "WHERE id=(SELECT MIN(id) FROM ledger_events WHERE group_id=1)")
    assert client.get("/api/groups/1/verify").json()["intact"] is False
