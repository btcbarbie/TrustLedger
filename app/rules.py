"""Deterministic financial rules. The AI never sets a status - these functions do."""
import re
from datetime import date, datetime

from rapidfuzz import fuzz

from .money import format_naira, parse_naira

DATE_TOLERANCE_DAYS = 3
NAME_MATCH_THRESHOLD = 80
MIN_CONFIDENCE = 0.5
APPROVER_ROLES = {"president", "treasurer"}

_ORD = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.IGNORECASE)
_DATE_FORMATS = ["%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%d/%m/%Y", "%d-%m-%Y",
                 "%Y-%m-%d", "%d.%m.%Y", "%d %b, %Y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%y"]


def parse_date_text(text: str | None) -> date | None:
    if not text:
        return None
    t = _ORD.sub(r"\1", str(text)).replace("Sept", "Sep").strip()
    # drop a trailing time like ", 10:14" or " 10:14:22 AM"
    t = re.split(r"[,\s]+\d{1,2}:\d{2}", t)[0].strip().rstrip(",")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def names_match(printed: str | None, candidates: list[str]) -> bool:
    if not printed:
        return False
    p = printed.lower()
    return any(fuzz.token_set_ratio(p, c.lower()) >= NAME_MATCH_THRESHOLD for c in candidates if c)


def assess_proof(*, direction: str, amount_kobo: int, occurred_on: date,
                 expected_names: list[str], read: dict | None,
                 duplicate_of_hash: int | None = None,
                 duplicate_of_reference: int | None = None) -> tuple[str, list[str]]:
    """Returns (status, reasons). `read` is proof.read_receipt output, or None when no proof."""
    if read is None:
        return "reported", ["No proof attached - recorded on the member's word."]
    reasons: list[str] = []
    if duplicate_of_hash:
        reasons.append(f"This exact screenshot was already used for entry #{duplicate_of_hash}.")
    if not read.get("ok"):
        reasons.append("The AI could not read this proof. Please check it manually.")
        return "needs_review", reasons
    ext = read["extraction"]
    if not ext["is_transfer_receipt"]:
        reasons.append("This does not look like a transfer receipt.")
        return "needs_review", reasons
    if ext.get("confidence", 0) < MIN_CONFIDENCE:
        reasons.append("The proof was hard to read clearly.")
    proof_amount = parse_naira(ext.get("amount_text"))
    if proof_amount is None:
        reasons.append("No amount could be read on the proof.")
    elif proof_amount != amount_kobo:
        reasons.append(f"Proof shows {format_naira(proof_amount)} but {format_naira(amount_kobo)} was entered.")
    proof_date = parse_date_text(ext.get("date_text"))
    if proof_date is None:
        reasons.append("No date could be read on the proof.")
    elif abs((proof_date - occurred_on).days) > DATE_TOLERANCE_DAYS:
        reasons.append(f"Proof is dated {proof_date:%d %b %Y} but {occurred_on:%d %b %Y} was entered.")
    party = ext.get("sender_name") if direction == "in" else ext.get("recipient_name")
    who = "Sender" if direction == "in" else "Recipient"
    if not party:
        reasons.append(f"{who} name is not visible on the proof.")
    elif not names_match(party, expected_names):
        reasons.append(f"{who} on the proof is \"{party}\", which does not match {expected_names[0]}.")
    if duplicate_of_reference:
        reasons.append(f"Transaction reference already used for entry #{duplicate_of_reference}.")
    return ("needs_review", reasons) if reasons else ("documented", ["Proof matches the amount, date and name."])


PAYOUT_OPEN = ("requested", "approved")
NOT_COUNTED = ("rejected", "declined")


def can_decide(*, actor_id: int, actor_role: str, entry: dict) -> tuple[bool, str]:
    """No self-approval: whoever created an entry, uploaded its receipt, or whose payment it is, cannot confirm it."""
    if actor_role not in APPROVER_ROLES:
        return False, "Only the president or treasurer can confirm entries."
    if entry["status"] == "requested":
        return False, "This payout has not been approved yet."
    if entry["status"] == "approved":
        return False, "Approved. Waiting for the receipt after the payment is made."
    if entry["status"] in ("verified", "rejected", "declined"):
        return False, "This entry has already been decided."
    if entry.get("receipt_by") is not None and actor_id == entry["receipt_by"]:
        return False, "You uploaded this receipt, so someone else must confirm it."
    if actor_id == entry["created_by"]:
        return False, "You created this entry, so someone else must confirm it."
    if entry.get("member_id") is not None and actor_id == entry["member_id"]:
        return False, "This is your own payment, so someone else must confirm it."
    return True, ""


def can_approve_payout(*, actor_id: int, actor_role: str, entry: dict) -> tuple[bool, str]:
    """A payout request must be approved by a leader other than the one who asked for it."""
    if entry["status"] != "requested":
        return False, "This payout is not waiting for approval."
    if actor_role not in APPROVER_ROLES:
        return False, "Waiting for a leader to approve this payout."
    if actor_id == entry["created_by"]:
        return False, "You requested this payout, so another leader must approve it."
    return True, ""


def can_add_receipt(*, actor_role: str, entry: dict) -> tuple[bool, str]:
    if entry["status"] != "approved":
        return False, "A receipt can only be added after the payout is approved."
    if actor_role not in APPROVER_ROLES:
        return False, "Approved. Waiting for a leader to upload the receipt."
    return True, ""


def obligation_summary(obligation: dict, member_count: int, entries: list[dict]) -> dict:
    mine = [e for e in entries if e["obligation_id"] == obligation["id"] and e["status"] not in NOT_COUNTED]
    def total(direction, verified):
        return sum(e["amount_kobo"] for e in mine
                   if e["direction"] == direction and (e["status"] == "verified") == verified)
    target = obligation["amount_due_kobo"] * member_count
    collected, spent = total("in", True), total("out", True)
    return {"target_kobo": target, "collected_kobo": collected, "collected_pending_kobo": total("in", False),
            "spent_kobo": spent, "spent_pending_kobo": total("out", False),
            "balance_kobo": collected - spent, "remaining_kobo": max(target - collected, 0)}


def member_record(member_id: int, obligations: list[dict], entries: list[dict], today: date) -> dict:
    """Facts only - no score. Counts only verified money as paid."""
    rows, counts = [], {"on_time": 0, "late": 0, "partial": 0, "missed": 0, "upcoming": 0}
    for ob in sorted(obligations, key=lambda o: o["due_date"]):
        due = date.fromisoformat(ob["due_date"])
        paid = [e for e in entries if e["direction"] == "in" and e["member_id"] == member_id
                and e["obligation_id"] == ob["id"]]
        verified = [e for e in paid if e["status"] == "verified"]
        pending = [e for e in paid if e["status"] in ("reported", "documented", "needs_review")]
        amount = sum(e["amount_kobo"] for e in verified)
        last = max((date.fromisoformat(e["occurred_on"]) for e in verified), default=None)
        if amount >= ob["amount_due_kobo"]:
            state = "on_time" if last <= due else "late"
        elif amount > 0:
            state = "partial"
        elif due < today:
            state = "missed"
        else:
            state = "upcoming"
        counts[state] += 1
        rows.append({"obligation_id": ob["id"], "title": ob["title"], "due_date": ob["due_date"],
                     "due_kobo": ob["amount_due_kobo"], "paid_kobo": amount,
                     "pending_kobo": sum(e["amount_kobo"] for e in pending),
                     "last_paid_on": last.isoformat() if last else None, "state": state})
    return {"counts": counts, "rows": rows}
