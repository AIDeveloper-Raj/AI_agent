import json
import os
from openai import OpenAI
from dotenv import load_dotenv

from backend.prompts import FINANCE_AGENT_SYSTEM_PROMPT, FINANCE_ADVISOR_SUMMARY_PROMPT
from backend.tools import get_finance_welcome, run_ar_billing, run_ar_phase1_tool

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CHAT_HISTORY = []


def _parse_select_client_message(message: str):
    """
    Card click values come in as:
    Select client::{client_id}::{client_name}
    """
    prefix = "select client::"
    raw = (message or "").strip()
    if raw.lower().startswith(prefix):
        rest = raw[len(prefix):]
        parts = rest.split("::", 1)
        if len(parts) == 2:
            client_id, client_name = parts[0].strip(), parts[1].strip()
            if client_id and client_name:
                return client_id, client_name
    return None, None


def _tool_result_to_final_payload(tool_result: dict) -> dict:
    artifacts = tool_result.get("artifacts", {}) or {}

    # If backend summary exists, let AI produce the advisor note from those facts only.
    if artifacts.get("summary"):
        try:
            advisor_ai = _generate_ai_advisor_summary(artifacts["summary"])
            artifacts["advisor"] = advisor_ai
        except Exception as e:
            print(f"Advisor summary generation failed: {e}")

    return {
        "intent": tool_result.get("intent", "AR_PHASE1"),
        "narration": tool_result.get("narration", "Done."),
        "next_question": {
            "text": tool_result.get("narration", "Please choose an option."),
            "options": tool_result.get("buttons", []) or []
        } if tool_result.get("buttons") else None,
        "artifacts": artifacts,
        "missing": {},
        "suggestions": {},
    }


def _extract_structured_request(raw_message: str) -> dict:
    """
    Ask the model for structured intent extraction only.
    The model should not answer conversationally here.
    It must return JSON only.
    """
    extraction_prompt = f"""
You are extracting structured finance intent for CEIPAL Finance Agent.

Return ONLY valid JSON.

Context:
- This is the Finance Agent page.
- In this phase, AR is implemented and AP is a placeholder.
- Users often type short, messy, incomplete prompts.

Rules:
- If the message is clearly about AR / invoice / billing for a client, return action=create_ar.
- If the message is clearly about AP / payable / vendor bill, return action=create_ap.
- If the message is ambiguous between AR and AP, return action=unknown.
- Do not force "create" by itself into AR.
- Extract the most likely client hint from the message when present.
- Correct obvious spacing / casing issues, but do not invent a completely different client name.
- Extract period only if clearly present.
- Do not invent values.
- Keep client_hint short and clean.

Examples:
- "Create invoice for Google" -> {{"action":"create_ar","client_hint":"Google","period":null}}
- "Do Google AR" -> {{"action":"create_ar","client_hint":"Google","period":null}}
- "AR for Starbucks" -> {{"action":"create_ar","client_hint":"Starbucks","period":null}}
- "Create for American Online" -> {{"action":"unknown","client_hint":"American Online","period":null}}
- "Create AP" -> {{"action":"create_ap","client_hint":null,"period":null}}

Return JSON in this exact shape:
{{
  "action": "create_ar" | "create_ap" | "unknown",
  "client_hint": string | null,
  "period": string | null
}}

User message:
{raw_message}
"""

    response = client.chat.completions.create(
        model="gpt-5.2",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You extract structured intent and return valid JSON only."
            },
            {
                "role": "user",
                "content": extraction_prompt
            }
        ],
        temperature=0.1,
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)

    return {
        "action": parsed.get("action", "unknown"),
        "client_hint": parsed.get("client_hint"),
        "period": parsed.get("period"),
    }


def _generate_ai_advisor_summary(summary_payload: dict) -> dict:
    """
    Uses backend-calculated finance facts and asks the model to write
    a concise advisor note without changing any numbers.
    """
    response = client.chat.completions.create(
        model="gpt-5.2",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": FINANCE_ADVISOR_SUMMARY_PROMPT + "\n\nReturn valid JSON only."
            },
            {
                "role": "user",
                "content": json.dumps(summary_payload)
            }
        ],
        temperature=0.4,
    )

    content = response.choices[0].message.content
    parsed = json.loads(content)

    return {
        "summary": parsed.get("summary", ""),
        "points": parsed.get("points", [])[:6],
    }


