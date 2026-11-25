# VidPulse AI — v2 (merged, PRIVATE link version)

Merged 26 Nov 2026 from two sources:
- `../final/` — our own final version (English-only UI, 4-tab output, history,
  .TXT/.MD downloads, 30-min limit, real 400 vs 500 errors, /health).
- `../v2-gemini-updated/` — Gemini's updated code from the 26 Nov share chat
  (verbatim, saved untouched).

## What the merge took from Gemini's version
- Facebook /share/v/ redirect resolution (`resolve_redirect_url`).
- yt-dlp browser impersonation + Chrome 131 User-Agent headers.
- Wait loop while Gemini processes the uploaded file.
- Per-request API key (UI key box overrides the server key).
- Pinned requirements (fastapi 0.115.6, uvicorn 0.34.0, google-genai 1.5.0,
  yt-dlp[default,curl-cffi], requests 2.32.3, pydantic 2.10.4).
- Temperature 0.3 on generation.
- Backend serves the frontend at GET / (single-service deploy).

## What it deliberately did NOT take
- Gemini's `/api/process` + Markdown output — kept our `/api/extract` JSON
  contract (summary/transcript/urdu/repurpose/title) so the tabbed UI,
  history and downloads keep working.
- Gemini's Roman Urdu UI strings — this version is English-only per the
  product rule (Urdu stays only inside the AI output, as before).

## NEW: private-app gate
Set env var `VIDPULSE_ACCESS_CODE` on the host. Every extract request must
carry the same code (body field `access_code` or `X-Access-Code` header),
otherwise the backend returns 401. The frontend stores the code in
localStorage (API Settings) on the owner's device only. When the env var is
unset (local dev), the gate is open. The code itself lives only in a
chmod-600 file on the owner's machine — never in this repo.

## Deploy (Render free, recommended)
1. Push this folder to the `vidpulse-ai-backend` repo (root = this folder).
2. Render → New → Web Service → connect the repo. Runtime: Docker
   (Dockerfile at repo root, build context = repo root).
3. Environment: `GEMINI_API_KEY` = fresh key from Google AI Studio,
   `VIDPULSE_ACCESS_CODE` = the private access code.
4. Copy the service URL, e.g. `https://vidpulse-ai-backend.onrender.com`.
   Check `https://<service>/health` → `{"status":"ok"}`.
5. Open the frontend (GitHub Pages or the service root `/`), open
   API Settings, paste `<service-url>/api/extract` + the access code, Save.
   First request after idle takes ~60 s (free tier wakes up).

## Layout
- `index.html` — frontend (served by the backend at / and by GitHub Pages)
- `backend/main.py` — FastAPI backend
- `backend/requirements.txt` — pinned deps
- `Dockerfile` — repo-root Docker build (context = this folder)
