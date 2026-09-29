# Deploying Tempest (Render + Vercel)

The API runs on **Render** as one Docker web service (`tempest-api`, region Singapore, free
plan), built from `api/Dockerfile` with `DEMO_MODE=true`. `render.yaml` at the repo root is the
Blueprint that defines it. The web app is on **Vercel**, which builds `web/` and forwards
`/api/*` and `/health` to the Render service (`web/vercel.json`). The browser only talks to the
Vercel origin, so no CORS setup is needed. Keys are Render environment variables; none are in
the image or in the repo.

Nothing here has been run for you. Deploys are manual on Render (`autoDeploy: false`).

> **State is not durable.** Advisories, the audit log and dispatch receipts live in SQLite at
> `/tmp/tempest.db` inside the container. They are lost on every deploy, restart and free-tier
> spin-down (below), and the queue starts empty again.

## 1. API on Render

1. Sign in at <https://dashboard.render.com> with GitHub (or connect GitHub to your existing
   Render account) and give Render access to the Tempest repository.
2. **New → Blueprint.** Pick the Tempest repository and the branch to deploy (`main`). Render
   reads `render.yaml` and shows one service, `tempest-api` (Docker, Singapore, Free).
3. Render asks for a value for each variable marked `sync: false`. Paste them in:

   | Variable | Value |
   |---|---|
   | `GEMINI_API_KEY` | Gemini API key |
   | `GROQ_API_KEY` | Groq API key (fallback advisory model) |
   | `TELEGRAM_BOT_TOKEN` | Telegram bot token |
   | `TELEGRAM_CHAT_ID` | Telegram chat id (from `api\scripts\telegram_chat_ids.py`) |
   | `GMAIL_ADDRESS` | Gmail address that sends dispatch e-mails |
   | `GMAIL_APP_PASSWORD` | Gmail app password (16 characters) |
   | `DISPATCH_EMAIL_TO` | Dispatch recipients, comma-separated |
   | `DISPATCH_PIN` | PIN required for a live dispatch |

   `DEMO_MODE=true` and `STATE_DB_PATH=/tmp/tempest.db` come from `render.yaml`. A key left
   empty just turns that feature off (`/health` reports it as `false`).
4. Click **Apply** to create the service. Open it (**Dashboard → tempest-api**).
5. Check **Settings → Build & Deploy**: Root Directory `api`, Dockerfile Path `./Dockerfile`
   (shown as `api/ ./Dockerfile`), Auto-Deploy **Off**. The build context is `api/`, which is
   what the Dockerfile expects (`COPY requirements.txt`, `COPY app`).
6. If no deploy started on its own: **Manual Deploy → Deploy latest commit**. Follow **Logs**:
   the build downloads the CAP 1.2 XSD and fails if its SHA-256 doesn't match, then installs
   the requirements (the first build takes several minutes).
7. When the deploy is **Live**, copy the service URL from the top of the page, e.g.
   `https://tempest-api-xxxx.onrender.com`, and open `https://tempest-api-xxxx.onrender.com/health`.
   It should show `"demo_mode": true` and `true` for every key you set.

The Dockerfile starts uvicorn on `$PORT`. Render sets `PORT` for the service, so no port
configuration is needed.

To change a key later: **tempest-api → Environment** → edit the value → **Save, rebuild, and
deploy** (or **Save only**, then **Manual Deploy**).

## 2. Web app on Vercel

1. Sign in at <https://vercel.com> with GitHub.
2. **Add New… → Project → Import** the Tempest repository.
3. On **Configure Project**:
   - **Root Directory:** click **Edit** and choose `web`.
   - **Framework Preset:** Vite. Build Command `npm run build` and Output Directory `dist` are
     the defaults; leave them.
   - **Environment Variables:** none. Leave `VITE_API_BASE_URL` unset so the app calls `/api/...`
     on its own origin and `vercel.json` forwards it.
4. **Deploy.** When it finishes, note the production URL, e.g. `https://tempest-xxxx.vercel.app`.

The site loads at this point but API calls fail: `vercel.json` still points at a placeholder.

## 3. Point Vercel at the Render API