def handle_message(message: str):
    """
    Generator that yields NDJSON stream chunks for the frontend.
    """
    global CHAT_HISTORY

    try:
        raw_message = (message or "").strip()

        # -------------------------------------------------
        # 1) Empty message -> direct welcome response
        # -------------------------------------------------
        if not raw_message:
            welcome = get_finance_welcome()
            final_json = _tool_result_to_final_payload(welcome)
            yield json.dumps({"type": "result", "content": final_json}) + "\n"
            return

        # -------------------------------------------------
        # 2) Deterministic client-card selection path
        # -------------------------------------------------
        selected_client_id, selected_client_name = _parse_select_client_message(raw_message)
        if selected_client_id and selected_client_name:
            yield json.dumps({"type": "thought", "content": "Loading pending client details..."}) + "\n"

            tool_result = run_ar_phase1_tool(
                user_text=None,
                selected_client_id=selected_client_id,
                selected_client_name=selected_client_name,
                action=None,
                period=None,
            )

            final_json = _tool_result_to_final_payload(tool_result)

            CHAT_HISTORY.append({"role": "user", "content": raw_message})
            CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})

            yield json.dumps({"type": "result", "content": final_json}) + "\n"
            return

        # -------------------------------------------------
        # 3) Explicit card shortcuts
        # -------------------------------------------------
        if raw_message in ["Create AR", "Create AP"]:
            yield json.dumps({"type": "thought", "content": "Starting selected workflow..."}) + "\n"

            tool_result = run_ar_billing(
                client_name=raw_message,
                worker_name=None,
                period=None,
                hours_filter=None,
                mode=None,
            )

            final_json = _tool_result_to_final_payload(tool_result)

            CHAT_HISTORY.append({"role": "user", "content": raw_message})
            CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})

            yield json.dumps({"type": "result", "content": final_json}) + "\n"
            return

        # -------------------------------------------------
        # 4) Typed prompt path -> LLM structured extraction first
        # -------------------------------------------------
        yield json.dumps({"type": "thought", "content": "Understanding your request..."}) + "\n"

        structured = _extract_structured_request(raw_message)

        action = structured.get("action")
        client_hint = structured.get("client_hint")
        period = structured.get("period")

        # ---------------------------------------------
        # AP placeholder
        # ---------------------------------------------
        if action == "create_ap":
            tool_result = run_ar_billing(
                client_name="Create AP",
                worker_name=None,
                period=period,
                hours_filter=None,
                mode=None,
            )

            final_json = _tool_result_to_final_payload(tool_result)

            CHAT_HISTORY.append({"role": "user", "content": raw_message})
            CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})

            yield json.dumps({"type": "result", "content": final_json}) + "\n"
            return

        # ---------------------------------------------
        # AR flow
        # ---------------------------------------------
        if action == "create_ar":
            if client_hint:
                synthetic_prompt = f"Create invoice for {client_hint}"
            else:
                synthetic_prompt = "Create AR"

            tool_result = run_ar_billing(
                client_name=client_hint if client_hint else "Create AR",
                worker_name=None,
                period=period,
                hours_filter=None,
                mode=None,
            )

            final_json = _tool_result_to_final_payload(tool_result)

            CHAT_HISTORY.append({"role": "user", "content": raw_message})
            CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})

            yield json.dumps({"type": "result", "content": final_json}) + "\n"
            return

        # -------------------------------------------------
        # 5) Unknown intent handling
        # -------------------------------------------------
        if action == "unknown" and client_hint:
            fallback = {
                "intent": "ASK_AR_OR_AP",
                "narration": f'I found "{client_hint}", but I need to know whether you want to create AR or AP.',
                "buttons": [
                    {
                        "label": f"Create AR for {client_hint}",
                        "value": f"Create AR for {client_hint}",
                    },
                    {
                        "label": f"Create AP for {client_hint}",
                        "value": f"Create AP for {client_hint}",
                    },
                ],
                "artifacts": {},
                "next_question": None,
            }
        else:
            fallback = {
                "intent": "FINANCE_WELCOME",
                "narration": "Hi, what would you like to do today?",
                "buttons": [
                    {"label": "Create AR", "value": "Create AR"},
                    {"label": "Create AP", "value": "Create AP"},
                ],
                "artifacts": {},
                "next_question": None,
            }

        final_json = _tool_result_to_final_payload(fallback)

        CHAT_HISTORY.append({"role": "user", "content": raw_message})
        CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})

        yield json.dumps({"type": "result", "content": final_json}) + "\n"
        return

    except Exception as e:
        print(f"Error in orchestrator.handle_message: {e}")
        yield json.dumps({"type": "error", "content": str(e)}) + "\n"
        return
