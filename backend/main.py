import os
import json
import tempfile
import time
import uuid
import glob
import requests
import yt_dlp
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI(title="VidPulse AI Backend")

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini API Client key: server env var, or a per-request key from the UI.
# (Per-request key wins when supplied.)

# Private-app gate: when VIDPULSE_ACCESS_CODE is set, every extract request
# must carry the same code (body field "access_code" or header
# "X-Access-Code"). When it is unset (local dev), the gate is open.
ACCESS_CODE = os.environ.get("VIDPULSE_ACCESS_CODE", "").strip()

# Videos longer than this are rejected (free-tier hosting + Gemini audio limits)
MAX_DURATION_SECONDS = 1800  # 30 minutes


class VideoRequest(BaseModel):
    url: str
    language: str = "English + Urdu"
    detail: str = "Detailed"
    api_key: str | None = None
    access_code: str | None = None


def _check_access(req: VideoRequest, header_code: str | None) -> None:
    if not ACCESS_CODE:
        return
    supplied = (req.access_code or "").strip() or (header_code or "").strip()
    if supplied != ACCESS_CODE:
        raise HTTPException(status_code=401, detail="Wrong access code.")


def resolve_redirect_url(url: str) -> str:
    """Resolve Facebook /share/v/ and other short links to the real video URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        resp = requests.head(url, allow_redirects=True, headers=headers, timeout=10)
        return resp.url
    except Exception:
        return url


@app.get("/", response_class=HTMLResponse)
def home():
    # Single-service deploy: serve the frontend when it sits next to main.py.
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(here):
        with open(here, "r", encoding="utf-8") as f:
            return f.read()
    return {"status": "VidPulse AI Backend is Running!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/extract")
async def extract_video(req: VideoRequest, x_access_code: str | None = Header(default=None)):
    _check_access(req, x_access_code)

    active_key = (req.api_key or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not active_key:
        raise HTTPException(
            status_code=400,
            detail="API key missing. Set GEMINI_API_KEY on the server or paste your key in the app settings.",
        )

    clean_url = resolve_redirect_url(req.url.strip())
    job_id = str(uuid.uuid4())

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Download audio using yt-dlp (with browser impersonation)
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(tmpdir, "raw_audio.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "64",
                }],
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "extractor_args": {"generic": ["impersonate"]},
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=True)
                video_title = info.get("title", "Social Video")
                description = info.get("description", "")
                duration = info.get("duration")

            if duration and duration > MAX_DURATION_SECONDS:
                raise HTTPException(
                    status_code=400,
                    detail="Video is longer than 30 minutes. Please use a shorter video.",
                )

            # Locate downloaded mp3
            downloaded_file = os.path.join(tmpdir, "raw_audio.mp3")
            if not os.path.exists(downloaded_file):
                raise HTTPException(status_code=400, detail="Audio download failed. Video might be private.")

            # 2. Upload audio to Gemini File API
            client = genai.Client(api_key=active_key)
            uploaded_audio = client.files.upload(file=downloaded_file)
            # Wait until Gemini finishes processing the file
            while uploaded_audio.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_audio = client.files.get(name=uploaded_audio.name)

            # 3. Generate Structured JSON Output
            prompt = f"""
            Analyze this video audio carefully. Video Title: "{video_title}". Caption: "{description}".
            Detail Level: {req.detail}. Language preference: {req.language}.

            Return ONLY a valid JSON object with these exact 4 keys:
            1. "summary": A structured executive summary with main takeaways and numbered key points.
            2. "transcript": Full word-for-word spoken transcript with approximate timestamps [00:00].
            3. "urdu": Complete, natural Urdu translation of the summary and main points.
            4. "repurpose": Ready-to-post viral caption with hashtags for TikTok/Instagram and a short 30-second script hook.
            """

            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[uploaded_audio, prompt],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            # Cleanup remote file
            try:
                client.files.delete(name=uploaded_audio.name)
            except Exception:
                pass

            try:
                result = json.loads(response.text)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=500,
                    detail="AI returned an invalid response. Please try again.",
                )

            result["title"] = video_title
            return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
