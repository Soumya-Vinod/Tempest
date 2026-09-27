# Deploying Tempest (Day 5)

The API runs on **Cloud Run** (`tempest-api`, region `asia-south1`), built from `api/Dockerfile`
with `DEMO_MODE=true`. The web app is on **Firebase Hosting**, which serves `web/dist` and
forwards `/api/**` and `/health` to the Cloud Run service (same origin, so no CORS). Keys come
from **Secret Manager** as environment variables; none are in the image.

All commands are PowerShell, run from the repo root. Nothing here has been run for you.

> **State is not durable.** Advisories, the audit log and dispatch receipts live in SQLite at
> `/tmp/tempest.db` inside the container. `/tmp` is in memory: it is lost on every restart,
> redeploy or scale-down, and it counts against the memory limit. `--max-instances=1` keeps a
> single instance, so every request sees the same queue; `--min-instances=1` during judging
> stops it being scaled to zero (and wiped) between visits.

## 0. One-time setup

```powershell
$PROJECT = "YOUR-GCP-PROJECT-ID"
$REGION  = "asia-south1"
$REPO    = "tempest"
$SA      = "tempest-api@$PROJECT.iam.gserviceaccount.com"

gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
  artifactregistry.googleapis.com secretmanager.googleapis.com firebasehosting.googleapis.com

# Container images
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION

# A service account for the API (it only needs to read its secrets)
gcloud iam service-accounts create tempest-api --display-name="Tempest API"

# Firebase CLI (once): npm install -g firebase-tools; then:
firebase login
```

Set your project id in `.firebaserc` (`"default": "YOUR-GCP-PROJECT-ID"`), and add Firebase to
the GCP project in the Firebase console if it isn't already.

## 1. Secrets (Secret Manager)

The helper reads each value without echoing it and writes it via a temporary file, so the value
is not in your shell history and has no trailing newline (piping a string to gcloud in
PowerShell 5.1 would add one).

```powershell
function Set-TempestSecret([string]$Name, [string]$Prompt) {
  $secure = Read-Host -AsSecureString $Prompt
  $plain  = [System.Net.NetworkCredential]::new("", $secure).Password
  $tmp    = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp, $plain)          # exact bytes, no newline
    gcloud secrets describe $Name *> $null
    if ($LASTEXITCODE -eq 0) {
      gcloud secrets versions add $Name --data-file=$tmp  # update an existing secret
    } else {
      gcloud secrets create $Name --replication-policy=automatic --data-file=$tmp
    }
  } finally { Remove-Item $tmp -Force }
}

Set-TempestSecret gemini-api-key      "Gemini API key"
Set-TempestSecret groq-api-key        "Groq API key"
Set-TempestSecret telegram-bot-token  "Telegram bot token"
Set-TempestSecret telegram-chat-id    "Telegram chat id (from api\scripts\telegram_chat_ids.py)"
Set-TempestSecret gmail-address       "Gmail address"
Set-TempestSecret gmail-app-password  "Gmail app password"
Set-TempestSecret dispatch-email-to   "Dispatch recipients (comma-separated)"
Set-TempestSecret dispatch-pin        "Dispatch PIN"

# Let the API's service account read them
foreach ($s in "gemini-api-key","groq-api-key","telegram-bot-token","telegram-chat-id",
               "gmail-address","gmail-app-password","dispatch-email-to","dispatch-pin") {
  gcloud secrets add-iam-policy-binding $s `
    --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"
}
```

To change a value later, run `Set-TempestSecret` again (it adds a new version), then redeploy
(step 3) or `gcloud run services update tempest-api --region $REGION` so the service picks up
`latest`.

## 2. Build the API image (Cloud Build)

`api/.gcloudignore` (which includes `api/.dockerignore`) keeps `.venv`, `data/raw`,
`data/processed`, `data/state`, `.env` files and `secrets/` out of the upload. The build
downloads the CAP 1.2 XSD and fails if its SHA-256 doesn't match.

```powershell
$TAG   = (git rev-parse --short HEAD)
$IMAGE = "$REGION-docker.pkg.dev/$PROJECT/$REPO/tempest-api:$TAG"

gcloud builds submit api --tag $IMAGE
```

## 3. Deploy to Cloud Run

```powershell
$SECRETS = @(
  "GEMINI_API_KEY=gemini-api-key:latest",
  "GROQ_API_KEY=groq-api-key:latest",
  "TELEGRAM_BOT_TOKEN=telegram-bot-token:latest",
  "TELEGRAM_CHAT_ID=telegram-chat-id:latest",
  "GMAIL_ADDRESS=gmail-address:latest",
  "GMAIL_APP_PASSWORD=gmail-app-password:latest",
  "DISPATCH_EMAIL_TO=dispatch-email-to:latest",
  "DISPATCH_PIN=dispatch-pin:latest"
) -join ","

gcloud run deploy tempest-api `
  --image $IMAGE `
  --region $REGION `
  --service-account $SA `
  --allow-unauthenticated `
  --min-instances 1 `
  --max-instances 1 `
  --memory 2Gi `
  --cpu 1 `
  --timeout 300 `
  --set-env-vars "DEMO_MODE=true,STATE_DB_PATH=/tmp/tempest.db" `
  --set-secrets $SECRETS

# Check it directly
$URL = gcloud run services describe tempest-api --region $REGION --format "value(status.url)"
Invoke-RestMethod "$URL/health"
```

`/health` should show `demo_mode: true` and `true` for every key you set.

## 4. Build and deploy the web app (Firebase Hosting)

The web app calls `/api/...` on its own origin (`VITE_API_BASE_URL` stays unset), and
`firebase.json` forwards those paths to `tempest-api`.

```powershell
Push-Location web
npm ci
npm run build          # writes web/dist
Pop-Location

firebase deploy --only hosting --project $PROJECT
```

Open the Hosting URL it prints, then check `https://<site>.web.app/health` and scrub the
timeline once (every replay timestep is served from fixtures).

Notes:
- Requests forwarded from Hosting to Cloud Run time out after 60 s. Advisory generation with
  retries and the Groq fallback normally takes well under that. If it ever times out, the API
  may still finish the request: refresh the queue before generating again.
- The Hosting rewrite needs the Cloud Run service in the same project and region as named in
  `firebase.json` (`tempest-api`, `asia-south1`).

## 5. Roll back

**API** (Cloud Run keeps every revision):

```powershell
gcloud run revisions list --service tempest-api --region $REGION
gcloud run services update-traffic tempest-api --region $REGION `
  --to-revisions "tempest-api-00007-abc=100"   # the revision to return to
```

A later `gcloud run deploy` sends traffic to the new revision again. Rolling back starts a fresh
instance, so the SQLite queue in `/tmp` starts empty.

**Web** (Firebase Hosting keeps every release): in the Firebase console, Hosting → release
history → the release to restore → Rollback. From the CLI, with the version id shown there:

```powershell
firebase hosting:clone "${PROJECT}:@VERSION_ID" "${PROJECT}:live"
```

## 6. After judging

```powershell
gcloud run services update tempest-api --region $REGION --min-instances 0
```

This lets the service scale to zero (no idle cost); the next request starts a new instance with
an empty queue.

## Local check before deploying

```powershell
api\.venv\Scripts\python -m pytest api\tests\test_smoke_demo.py   # the container's view: DEMO_MODE,
                                                                   # no keys, no raw/processed data
```
