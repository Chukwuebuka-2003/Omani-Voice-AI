# Omani Arabic AI Therapy Assistant

**Version: 4.0.0**

This project is a sophisticated, real-time, voice-based conversational AI designed to act as a compassionate and culturally-aware listening assistant for speakers of the Omani Arabic dialect. It leverages a state-of-the-art tech stack to provide a safe, responsive, and empathetic user experience, with a primary focus on user safety and ethical AI principles.

The application is architected to be production-ready, featuring a dual-model AI core for resilience, a multi-layered safety system for proactive risk detection, and a prompt-driven knowledge base for deep cultural and therapeutic competency.

---

## Core Features

### Therapeutic & Language Capabilities
- **Dialect Authenticity:** The AI is specifically instructed to communicate in modern, conversational Omani Arabic (`ar-OM`) from Google Cloud, ensuring a natural and relatable interaction.
- **Cultural Sensitivity:** A deep understanding of Omani and Gulf cultural norms, including family dynamics, social sensitivities, and Islamic values, is integrated directly into the AI's persona.
- **CBT Framework:** The AI's conversational strategy is based on principles of Cognitive Behavioral Therapy (CBT), such as active listening, guided discovery, and cognitive reframing, to help users explore their thoughts and feelings constructively.
- **Emotional Intelligence:** The system can detect subtle emotional cues and contradictions in user statements, allowing it to respond with greater nuance and empathy.
- **Crisis Intervention:** Robust protocols are in place to detect and safely handle conversations that involve a risk of harm.

### Technical Excellence & Safety
- **Real-Time Voice Interface:** A low-latency web interface allows users to speak naturally and receive synthesized voice responses in near real-time.
- **Dual-Model Resilience:** The system uses **GPT-4o** as its primary conversational model and automatically falls back to **Google's Gemini** in case of an outage or error, ensuring high availability.
- **Multi-Layered Safety System:**
    1.  **Keyword Detection:** A rapid, deterministic check for high-risk keywords.
    2.  **Semantic Analysis:** A second-pass LLM-based check to understand the *intent* behind the user's words, catching non-obvious risks.
    3.  **LLM Guardrails:** The main AI prompt contains its own set of safety instructions as a final layer of protection.
- **Latency Enforcement:** The system actively enforces a **<20-second** turn latency target by using aggressive timeouts on the primary model, triggering a fallback if it's too slow.
- **Secure Logging:** Standard application logs are separated from a dedicated, file-based **safety audit trail** (`logs/safety_audit.log`) for secure review of critical incidents.
- **Explicit User Consent:** The user interface includes a mandatory consent modal that ensures users understand and agree to the terms of use and data processing before a session can begin.

---

## System Architecture

The application follows a modern, decoupled architecture designed for scalability and maintainability.

### Components
- **Frontend:** A single-page web application built with HTML, CSS, and vanilla JavaScript. It uses the `MediaRecorder` API to capture audio and a WebSocket to stream it to the backend.
- **Backend:** A high-performance asynchronous web server built with **FastAPI** (Python). It manages WebSocket connections, orchestrates the various AI services, and handles all business logic.
- **Speech Pipeline (Google Cloud):**
    - **Speech-to-Text (STT):** Google's `speech_v1` API is used for real-time transcription of Omani Arabic.
    - **Text-to-Speech (TTS):** Google's `texttospeech_v1` API synthesizes the AI's responses into a natural-sounding Omani Arabic female voice.
- **AI Core (Dual-Model):**
    - **Primary Model:** OpenAI's `gpt-4o-mini` is used for the main conversational and semantic analysis tasks.
    - **Secondary Model (Fallback):** Google's `gemini-1.5-pro` is used to ensure high availability.
- **Configuration:** The AI's entire personality, rules, and knowledge base are externalized into a `prompt.yaml` file, allowing for easy updates without changing the application code.

### Data Flow of a Conversation Turn
1.  **Consent:** User agrees to the terms in the consent modal.
2.  **Audio Capture:** The browser records the user's speech as a `.webm` audio blob.
3.  **WebSocket Transmission:** The audio blob is sent to the FastAPI backend over a persistent WebSocket connection.
4.  **Audio Conversion:** The server uses `pydub` to convert the received audio into the required `LINEAR16 / 16kHz` format.
5.  **Transcription:** The converted audio is streamed to the Google STT API, which returns a text transcript.
6.  **Safety Check (Pass 1 - Keyword):** The transcript is scanned for high-risk keywords. If a match is found, the crisis script is returned immediately, and the flow stops.
7.  **Safety Check (Pass 2 - Semantic):** If no keywords are found, a request is made to GPT-4o with a specialized prompt to classify the transcript's intent (`SAFE`, `MEDIUM_RISK`, `HIGH_RISK`). If the risk is high, the appropriate script is returned, and the flow stops.
8.  **Main AI Response:** If the transcript is deemed safe, the full conversation history and the system prompt are sent to the primary model (GPT-4o) to generate the therapeutic response.
9.  **Fallback Logic:** If the call to GPT-4o fails or times out (after 12 seconds), the system automatically makes a second attempt using the Gemini model.
10. **Speech Synthesis:** The final text response from the AI is sent to the Google TTS API to be converted into an MP3 audio stream.
11. **Response Delivery:** The synthesized MP3 audio is sent back to the client over the WebSocket and played automatically.

---

The FastAPI Backend Server was deployed on Huggingface Docker space

## Setup and Installation

### Prerequisites
- Python 3.10+
- `pip` for package management
- `ffmpeg`: The `pydub` library requires `ffmpeg` to be installed on the system for audio conversion.
  - **On Fedora/CentOS:** `sudo dnf install ffmpeg`
  - **On Debian/Ubuntu:** `sudo apt-get install ffmpeg`
  - **On macOS (with Homebrew):** `brew install ffmpeg`

### Installation Steps
1.  **Clone the Repository:**
    ```bash
    git clone github.com/Chukwuebuka-2003/Omani-Voice-AI
    cd Omani-Voice-Ai
    ```
2.  **Create a Virtual Environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate
    # On Windows, use: venv\Scripts\activate
    ```
3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure API Keys:**
    - Create a file named `.env` in the `Omani-Voice-AI/` directory.
    - Add your API keys to this file. The file should **not** be committed to version control.
    ```env
    # oman/.env
    OPENAI_API_KEY="your_openai_api_key_here"
    GEMINI_API_KEY="your_google_gemini_api_key_here"
    # Ensure your Google Cloud credentials for STT/TTS are set up via
    # environment variables or a service account JSON file.
    # export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/credentials.json"
    ```

---

## Running the Application

To run the server in development mode with live reloading:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8030
```
- The `--reload` flag automatically restarts the server when code changes are detected.
- The `--host 0.0.0.0` makes the server accessible on your local network.

Once the server is running, open a web browser and navigate to:
**`http://localhost:8030/new`**

---

## Project Structure

```
oman/
│
├── .env                  # (To be created) Stores secret API keys
├── main.py               # Main FastAPI application, WebSocket logic, STT/TTS pipeline
├── ai_helper.py          # All AI logic: safety checks, dual-model orchestration
├── prompt.yaml           # The "brain" of the AI: all system prompts and configurations
├── requirements.txt      # Python dependencies
│
├── logs/
│   └── safety_audit.log  # (Auto-generated) Secure log for high-risk safety events
│
└── templates/
    └── new_interface.html    # The frontend web application UI and JavaScript
