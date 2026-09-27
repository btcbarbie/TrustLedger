from datetime import date

from app.money import format_naira, parse_naira
from app.rules import assess_proof, can_decide, member_record, obligation_summary, parse_date_text

D = date(2026, 9, 27)


def read(**kw):
    ext = {"is_transfer_receipt": True, "amount_text": "₦5,000.00", "date_text": "27 Sep 2026, 10:14",
           "sender_name": "AMINA BELLO", "recipient_name": "IRETI WOMEN'S COOPERATIVE",
           "reference": "DMB1", "confidence": 0.95}
    ext.update(kw)
    return {"ok": True, "extraction": ext, "provider": "test"}


def assess(r, amount=500000, names=("Amina Bello",), direction="in", **kw):
    return assess_proof(direction=direction, amount_kobo=amount, occurred_on=D,
                        expected_names=list(names), read=r, **kw)


def test_money_parsing():
    assert parse_naira("₦45,000.00") == 4_500_000
    assert parse_naira("50k") == 5_000_000
    assert parse_naira("NGN 2,000") == 200_000
    assert parse_naira("5000") == 500_000
    assert parse_naira("abc") is None and parse_naira("0") is None and parse_naira("-5") is None
    assert format_naira(4_500_000) == "₦45,000" and format_naira(150) == "₦1.50"


def test_date_parsing():
    assert parse_date_text("27 Sep 2026, 10:14") == D
    assert parse_date_text("27th Sept 2026") == D
    assert parse_date_text("27/09/2026") == D
    assert parse_date_text("2026-09-27") == D
    assert parse_date_text("yesterday") is None


def test_matching_proof_is_documented():
    assert assess(read())[0] == "documented"


def test_name_alias_matches():
    status, _ = assess(read(sender_name="MAMA CHINWE"), names=("Chinwe Okafor", "Mama Chinwe"))
    assert status == "documented"


def test_no_proof_is_reported():
    assert assess(None)[0] == "reported"


def test_amount_mismatch_needs_review():
    status, reasons = assess(read(amount_text="₦45,000.00"), amount=5_000_000)
    assert status == "needs_review" and "₦45,000" in reasons[0] and "₦50,000" in reasons[0]


def test_wrong_sender_needs_review():
    status, reasons = assess(read(sender_name="TUNDE BAKARE"))
    assert status == "needs_review" and "TUNDE BAKARE" in " ".join(reasons)


def test_date_far_off_needs_review():
    assert assess(read(date_text="01 Aug 2026"))[0] == "needs_review"


def test_duplicate_screenshot_and_reference():
    status, reasons = assess(read(), duplicate_of_hash=7, duplicate_of_reference=7)
    assert status == "needs_review" and len(reasons) == 2


def test_ai_failure_and_non_receipt_go_to_human():
    assert assess({"ok": False, "extraction": None})[0] == "needs_review"
    assert assess(read(is_transfer_receipt=False))[0] == "needs_review"


def test_payout_checks_recipient_not_sender():
    r = read(amount_text="₦120,000.00", sender_name="IRETI WOMEN'S COOPERATIVE", recipient_name="GRACE HOSPITAL YABA")
    assert assess(r, amount=12_000_000, names=("Grace Hospital, Yaba",), direction="out")[0] == "documented"


def test_injected_amount_cannot_become_verified():
    # Even if a hidden instruction fooled the model into reporting 50,000, the rules only
    # ever return documented/needs_review - never verified. Humans verify.
    status, _ = assess(read(amount_text="50,000"), amount=500_000)
    assert status == "needs_review"
    assert assess(read())[0] != "verified"


E = {"status": "documented", "created_by": 3, "member_id": 3}


def test_no_self_approval():
    assert can_decide(actor_id=2, actor_role="treasurer", entry=E)[0] is True
    assert can_decide(actor_id=3, actor_role="member", entry=E)[0] is False
    own = {"status": "documented", "created_by": 2, "member_id": 2}
    assert can_decide(actor_id=2, actor_role="treasurer", entry=own)[0] is False   # treasurer's own payment
    assert can_decide(actor_id=1, actor_role="president", entry=own)[0] is True    # president checks treasurer
    payout = {"status": "needs_review", "created_by": 2, "member_id": None}
    assert can_decide(actor_id=2, actor_role="treasurer", entry=payout)[0] is False  # treasurer's own payout
    assert can_decide(actor_id=1, actor_role="president", entry=payout)[0] is True
    assert can_decide(actor_id=1, actor_role="president", entry={**E, "status": "verified"})[0] is False


def _e(direction, ob, member, kobo, day, status="verified"):
    return {"direction": direction, "obligation_id": ob, "member_id": member, "amount_kobo": kobo,
            "occurred_on": day, "status": status}


def test_obligation_summary_in_out_balance():
    ob = {"id": 1, "amount_due_kobo": 2_000_000}
    entries = [_e("in", 1, 1, 2_000_000, "2026-09-10"), _e("in", 1, 2, 2_000_000, "2026-09-11"),
               _e("in", 1, 3, 2_000_000, "2026-09-12", "documented"), _e("out", 1, None, 3_000_000, "2026-09-20"),
               _e("in", 1, 4, 2_000_000, "2026-09-12", "rejected")]
    s = obligation_summary(ob, 6, entries)
    assert s["target_kobo"] == 12_000_000 and s["collected_kobo"] == 4_000_000
    assert s["collected_pending_kobo"] == 2_000_000 and s["spent_kobo"] == 3_000_000
    assert s["balance_kobo"] == 1_000_000


def test_member_record_states():
    obs = [{"id": i, "title": f"W{i}", "due_date": f"2026-09-{d}", "amount_due_kobo": 500_000}
           for i, d in [(1, "05"), (2, "12"), (3, "19"), (4, "26"), (5, "30")]]
    entries = [_e("in", 1, 9, 500_000, "2026-09-04"),             # on time
               _e("in", 2, 9, 500_000, "2026-09-14"),             # late
               _e("in", 3, 9, 300_000, "2026-09-18"),             # partial
               _e("in", 4, 9, 500_000, "2026-09-25", "reported")]  # unverified -> missed, pending shown
    r = member_record(9, obs, entries, D)
    assert r["counts"] == {"on_time": 1, "late": 1, "partial": 1, "missed": 1, "upcoming": 1}
    assert r["rows"][3]["pending_kobo"] == 500_000
