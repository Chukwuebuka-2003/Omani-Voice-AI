import os
import logging
from logging import getLogger
import yaml
from pathlib import Path
from openai import AsyncOpenAI
import google.generativeai as genai

from dotenv import load_dotenv

load_dotenv()

# Client Initialization

# Initialize OpenAI Client
try:
    openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    logging.info("OpenAI client initialized successfully.")
except Exception as e:
    logging.critical("Failed to initialize OpenAI client.", exc_info=True)
    openai_client = None

# Initialize Gemini Client
try:
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        gemini_model = genai.GenerativeModel('gemini-1.5-pro-latest')
        logging.info("Gemini client configured successfully.")
    else:
        gemini_model = None
        logging.warning("GEMINI_API_KEY not found. Gemini fallback will be disabled.")
except Exception as e:
    logging.critical("Failed to initialize Gemini client.", exc_info=True)
    gemini_model = None


#  Configuration Loading

def _load_all_configs() -> dict:
    """Loads all configurations from prompt.yaml with detailed logging."""
    try:
        prompt_path = Path(__file__).parent / "prompt.yaml"
        with open(prompt_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        semantic_check_config = data.get('semantic_safety_check', {})
        semantic_prompt = semantic_check_config.get('system_prompt')

        persona = data.get('persona', {})
        rules = data.get('rules_of_engagement', {})
        boundaries = data.get('boundaries_and_limitations', {})
        cultural = data.get('cultural_context_omani', {})
        therapeutic = data.get('therapeutic_framework_cbt', {})
        safety_protocol = data.get('safety_protocol_critical', {})
        prompt_pieces = [
            f"# Persona\nRole: {persona.get('role')}",
            f"Identity Declaration: {persona.get('identity_declaration')}",
            f"Language and Dialect: {persona.get('language_and_dialect', {}).get('primary')}",
            "Language Instructions:\n- " + "\n- ".join(persona.get('language_and_dialect', {}).get('instructions', [])),
            f"\n# Rules of Engagement\nPrimary Objective: {rules.get('primary_objective')}",
            "Communication Style:\n- " + "\n- ".join(rules.get('communication_style', [])),
            "Interaction Method:\n- " + "\n- ".join(rules.get('interaction_method', [])),
            f"\n# Boundaries and Limitations\nNo Direct Advice: {boundaries.get('no_direct_advice')}",
            f"No Medical Diagnosis: {boundaries.get('no_medical_diagnosis')}",
            f"No Personal Opinions: {boundaries.get('no_personal_opinions')}",
            f"Data Privacy Statement: {boundaries.get('data_privacy_statement')}",
            f"\n# Cultural Context: Omani\nIslamic Values:\n- " + "\n- ".join(cultural.get('islamic_values', [])),
            "Social Norms:\n- " + "\n- ".join(cultural.get('social_norms', [])),
            f"Communication Etiquette: {cultural.get('communication_etiquette')}",
            f"\n# Therapeutic Framework (based on CBT principles)\nActive Listening: {therapeutic.get('active_listening')}",
            f"Guided Discovery: {therapeutic.get('guided_discovery')}",
            "Cognitive Reframing:\n- " + "\n- ".join(therapeutic.get('cognitive_reframing', [])),
            f"Behavioral Activation: {therapeutic.get('behavioral_activation')}",
            f"Handling Nuance:\n- " + "\n- ".join(therapeutic.get('handling_nuance', [])),
            f"\n# CRITICAL SAFETY PROTOCOL (Overrides all other rules)\nTrigger Detection:\n- " + "\n- ".join(safety_protocol.get('trigger_detection', [])),
            "Immediate Action Plan:\n- " + "\n- ".join(safety_protocol.get('immediate_action_plan', [])),
            f"De-escalation Script (Use this exact text):\n{safety_protocol.get('de_escalation_script')}"
        ]
        formatted_prompt = "\n".join(prompt_pieces)

        return {
            "system_prompt_template": formatted_prompt,
            "risk_analysis_config": data.get('risk_analysis_config', {}),
            "semantic_safety_check_prompt": semantic_prompt
        }
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to load or parse prompt.yaml: {e}", exc_info=True)
        return { "system_prompt_template": "You are a helpful assistant.", "risk_analysis_config": {}, "semantic_safety_check_prompt": None }

CONFIG = _load_all_configs()
safety_logger = getLogger("safety_audit")

# Safety Layer & Main Response Logic

def keyword_risk_check(transcript: str, session_id: str) -> dict | None:
    transcript_lower = transcript.lower()
    risk_config = CONFIG.get("risk_analysis_config", {})
    high_risk_config = risk_config.get('high_risk', {})
    for keyword in high_risk_config.get('keywords', []):
        if keyword.lower() in transcript_lower:
            safety_logger.warning(f"[{session_id}] KEYWORD CHECK: HIGH RISK DETECTED! Keyword: '{keyword}'. Transcript: '{transcript}'")
            return {'level': 'HIGH', 'data': high_risk_config.get('response_script')}
    medium_risk_config = risk_config.get('medium_risk', {})
    for keyword in medium_risk_config.get('keywords', []):
        if keyword.lower() in transcript_lower:
            safety_logger.warning(f"[{session_id}] KEYWORD CHECK: MEDIUM RISK DETECTED! Keyword: '{keyword}'. Transcript: '{transcript}'")
            return {'level': 'MEDIUM', 'data': medium_risk_config.get('response_script')}
    low_risk_config = risk_config.get('low_risk', {})
    for keyword in low_risk_config.get('keywords', []):
        if keyword.lower() in transcript_lower:
            logging.info(f"[{session_id}] KEYWORD CHECK: LOW RISK DETECTED. Keyword: '{keyword}'.")
            return {'level': 'LOW', 'data': low_risk_config.get('prompt_injection')}
    return None

async def semantic_risk_check(transcript: str, session_id: str) -> str:
    system_prompt = CONFIG.get("semantic_safety_check_prompt")
    if not system_prompt or not openai_client:
        logging.error(f"[{session_id}] Semantic safety check misconfigured. Defaulting to SAFE.")
        return "SAFE"
    try:
        logging.info(f"[{session_id}] SEMANTIC CHECK: Performing safety analysis on transcript...")
        chat_completion = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript}
            ],
            temperature=0, max_tokens=5, timeout=5.0)
        result = chat_completion.choices[0].message.content.strip().upper()
        logging.info(f"[{session_id}] SEMANTIC CHECK: Result: {result}")
        if result in ["HIGH_RISK", "MEDIUM_RISK", "SAFE"]:
            return result
        else:
            safety_logger.warning(f"[{session_id}] SEMANTIC CHECK: LLM returned invalid classification: '{result}'. Defaulting to MEDIUM_RISK.")
            return "MEDIUM_RISK"
    except Exception as e:
        logging.error(f"[{session_id}] SEMANTIC CHECK: An error occurred: {e}", exc_info=True)
        return "MEDIUM_RISK"