1. In `web/vercel.json`, replace `REPLACE-WITH-RENDER-HOST.onrender.com` with your Render host
   from step 1.7, without `https://` and without a trailing slash (e.g.
   `tempest-api-xxxx.onrender.com`). It appears **twice**:
   - line 7, the `/api/(.*)` rewrite (keep the `/api/$1` after the host), and
   - line 11, the `/health` rewrite (keep the `/health` after the host).
2. Commit and push to the branch Vercel deploys (`main`).
3. Vercel deploys each push to that branch on its own. If it doesn't, open the project →
   **Deployments** → the latest deployment → **⋯ → Redeploy**.

## 4. Check it end to end

1. Open `https://tempest-xxxx.vercel.app/health`. This goes through Vercel to Render. It should
   return the same JSON as step 1.7. An HTML page here means the `/health` rewrite is wrong.
   A 404 or 502 from Vercel means the Render host in `vercel.json` is wrong.
2. Open the site, scrub the timeline once, and open one block's risk breakdown and an advisory.

## Free-tier sleep and warming up before the demo

A free Render service **spins down after about 15 minutes without traffic**. The next request
starts it again, which takes about a minute. While it starts, requests through Vercel can fail
or time out. A spin-down also wipes `/tmp`, so the advisory queue starts empty.

Before the demo (10 minutes ahead is enough):

1. Open `https://<render-host>/health` **directly** (not through Vercel) and wait for the JSON.
2. Open the Vercel site and scrub the timeline once. The first load of each timestep's impact
   layer is large (about 12 MB of JSON) and is slow on the free instance's small CPU.
3. Keep a tab open, or use the monitor below, so it doesn't spin down again.

**Keep it awake with UptimeRobot (optional).** At <https://uptimerobot.com> (free account):
**Add New Monitor → HTTP(s)**, URL `https://<render-host>/health` (the Render URL, not Vercel),
interval **5 minutes** → **Create Monitor**. It pings the API often enough that it never
sleeps, and alerts you if it goes down. Render's free plan includes a monthly allowance of
instance hours per workspace, and one always-on service fits in it, but a second free service
kept awake would not. Pause the monitor after the demo.

## Watching memory

A free instance has **512 MB of RAM** and a fraction of a CPU (the old Cloud Run setup had
2 GiB). Run locally in DEMO_MODE, the API used about 140 MB at start-up and about 220 MB (peak
about 280 MB) after serving the hazard, exposure, impact, risk and insurance routes. So it fits,
without much headroom.

- **tempest-api → Metrics** shows memory and CPU. Check it after scrubbing the whole timeline.
- If the instance goes over the limit, Render restarts it. The **Events** tab shows the failure
  and the queue in `/tmp` is lost. If that happens, move the service to a paid instance type
  with more memory (**Settings → Instance Type**).

**E-mail dispatch:** the API sends mail through Gmail SMTP on port 587. Render may block
outbound SMTP ports on free instances (check Render's current free-tier limits). Test one live
e-mail dispatch well before the demo. If it fails, Telegram still works, or move to a paid
instance type.

## Roll back

**API (Render):** open **tempest-api → Events**, find the last good deploy and click
**Rollback**. With Auto-Deploy off you can also use **Manual Deploy → Deploy a specific
commit** and pick the good commit. Either way the instance restarts, so the SQLite queue in
`/tmp` starts empty. The next **Manual Deploy → Deploy latest commit** goes forward again.

**Web (Vercel):** open the project → **Deployments**, find the last good production deployment,
**⋯ → Instant Rollback** (or **Promote to Production**). The next push deploys forward again.
A rollback keeps that deployment's `vercel.json`, so check the Render host in it is still right.

## After the demo

- Pause or delete the UptimeRobot monitor, so the free service can spin down.
- To stop the API entirely: **tempest-api → Settings → Suspend Web Service** (resume from the
  same page).

## Local check before deploying

```powershell
api\.venv\Scripts\python -m pytest api\tests\test_smoke_demo.py   # the container's view: DEMO_MODE,
                                                                   # no keys, no raw/processed data
```

To try the image the way Render runs it (Docker Desktop, from the repo root):

```powershell
docker build -t tempest-api api
docker run --rm -p 10000:10000 -e PORT=10000 tempest-api
# then open http://localhost:10000/health
```
