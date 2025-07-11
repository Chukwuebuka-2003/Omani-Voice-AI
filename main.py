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
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google.cloud import speech_v1
from google.cloud import texttospeech_v1
from google.cloud.exceptions import GoogleCloudError
from dotenv import load_dotenv

from ai_helper import get_ai_response

def configure_logging():
    """Sets up a file-based logger for safety-critical events."""
    # Get the root logger provided by Uvicorn
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # the dedicated safety logger
    safety_logger = logging.getLogger("safety_audit")
    safety_logger.setLevel(logging.WARNING)
    safety_logger.propagate = False

    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file_path = log_dir / "safety_audit.log"

    safety_logger.propagate = False

    # Only add a file handler if one doesn't already exist (prevents duplicates on reload)
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
# This dictionary will hold our async clients, initialized during app startup.
clients = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown events for the FastAPI application.
    Initializes logging and async clients for Google Cloud services.
    """
    configure_logging()  # Configure logging within the lifespan event
    logging.info("Application startup: Initializing async Google Cloud clients...")
    try:
        # only initialize the TTS client once, as it is stateless.
        # The STT client will be created on-demand for each request.
        clients["tts"] = texttospeech_v1.TextToSpeechAsyncClient()
        logging.info("Async TTS client initialized successfully.")
    except GoogleCloudError as e:
        logging.critical(
            "Fatal: Failed to initialize Google Cloud TTS client on startup.", exc_info=True
        )
        raise RuntimeError(
            "Could not initialize Google Cloud TTS client. Check credentials."
        ) from e

    yield

    logging.info("Application shutdown: Cleaning up resources.")
    if "tts" in clients and hasattr(clients["tts"], "close"):
        await clients["tts"].close()
    logging.info("Async TTS client closed successfully.")

app = FastAPI(
    title="Omani Arabic Speech API",
    description="Real-time transcription and synthesis of Omani Arabic.",
    version="4.0.0", # Final correct version. I started with version 1, 2 and 3 before i got this working version 4
    lifespan=lifespan,
)

# Set up templates and static files for FastHTML
templates = Jinja2Templates(directory="templates")
# Create a static files directory if needed
try:
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception as e:
    logging.warning(f"Could not set up static files directory: {e}")

#  Streaming and Voice Configuration
STREAMING_CONFIG = speech_v1.StreamingRecognitionConfig(
    config=speech_v1.RecognitionConfig(
        encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="ar-OM",
        enable_automatic_punctuation=True,
    ),
    single_utterance=True,
    interim_results=True,
)
VOICE_PARAMS = texttospeech_v1.VoiceSelectionParams(
    language_code="ar-OM", ssml_gender=texttospeech_v1.SsmlVoiceGender.FEMALE
)
AUDIO_CONFIG = texttospeech_v1.AudioConfig(
    audio_encoding=texttospeech_v1.AudioEncoding.MP3
)

#  HTTP Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Serves the main interface for the Omani Arabic transcription and synthesis application.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/new", response_class=HTMLResponse)
async def new_interface(request: Request):
    """
    Serves the new interface for the Omani Arabic transcription and synthesis application.
    """
    return templates.TemplateResponse("new_interface.html", {"request": request})

#  Real-Time WebSocket Endpoint
@app.websocket("/ws/talk")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    logging.info(f"[{session_id}] WebSocket connection accepted from {websocket.client.host}")
    conversation_history = []

    # This outer loop handles multiple conversational turns within the same WebSocket session
    try:
        while True:
            # Receive raw webm audio data from the client.
            raw_audio_data = await websocket.receive_bytes()
            if not raw_audio_data:
                logging.info(f"[{session_id}] Received empty message; waiting for next utterance.")
                continue

            # Latency Measurement Start
            turn_start_time = datetime.utcnow()

            #  Convert audio to the required format on the server.
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

            # Stream audio to the STT API using a context manager for robustness.
            transcript = ""
            try:
                # Use 'async with' to create a fully isolated client for each turn.
                async with speech_v1.SpeechAsyncClient() as speech_client:
                    # Create the request list directly.
                    stt_requests = [
                        speech_v1.StreamingRecognizeRequest(streaming_config=STREAMING_CONFIG),
                        speech_v1.StreamingRecognizeRequest(audio_content=converted_audio_data),
                    ]
                    streaming_responses = await speech_client.streaming_recognize(requests=stt_requests)

                    # Process the responses. With single_utterance=True, we expect one primary result.
                    async for response in streaming_responses:
                        if response.results and response.results[0].alternatives and response.results[0].is_final:
                            transcript = response.results[0].alternatives[0].transcript.strip()
                            # We can break after the first final result.
                            if transcript:
                                break
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

            #Get a response from the AI model.
            response_text = await get_ai_response(
                transcript=transcript,
                conversation_history=conversation_history,
                session_id=session_id,
                timestamp=datetime.utcnow().isoformat(),
            )
            time_after_llm = datetime.utcnow()
            logging.info(f"[{session_id}] PERF: AI (LLM) response took {(time_after_llm - time_after_stt).total_seconds():.2f}s")

            #Update conversation history.
            conversation_history.append({"role": "user", "content": transcript})
            conversation_history.append({"role": "assistant", "content": response_text})

            # Synthesize the AI's response to speech.
            tts_client = clients["tts"]
            synthesis_input = texttospeech_v1.SynthesisInput(text=response_text)
            tts_response = await tts_client.synthesize_speech(
                input=synthesis_input, voice=VOICE_PARAMS, audio_config=AUDIO_CONFIG,
            )
            time_after_tts = datetime.utcnow()
            logging.info(f"[{session_id}] PERF: TTS synthesis took {(time_after_tts - time_after_llm).total_seconds():.2f}s")

            #  Send the synthesized audio back to the client.
            await websocket.send_bytes(tts_response.audio_content)
            total_turn_time = (datetime.utcnow() - turn_start_time).total_seconds()
            logging.info(f"[{session_id}] PERF: Full turn processed in {total_turn_time:.2f}s")

    except WebSocketDisconnect:
        logging.info(f"[{session_id}] Client {websocket.client.host} disconnected gracefully.")
    except Exception as e:
        # Log any other exceptions that might occur during the conversation.
        logging.error(f"[{session_id}] An unexpected error occurred in the WebSocket loop: {e}", exc_info=True)
    finally:
        # This block ensures cleanup happens if the loop exits for any reason.
        logging.info(f"[{session_id}] Closing WebSocket connection for {websocket.client.host}.")
        # FastAPI's decorator handles the actual closing.


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8040")) # Default to 8001 as per usage
    logging.info(f"Starting server on http://localhost:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
