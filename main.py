import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from pydub import AudioSegment
import io
from pathlib import Path
import uuid
from datetime import datetime
import uvicorn
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.cloud import speech_v1, texttospeech_v1
from google.oauth2 import service_account
from google.api_core.exceptions import GoogleAPIError
from dotenv import load_dotenv

from ai_helper import get_ai_response

def get_google_credentials():
    """
    Gets Google Cloud credentials. It checks for a JSON string in an environment
    variable first (for serverless environments like Vercel), and falls back to
    default discovery (local file path) if it's not found.
    """
    credentials_json_str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if credentials_json_str:
        logging.info("Found GOOGLE_APPLICATION_CREDENTIALS_JSON env var. Loading credentials from JSON string.")
        try:
            credentials_info = json.loads(credentials_json_str)
            return service_account.Credentials.from_service_account_info(credentials_info)
        except json.JSONDecodeError:
            logging.critical("Failed to parse GOOGLE_APPLICATION_CREDENTIALS_JSON. The string is not valid JSON.")
            return None
    else:
        logging.info("GOOGLE_APPLICATION_CREDENTIALS_JSON not found. Using default credential discovery.")
        # When no credentials are provided, the library uses the default
        # mechanism (like the GOOGLE_APPLICATION_CREDENTIALS file path env var).
        return None

def configure_logging():
    # ... (this function remains the same) ...
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    safety_logger = logging.getLogger("safety_audit")
    safety_logger.setLevel(logging.WARNING)
    if not safety_logger.handlers:
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file_path = log_dir / "safety_audit.log"
        handler = RotatingFileHandler(
            log_file_path, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        safety_logger.addHandler(handler)
        root_logger.info("Safety audit logger configured to write to %s", log_file_path)

load_dotenv()

# Application State and Lifespan
clients = {}
google_credentials = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global google_credentials
    configure_logging()

    google_credentials = get_google_credentials()

    logging.info("Application startup: Initializing async TTS client...")
    try:
        clients["tts"] = texttospeech_v1.TextToSpeechAsyncClient(credentials=google_credentials)
        logging.info("Async TTS client initialized successfully.")
    except Exception as e:
        logging.critical("Fatal: Failed to initialize Google Cloud TTS client on startup.", exc_info=True)
        raise RuntimeError("Could not initialize Google Cloud TTS client.") from e

    yield

    logging.info("Application shutdown: Cleaning up resources.")
    if "tts" in clients and hasattr(clients["tts"], "close"):
        await clients["tts"].close()
    logging.info("Async TTS client closed successfully.")

app = FastAPI(
    title="Omani Arabic Speech API",
    description="Real-time transcription and synthesis of Omani Arabic.",
    version="4.0.0",
    lifespan=lifespan,
)


templates = Jinja2Templates(directory="templates")
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logging.warning(f"Could not set up static files directory: {e}")

STREAMING_CONFIG = speech_v1.StreamingRecognitionConfig(
    config=speech_v1.RecognitionConfig(
        encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="ar-OM",
        enable_automatic_punctuation=True,
    ),
    single_utterance=True,
)
VOICE_PARAMS = texttospeech_v1.VoiceSelectionParams(
    language_code="ar-OM", ssml_gender=texttospeech_v1.SsmlVoiceGender.FEMALE
)
AUDIO_CONFIG = texttospeech_v1.AudioConfig(
    audio_encoding=texttospeech_v1.AudioEncoding.MP3
)

# HTTP Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/new", response_class=HTMLResponse)
async def new_interface(request: Request):
    return templates.TemplateResponse("new_interface.html", {"request": request})


#  Real-Time WebSocket Endpoint
@app.websocket("/ws/talk")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    logging.info(f"[{session_id}] WebSocket connection accepted from {websocket.client.host}")
    conversation_history = []

    try:
        while True:
            raw_audio_data = await websocket.receive_bytes()
            if not raw_audio_data:
                continue

            turn_start_time = datetime.utcnow()
            logging.info(f"[{session_id}] Received {len(raw_audio_data)} bytes of webm audio. Converting...")
            try:
                audio_segment = AudioSegment.from_file(io.BytesIO(raw_audio_data), format="webm")
                audio_segment = audio_segment.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                converted_audio_data = audio_segment.raw_data
                time_after_conversion = datetime.utcnow()
                logging.info(f"[{session_id}] PERF: Audio conversion took {(time_after_conversion - turn_start_time).total_seconds():.2f}s")
            except Exception as e:
                logging.error(f"[{session_id}] Failed to convert audio: {e}", exc_info=True)
                continue

            transcript = ""
            try:
                # Use the globally configured credentials for the on-demand STT client
                async with speech_v1.SpeechAsyncClient(credentials=google_credentials) as speech_client:
                    stt_requests = [
                        speech_v1.StreamingRecognizeRequest(streaming_config=STREAMING_CONFIG),
                        speech_v1.StreamingRecognizeRequest(audio_content=converted_audio_data),
                    ]
                    streaming_responses = await speech_client.streaming_recognize(requests=stt_requests)
                    async for response in streaming_responses:
                        if response.results and response.results[0].alternatives and response.results[0].is_final:
                            transcript = response.results[0].alternatives[0].transcript.strip()
                            if transcript:
                                break
            except GoogleAPIError as e:
                logging.error(f"[{session_id}] Google STT API Error: {e}", exc_info=True)
                continue
            except Exception as e:
                logging.error(f"[{session_id}] STT request failed: {e}", exc_info=True)
                continue

            time_after_stt = datetime.utcnow()
            logging.info(f"[{session_id}] PERF: STT took {(time_after_stt - time_after_conversion).total_seconds():.2f}s")

            if not transcript:
                logging.warning(f"[{session_id}] STT stream ended without a final transcript.")
                await websocket.send_json({"type": "status", "message": "لم ألتقط ذلك. الرجاء المحاولة مرة أخرى."})
                continue

            logging.info(f"[{session_id}] Final transcript: '{transcript}'")

            response_text = await get_ai_response(
                transcript=transcript,
                conversation_history=conversation_history,
                session_id=session_id,
                timestamp=datetime.utcnow().isoformat(),
            )
            time_after_llm = datetime.utcnow()
            logging.info(f"[{session_id}] PERF: AI (LLM) response took {(time_after_llm - time_after_stt).total_seconds():.2f}s")

            conversation_history.append({"role": "user", "content": transcript})
            conversation_history.append({"role": "assistant", "content": response_text})

            tts_client = clients["tts"]
            synthesis_input = texttospeech_v1.SynthesisInput(text=response_text)
            tts_response = await tts_client.synthesize_speech(
                input=synthesis_input, voice=VOICE_PARAMS, audio_config=AUDIO_CONFIG,
            )
            time_after_tts = datetime.utcnow()
            logging.info(f"[{session_id}] PERF: TTS synthesis took {(time_after_tts - time_after_llm).total_seconds():.2f}s")

            await websocket.send_bytes(tts_response.audio_content)
            total_turn_time = (datetime.utcnow() - turn_start_time).total_seconds()
            logging.info(f"[{session_id}] PERF: Full turn processed in {total_turn_time:.2f}s")

    except WebSocketDisconnect:
        logging.info(f"[{session_id}] Client {websocket.client.host} disconnected gracefully.")
    except Exception as e:
        logging.error(f"[{session_id}] An unexpected error occurred in the WebSocket loop: {e}", exc_info=True)
    finally:
        logging.info(f"[{session_id}] Closing WebSocket connection for {websocket.client.host}.")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8040"))
    logging.info(f"Starting server on http://localhost:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
