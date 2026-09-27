from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, llm


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "SEED_PROOF_DIR", tmp_path / "seed_proofs")
    def no_ai(*a, **k):
        raise llm.LLMError("offline in tests")
    monkeypatch.setattr(llm, "complete_json", no_ai)
    from scripts import seed
    seed.main()
    from app.main import app
    with TestClient(app) as c:
        yield c


def signup(c, name):
    return c.post("/api/signup", json={"name": name}).json()["user"]


def new_group(c, **over):
    body = {"name": "Oja Oba Savers", "my_role": "treasurer", "members": ["Sade Bello", "Yemi Ojo"],
            "second_leader": "Sade Bello",
            "contribution": {"amount": "3,000", "frequency": "weekly",
                             "first_due": (date.today() + timedelta(days=6)).isoformat(), "periods": 12},
            "goal": {"title": "Christmas bulk buy", "amount": "20000", "due_date": "2026-12-01"}}
    body.update(over)
    return c.post("/api/groups", json=body)


def test_signup_then_create_long_term_group(client):
    me = signup(client, "Grace Nwosu")
    r = new_group(client)
    assert r.status_code == 200, r.text
    gid = r.json()["group_id"]
    ov = client.get(f"/api/groups/{gid}").json()
    assert ov["my_role"] == "treasurer"
    roles = {m["name"]: m["role"] for m in ov["members"]}
    assert roles == {"Grace Nwosu": "treasurer", "Sade Bello": "president", "Yemi Ojo": "member"}
    assert len([o for o in ov["obligations"] if o["series"] == "Weekly contribution"]) == 12
    assert any(o["title"] == "Christmas bulk buy" for o in ov["obligations"])
    assert "invite_code" not in ov["group"]


def test_group_needs_a_second_leader(client):
    signup(client, "Solo Sam")
    assert new_group(client, second_leader="Nobody").status_code == 422
    assert new_group(client, members=["A One", "a one"], second_leader="A One").status_code == 422


def test_invite_and_join(client):
    signup(client, "Grace Nwosu")
    gid = new_group(client).json()["group_id"]
    code = client.get(f"/api/groups/{gid}/invite").json()["code"]
    signup(client, "New Neighbour")
    assert client.get(f"/api/groups/{gid}").status_code == 404      # not a member yet
    assert client.get(f"/api/join/{code}").json()["group"] == "Oja Oba Savers"
    assert client.post(f"/api/join/{code}").json()["group_id"] == gid
    assert client.get(f"/api/groups/{gid}").json()["my_role"] == "member"
    assert client.post("/api/join/not-a-real-code").status_code == 404


def test_add_contribution_to_demo_group(client):
    people = {p["name"]: p["id"] for p in client.get("/api/people").json()}
    client.post("/api/view-as", json={"user_id": people["Amina Bello"]})
    goal = {"kind": "goal", "goal": {"title": "Generator repair", "amount": "3000", "due_date": "2026-10-30"}}
    assert client.post("/api/groups/1/obligations", json=goal).status_code == 403   # members cannot
    client.post("/api/view-as", json={"user_id": people["Ngozi Eze"]})
    assert client.post("/api/groups/1/obligations", json=goal).status_code == 200
    rec = {"kind": "recurring", "series_name": "Monthly dues",
           "contribution": {"amount": "10k", "frequency": "monthly", "first_due": "2026-10-31", "periods": 6}}
    assert len(client.post("/api/groups/1/obligations", json=rec).json()["created"]) == 6
    titles = [o["title"] for o in client.get("/api/groups/1").json()["obligations"]]
    assert "Generator repair" in titles and "Monthly dues - Oct 2026" in titles and "Monthly dues - Feb 2027" in titles


def test_whatsapp_import_with_rule_based_fallback(client):
    signup(client, "Grace M.")
    chat = (config.ROOT / "data" / "demo_uploads" / "9_whatsapp_riverside_library_fund.txt").read_bytes()
    prev = client.post("/api/import/whatsapp/preview", files={"chat_file": ("chat.txt", chat, "text/plain")}).json()
    names = [p["name"] for p in prev["participants"]]
    assert set(names) == {"Grace Mensah", "Tunde Bakare", "Leila Haddad", "Musa Ibrahim", "Chloe Martin"}
    assert prev["flagged"] == 1
    r = client.post("/api/import/whatsapp/create", json={
        "token": prev["token"], "group_name": "Riverside Library Fund", "me": "Grace Mensah", "my_role": "treasurer",
        "second_leader": "Leila Haddad", "amount": "5000", "frequency": "weekly"}).json()
    assert r["read_by"].startswith("Rule-based") and r["payments_found"] >= 12
    assert r["needs_review"] >= 1                       # Chiamaka's duplicate message
    assert any("SYSTEM NOTE" in f for f in r["flagged"])
    entries = client.get(f"/api/groups/{r['group_id']}/entries").json()
    assert all(e["status"] in ("reported", "needs_review") for e in entries)   # nothing auto-verified
    assert not any(e["amount_kobo"] == 5_000_000 for e in entries)              # the injected 50000 is ignored
    ov = client.get(f"/api/groups/{r['group_id']}").json()
    assert {m["name"]: m["role"] for m in ov["members"]}["Leila Haddad"] == "president"
    # the importer created these entries, so the importer cannot confirm them - the president must
    assert not any(e["can_decide"] for e in entries)
    # the preview token is single use
    again = client.post("/api/import/whatsapp/create", json={
        "token": prev["token"], "group_name": "Again", "me": "Grace Mensah", "second_leader": "Leila Haddad", "amount": "5000"})
    assert again.status_code == 410


def test_import_rejects_non_chat_files(client):
    signup(client, "Someone")
    r = client.post("/api/import/whatsapp/preview", files={"chat_file": ("x.txt", b"hello world", "text/plain")})
    assert r.status_code == 422
