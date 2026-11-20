import os
import json
import tempfile
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai

app = FastAPI(title="VidPulse AI Backend")

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini API Client (Set GEMINI_API_KEY in your hosting environment variables)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Videos longer than this are rejected (Render free tier + Gemini audio limits)
MAX_DURATION_SECONDS = 1800  # 30 minutes


class VideoRequest(BaseModel):
    url: str
    language: str = "English + Urdu"
    detail: str = "Detailed"


@app.get("/")
def home():
    return {"status": "VidPulse AI Backend is Running!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/extract")
async def extract_video(req: VideoRequest):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Download audio using yt-dlp
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
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(req.url, download=True)
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
            uploaded_audio = client.files.upload(file=downloaded_file)

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
                model="gemini-2.5-flash",
                contents=[uploaded_audio, prompt],
                config={"response_mime_type": "application/json"}
            )

            # Cleanup remote file
            client.files.delete(name=uploaded_audio.name)

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
