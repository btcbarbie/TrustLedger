# Deploying TrustLedger on Railway

Railway builds straight from the GitHub repo. After this one-time setup, every push to `main`
redeploys automatically.

## 1. Create the service
1. Railway dashboard → **New Project** → **Deploy from GitHub repo** → pick `btcbarbie/TrustLedger`.
2. Railway detects Python (`requirements.txt`, `.python-version`) and starts the app with the
   `Procfile` (`python -m scripts.serve`). No build or start command needs to be typed in.

## 2. Add a disk (so data survives redeploys)
1. In the service → **Volumes** (or right-click the service → *Attach volume*).
2. Mount path: **`/data`**

## 3. Set the variables
Service → **Variables** → add these (use **Raw Editor** to paste them in one go):

```
DATA_DIR=/data
DB_PATH=/data/trustledger.db
SECURE_COOKIES=1
SESSION_SECRET=<a long random string - see below>
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=meta/llama-3.2-11b-vision-instruct
LLM_PROVIDER_LABEL=NVIDIA Build
LLM_IMAGE_MODE=openai
LLM_API_KEY=<your own NVIDIA Build key, starts with nvapi->
```

- **SESSION_SECRET:** any long random string. On a Mac: `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`
- **LLM_API_KEY:** create your own at build.nvidia.com → open *llama-3.2-11b-vision-instruct* → **Get API Key**.
  Paste it only into Railway. Never into the code, the repo, chat, slides or the video.

## 4. Get the public link
Service → **Settings** → **Networking** → **Generate Domain**. Open the `https://...up.railway.app`
link. On the first start the app loads the three demo groups (synthetic data) automatically.
It only does this when the database is empty, so later redeploys keep all data.

Optional: **Settings → Healthcheck path** = `/api/health`.

## 5. Check it works
- The landing page shows three demo groups.
- Open *Ireti Women's Cooperative* as Ngozi, click **I've paid**, upload
  `data/demo_uploads/1_amina_inventory_shows_45000.png` from the repo with amount 50,000.
  It should say *Needs review: Proof shows ₦45,000 but ₦50,000 was entered.*
  That confirms the AI key works.

## Resetting the demo data
Delete `trustledger.db` on the volume (or detach and re-create the volume) and redeploy.
The demo groups are recreated on the next start.

## Security notes
- This is a demo: there is no login, and anyone with the link can pick any person under
  "Viewing as". Only use synthetic data.
- Keys live only in Railway variables. `.env` is git-ignored.
