# System Architecture Documentation

**Project:** Omani Arabic AI Therapy Assistant
**Version:** 4.0.0

## 1. Introduction

This document provides a detailed overview of the system architecture for the Omani Arabic AI Therapy Assistant. The system is designed as a real-time, voice-based conversational AI with a primary focus on user safety, cultural competency, and high availability. The architecture follows a decoupled, service-oriented design pattern, separating concerns to enhance maintainability, scalability, and testability.

## 2. System Design & Core Components

The application is comprised of five primary components that work in concert to deliver a seamless conversational experience.

### 2.1. Frontend Client
- **Technology:** Vanilla HTML, CSS, and JavaScript.
- **Role:** Provides the user interface (`new_interface.html`). Its responsibilities include:
    - Obtaining explicit user consent for the session.
    - Capturing microphone audio using the `MediaRecorder` API.
    - Establishing and maintaining a persistent WebSocket connection to the backend.
    - Transmitting raw `.webm` audio blobs to the server.
    - Receiving synthesized MP3 audio blobs from the server and playing them automatically.
    - Displaying status messages and conversation history.

### 2.2. Backend Server
- **Technology:** Python with **FastAPI**.
- **Role:** Acts as the central orchestrator of the entire system (`main.py`). Its responsibilities include:
    - Managing WebSocket connections and user sessions.
    - Receiving raw audio data and performing server-side audio format conversion using `pydub`.
    - Orchestrating the sequential calls to the Speech-to-Text, AI Core, and Text-to-Speech services.
    - Implementing performance logging to measure latency at each stage.
    - Hosting the frontend HTML file.

### 2.3. Speech Services
- **Technology:** **Google Cloud Platform (GCP)** APIs.
- **Role:** Handles all voice-to-text and text-to-voice conversions.
    - **Speech-to-Text (STT):** The `speech_v1` API is used for real-time transcription. It is configured for Omani Arabic (`ar-OM`) and `single_utterance` mode for optimal results with short voice clips.
    - **Text-to-Speech (TTS):** The `texttospeech_v1` API is used to synthesize the AI's final text response into a natural-sounding Omani Arabic female voice.

### 2.4. AI Core & Safety Layer
- **Technology:** Python (`ai_helper.py`), **OpenAI API**, and **Google Gemini API**.
- **Role:** This is the "brain" of the application, responsible for all intelligent decision-making, safety checks, and response generation. It is designed as a dual-model, multi-layered system for resilience and safety. (See Section 4 for details).

### 2.5. Configuration Management
- **Technology:** YAML (`prompt.yaml`).
- **Role:** The AI's entire persona, rules, therapeutic framework, cultural knowledge, and safety protocols are externalized into a single, human-readable YAML file. This decouples the AI's "knowledge" from the application's "logic," allowing for easy updates and review by non-technical stakeholders (e.g., clinicians).

## 3. End-to-End Data Flow

A single conversational turn follows this precise sequence of events:

```
  User         Frontend                Backend Server                  External APIs
   |              |                         |                              |
1. Speak -------->|                         |                              |
   |        2. Record Audio (.webm) ------->|                              |
   |              |                   3. Convert Audio (PCM)               |
   |              |                         |--------> 4. Transcribe (STT) ->| Google
   |              |                         |<------- 5. Get Transcript ----|
   |              |                         |                              |
   |              |                   6. Safety & AI Logic                 |
   |              |                         |--------> 7. Analyze (LLM) --->| OpenAI
   |              |                         |<------- 8. Get Response ----|  (or Gemini)
   |              |                         |                              |
   |              |                         |--------> 9. Synthesize (TTS) ->| Google
   |              |                         |<------- 10. Get Audio (MP3) --|
   |              |                         |                              |
   |<------ 11. Send Audio (MP3) <---------|                              |
12. Hear Response |                         |                              |
   |              |                         |                              |
```

1.  **User Speaks:** The user clicks the record button and speaks.
2.  **Audio Capture:** The frontend records the audio and sends the complete `.webm` blob over the WebSocket.
3.  **Audio Conversion:** The backend receives the blob and uses `pydub` to convert it to a 16-bit, 16kHz, single-channel PCM audio stream—the required format for the STT API.
4.  **Transcription:** The converted audio is sent to the Google STT API.
5.  **Text Received:** The server receives the final text transcript from Google.
6.  **Safety & AI Logic:** The transcript is passed to the `ai_helper` module for processing (see Section 4).
7.  **AI Analysis:** One or more calls are made to the LLMs (OpenAI or Gemini) for safety analysis and response generation.
8.  **AI Response Received:** The server receives the final, safe, and context-aware text response.
9.  **Speech Synthesis:** The text response is sent to the Google TTS API.
10. **Synthesized Audio Received:** The server receives the synthesized MP3 audio data.
11. **Audio Delivery:** The MP3 data is sent back to the client over the WebSocket.
12. **User Hears Response:** The browser plays the audio automatically.

## 4. Model Integration & Safety Architecture

The AI Core is not a single call to an LLM. It is a **three-stage funnel** designed to prioritize safety and efficiency.

### Stage 1: Keyword Risk Check (Fast Path)
- **Purpose:** To instantly catch obvious, high-risk user input without the latency or cost of an LLM call.
- **Mechanism:** The incoming transcript is scanned against a predefined list of high and medium-risk keywords configured in `prompt.yaml`.
- **Outcome:** If a match is found, the system immediately returns a predefined crisis script and **bypasses all subsequent stages**.

### Stage 2: Semantic Risk Check (Smart Path)
- **Purpose:** To understand the *intent* behind user input that doesn't contain obvious keywords (e.g., "I'm not okay" vs. "I want to die").
- **Mechanism:** If the keyword check passes, a **second, specialized API call** is made to `gpt-4o-mini`. It uses a minimal system prompt that instructs the model to act as a safety classifier and return only a single word: `SAFE`, `MEDIUM_RISK`, or `HIGH_RISK`. A strict 5-second timeout is enforced.
- **Outcome:** If the result is anything other than `SAFE`, the appropriate crisis script is returned, and the final stage is bypassed.

### Stage 3: Main AI Response (Therapist Path)
- **Purpose:** To generate a helpful, empathetic, and context-aware therapeutic response.
- **Mechanism:** Only if the transcript is cleared by both Stage 1 and Stage 2 does the system proceed. It constructs a full system prompt using the main template from `prompt.yaml`, adds the conversation history, and makes the primary API call.
- **Dual-Model Fallback Logic:**
    - The system first attempts to call the **primary model (OpenAI's GPT-4o)** with a strict 12-second timeout.
    - If this call fails for any reason (error, timeout, etc.), the `except` block is triggered.
    - The system then automatically makes a second attempt using the **secondary model (Google's Gemini)**.
    - If both models fail, a final error message is returned to the user.

This architecture ensures that safety is checked deterministically first, then semantically, before any creative text is generated, providing a robust "defense in depth" strategy. The dual-model fallback ensures high availability for the core response generation.