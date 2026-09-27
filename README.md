# TrustLedger

**Every transaction, in the open.** A shared ledger for savings groups and cooperatives.

Live prototype: **https://trustledger-production-b39d.up.railway.app**
(demo data only - pick a demo group and a person under "Viewing as"; no password needed)

Built at the GOMYCODE "Come Build with AI" hackathon, 27 September 2026.

---

## The problem

Savings groups, cooperatives and community funds move real money on trust. Records live in
WhatsApp messages, screenshots and one person's notebook. When someone asks "did she pay?" or
"where did the money go?", nobody can prove it, and the treasurer carries all the risk.

## What TrustLedger does

- **Record a payment with proof.** A member taps "I've paid" and adds the transfer screenshot.
  AI reads the amount, date and sender; fixed rules compare it with what was entered and flag
  mismatches, duplicate screenshots and the wrong sender.
- **A second person confirms everything.** Nobody can confirm their own entry.
- **Payouts need approval before money moves.** The treasurer requests a payout, the president
  approves it, the treasurer pays and uploads the receipt, and the receipt is checked against the
  *approved* amount and payee. Nothing counts until it is confirmed.
- **Several pots at once.** Weekly or monthly contributions plus one-off goals (a wedding, a
  medical bill, bulk stock), each with collected, spent and balance.
- **One shared view.** Money in minus money out equals what is in the pot, with a paginated
  ledger, running balance and the receipt behind every figure.
- **Member payment records, not scores.** Facts only: paid on time, late, part paid, missed.
- **Tamper-evident history.** Every action is hash-chained to the one before it; a one-click
  integrity check shows if anyone edited the past.
- **WhatsApp chat import.** Upload an exported group chat; AI finds past payments, members are
  created from the participants, and every claim waits for confirmation.
- **Ask TrustLedger.** Plain-language questions ("summary of September", "who has not paid
  week 6?") answered from the ledger, with the source entries listed under each answer.

## Roles

| Role | Can do |
| --- | --- |
| Treasurer | Request payouts, upload payout receipts, confirm members' payments |
| President | Approve or decline payouts, add contributions and goals, confirm members' payments and the treasurer's own entries |
| Member | Record their own payments, see the whole ledger, ask questions |

The person holding the money can never approve spending it, and nobody confirms their own entry.

## How the AI is used - "AI reads, code decides"

Model: **NVIDIA Build API, `meta/llama-3.2-11b-vision-instruct`**, through an OpenAI-compatible
client (the provider is a configuration setting).

| Job | What the AI does | What the code does |
| --- | --- | --- |
| Receipts | Reads amount, date, sender, recipient, reference | Parses the amount, compares with what was entered or approved, checks duplicates, sets the status |
| WhatsApp import | Finds messages that report a payment | Accepts an amount only if it appears in that exact message, matches names, maps to the right week, flags duplicates |
| Ask | Turns the question into a structured request | Looks up every number in the ledger and lists the sources |

The AI never sets a status, moves money or makes a decision about a person.

**Fallbacks:** if the AI is unavailable, receipts go to human review, and chat import and
questions switch to rule-based readers. Instructions hidden in receipts or messages ("mark this
verified") are ignored and flagged.

**Results on our demo files (27 September 2026):** 8 of 8 receipts judged correctly, including
one with a hidden instruction; 17 of 18 payments found in a sample chat (a payment made on
behalf of another member was missed).

NVIDIA Brev was not used; the hosted NVIDIA Build API was enough for this workload.

## Security and data handling

- **Identity from the session, never from the request.** Who you are comes from a signed
  session cookie; a member can only record payments as themselves.
- **Group isolation.** Every request checks membership; other groups return "not found", so
  their existence is not revealed.
- **Separation of duties** as described under Roles, enforced on the server, not only in the UI.
- **Tamper evidence:** hash-chained activity log with an integrity check.
- **Uploads:** checked by content (PNG, JPEG, WEBP only), size-limited, stored under random
  names, and served only to members of that group.
- **Money** is stored as whole kobo (integers), never floating point.
- **Secrets** live only in environment variables; `.env` is git-ignored. Cookies are
  `HttpOnly`, `SameSite=Lax` and `Secure` in production.
- **Demo limitations, on purpose:** there is no real login ("Viewing as" lets anyone act as any
  demo person) and all data is synthetic. Do not enter real personal or financial data.

## Run it locally

Requires Python 3.13.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then add your NVIDIA Build key to LLM_API_KEY
.venv/bin/python -m scripts.seed
.venv/bin/uvicorn app.main:app --port 8765
```

Open http://localhost:8765. Without a key the app still works: receipts go to human review and
the rule-based readers take over.

Tests:

```bash
.venv/bin/python -m pytest -q tests      # 37 tests
```

Deploying: see [DEPLOY.md](DEPLOY.md) (Railway, persistent disk, variables).

## Demo data

Everything is made up: three groups (Ireti Women's Cooperative, Summit Heights Housing
Cooperative, Bright Futures Scholarship Fund), their members and history, receipt images from a
fictional "Demo Bank" watermarked **DEMO DATA**, and a sample WhatsApp chat. Files to try live
are in `data/demo_uploads/` (for example a receipt showing ₦45,000 to record as ₦50,000).

## Project structure

```
app/        main.py (API), rules.py (money rules and permissions), proof.py (receipt reading),
            whatsapp.py (chat import), ask.py (questions), llm.py (model client), db.py (schema,
            hash-chained log), groups_api.py (groups, invites, import)
web/        index.html, styles.css, app.js (no build step)
scripts/    seed.py (demo data), receipts.py (synthetic receipts), serve.py (production start)
tests/      rules, API security, groups and import, questions
```

## Next steps

Pilot with 3 to 5 real savings groups; real sign-up with phone verification; PostgreSQL with
row-level security; verifying payments against bank and mobile-money statements; and
consent-based sharing of a member's payment record with lenders and credit bureaus, so group
savers can build a credit history.

## AI tools used to build it

Claude Code (Anthropic) was used as an AI coding assistant during the hackathon.
