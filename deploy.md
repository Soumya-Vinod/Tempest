# Deploying Tempest (Render + Vercel)

The API runs on **Render** as one Docker web service (`tempest-api`, region Singapore, free
plan), built from `api/Dockerfile` with `DEMO_MODE=true`. `render.yaml` at the repo root is the
Blueprint that defines it. The web app is on **Vercel**, which builds `web/` and forwards
The browser calls the Render service **directly**:
the production build has `VITE_API_BASE_URL` set to the Render URL, and Render allows the Vercel
origin through `CORS_ORIGINS`. (Going through Vercel's `/api/*` rewrite in `web/vercel.json`
timed out on the free instance and returned 502s; the rewrite is still there as a fallback for
a build without `VITE_API_BASE_URL`.) Keys are Render environment variables; none are in the
image or in the repo.

**Pre-rendered responses.** The image build runs `api/scripts/build_static_responses.py`, which
requests every route and parameter combination the web app uses (25 timesteps × both horizons ×
each impact status, plus hazard layers, exposure, risk, insurance, countdown, departures, track,
unscored areas and validation) and stores each final response gzip-compressed in
`/app/data/static/` (about 9 MB, 371 responses). In DEMO_MODE the API sends those files as they
are, so a request costs a file read instead of parsing, rebuilding and compressing large
fixtures. Anything else (advisories, dispatch, an unexpected parameter) runs the route code.

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
   | `GMAIL_ADDRESS` | Address that sends dispatch e-mails (must be a verified sender in Brevo) |
   | `GMAIL_APP_PASSWORD` | Gmail app password; only used with `EMAIL_PROVIDER=smtp`, so it can stay empty here |
   | `BREVO_API_KEY` | Brevo API key (**Brevo → SMTP & API → API Keys**) |
   | `DISPATCH_EMAIL_TO` | Dispatch recipients, comma-separated |
   | `DISPATCH_PIN` | PIN required for a live dispatch |
   | `CORS_ORIGINS` | The Vercel site's origin, e.g. `https://tempest-xxxx.vercel.app` (no trailing slash; several: comma-separated). Leave it empty for now and fill it in at step 3. |

   `DEMO_MODE=true`, `STATE_DB_PATH=/tmp/tempest.db` and `EMAIL_PROVIDER=brevo` come from
   `render.yaml`. A key left
   empty just turns that feature off (`/health` reports it as `false`).
4. Click **Apply** to create the service. Open it (**Dashboard → tempest-api**).
5. Check **Settings → Build & Deploy**: Root Directory `api`, Dockerfile Path `./Dockerfile`
   (shown as `api/ ./Dockerfile`), Auto-Deploy **Off**. The build context is `api/`, which is
   what the Dockerfile expects (`COPY requirements.txt`, `COPY app`).
6. If no deploy started on its own: **Manual Deploy → Deploy latest commit**. Follow **Logs**:
   the build downloads the CAP 1.2 XSD and fails if its SHA-256 doesn't match, then installs
   the requirements, then pre-renders the responses (`N responses, … MB in /app/data/static`,
   a minute or two). The first build takes several minutes.
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
   - **Environment Variables:** add `VITE_API_BASE_URL` = the Render URL from step 1.7, e.g.
     `https://tempest-api-xxxx.onrender.com` (with `https://`, no trailing slash), for the
     **Production** environment (and Preview, if you use preview deployments). Vite bakes it in
     at build time, so changing it later needs a redeploy.
4. **Deploy.** When it finishes, note the production URL, e.g. `https://tempest-xxxx.vercel.app`.

The site loads at this point but API calls fail: `vercel.json` still points at a placeholder.

## 3. Allow the Vercel site on Render (CORS)

1. On Render: **tempest-api → Environment**, set `CORS_ORIGINS` to the Vercel production URL
   from step 2.4, e.g. `https://tempest-xxxx.vercel.app` (exactly the origin: `https://`, no
   path, no trailing slash). For a custom domain or preview URLs too, list them comma-separated.
   `http://localhost:5173` is always allowed.
2. **Save, rebuild, and deploy** (the setting is read at start-up).
3. Optional fallback: `web/vercel.json` still forwards `/api/*` and `/health` to Render. If the
   Render host changes, update it there too (it appears twice), but the app only uses it when
   `VITE_API_BASE_URL` is unset.

## 4. Check it end to end

1. Open the site with the browser's developer tools (**Network** tab). Requests should go to
   `https://tempest-api-xxxx.onrender.com/api/...`, not the Vercel origin; if they go to Vercel,
   `VITE_API_BASE_URL` wasn't set for that build (set it and redeploy).
2. A request blocked with a CORS error in the **Console** means `CORS_ORIGINS` on Render doesn't
   match the site's origin exactly (check `https`, the trailing slash, and the redeploy).
3. Large responses (`/api/impact/results`) should show `content-encoding: gzip` and come back
   in well under a second once the service is awake.
4. Scrub the timeline once, press Play, and open one block's risk breakdown and an advisory.

## Free-tier sleep and warming up before the demo

A free Render service **spins down after about 15 minutes without traffic**. The next request
starts it again, which takes about a minute. While it starts the web app shows "Waking up the
server…" and keeps its requests queued (at most 4 in flight). A spin-down also wipes `/tmp`, so the advisory queue starts empty.

Before the demo (10 minutes ahead is enough):

1. Open `https://<render-host>/health` **directly** (not through Vercel) and wait for the JSON.
2. Open the Vercel site and scrub the timeline once.
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

**E-mail dispatch:** Render's free tier blocks outbound SMTP, so `render.yaml` sets
`EMAIL_PROVIDER=brevo`: the API sends through Brevo's HTTPS API
(`POST https://api.brevo.com/v3/smtp/email`, authenticated with `BREVO_API_KEY`), with the same subject
and body as the Gmail path and the CAP XML attached as `cap.xml`. Before the first live dispatch,
add `GMAIL_ADDRESS` as a sender in Brevo (**Senders, Domains & Dedicated IPs → Senders**) and
confirm it from the verification e-mail; Brevo rejects mail from an unverified sender. Locally
the default `EMAIL_PROVIDER=smtp` keeps using Gmail SMTP with `GMAIL_APP_PASSWORD`. `/health`
shows `email_provider` and `configured.brevo_api_key` (true/false). Test one live e-mail dispatch
well before the demo; a Brevo error is stored in the receipt with the key scrubbed. If it fails,
Telegram still works.

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