async def get_ai_response(
    transcript: str, conversation_history: list, session_id: str, timestamp: str,
) -> str:
    # First-Pass: Keyword Check
    keyword_assessment = keyword_risk_check(transcript, session_id)
    if keyword_assessment and keyword_assessment['level'] in ['HIGH', 'MEDIUM']:
        return keyword_assessment['data']

    # Second-Pass: Semantic Check
    semantic_risk_level = await semantic_risk_check(transcript, session_id)
    if semantic_risk_level == 'HIGH_RISK':
        safety_logger.warning(f"[{session_id}] SEMANTIC CHECK: HIGH RISK DETECTED! Transcript: '{transcript}'")
        return CONFIG.get("risk_analysis_config", {}).get('high_risk', {}).get('response_script')
    if semantic_risk_level == 'MEDIUM_RISK':
        safety_logger.warning(f"[{session_id}] SEMANTIC CHECK: MEDIUM RISK DETECTED! Transcript: '{transcript}'")
        return CONFIG.get("risk_analysis_config", {}).get('medium_risk', {}).get('response_script')

    # Construct Main Prompt
    system_prompt_template = CONFIG.get("system_prompt_template", "You are a helpful assistant.")
    dynamic_system_prompt = system_prompt_template
    if keyword_assessment and keyword_assessment['level'] == 'LOW':
        dynamic_system_prompt += f"\n\n# Special Instruction for This Turn\n{keyword_assessment['data']}"
    dynamic_system_prompt += f"\n\n# Session Context\n- **Session ID:** {session_id}\n- **Timestamp (UTC):** {timestamp}"

    messages = [{"role": "system", "content": dynamic_system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": transcript})

    # Try Primary Model (OpenAI)
    if openai_client:
        try:
            logging.info(f"[{session_id}] MAIN AI: Attempting primary model (GPT-4o)...")
            chat_completion = await openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, temperature=0.7, max_tokens=150, top_p=1.0, frequency_penalty=0.5, presence_penalty=0.0, timeout=12.0)
            response_text = chat_completion.choices[0].message.content.strip()
            logging.info(f"[{session_id}] MAIN AI: Received response from primary model.")
            return response_text
        except Exception as e:
            logging.error(f"[{session_id}] MAIN AI: Primary model (GPT-4o) failed: {e}", exc_info=True)

    # Fallback to Secondary Model (Gemini)
    if gemini_model:
        try:
            logging.info(f"[{session_id}] MAIN AI: Attempting secondary model (Gemini)...")
            # Gemini has a different API structure for conversation history
            gemini_history = []
            for turn in conversation_history:
                # Map roles: 'assistant' -> 'model'
                role = "model" if turn["role"] == "assistant" else "user"
                gemini_history.append({"role": role, "parts": [turn["content"]]})

            chat_session = gemini_model.start_chat(history=gemini_history)
            response = await chat_session.send_message_async(transcript)

            response_text = response.text.strip()
            logging.info(f"[{session_id}] MAIN AI: Received response from secondary model.")
            return response_text
        except Exception as e:
            logging.error(f"[{session_id}] MAIN AI: Secondary model (Gemini) also failed: {e}", exc_info=True)

    # If both models fail
    return "عفواً، أواجه صعوبة في الاتصال بخدمات الذكاء الاصطناعي حاليًا. الرجاء المحاولة مرة أخرى لاحقًا."
