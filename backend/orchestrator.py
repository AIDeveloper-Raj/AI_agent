import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_json(name):
    with open(DATA_DIR / name, "r") as f:
        return json.load(f)


def handle_message(message: str):
    message_lower = message.lower()

    # Load data
    clients = load_json("clients.json")
    placements = load_json("placements.json")
    timesheets = load_json("timesheets.json")

    # Simple intent detection
    if "invoice" in message_lower:

        # Check if client mentioned
        for client in clients:
            if client["name"].lower() in message_lower:
                return {
                    "intent": "GENERATE_AR_DRAFT",
                    "narration": f"Client {client['name']} detected. Preparing billing cycle evaluation.",
                    "missing": {},
                    "suggestions": {},
                    "next_question": None,
                    "canvas_events": [
                        {"type": "progress", "title": "Resolving client", "status": "success"}
                    ],
                    "artifacts": {"invoice_drafts": [], "ap_drafts": []},
                    "next_actions": [],
                }

        # No client found — suggest top invoiceable clients
        invoiceable_clients = []

        for ts in timesheets:
            if ts["status"] == "APPROVED" and ts["invoiced_flag"] == 0:
                placement_id = ts["placement_id"]
                for p in placements:
                    if p["id"] == placement_id:
                        client_id = p["client_id"]
                        for c in clients:
                            if c["id"] == client_id:
                                invoiceable_clients.append(c["name"])

        top5 = list(set(invoiceable_clients))[:5]

        return {
            "intent": "ASK_CLARIFY_CLIENT",
            "narration": (
                "I need the client to generate the invoice. "
                "Here are clients with approved, not-yet-invoiced timesheets."
            ),
            "missing": {"client": "Client required"},
            "suggestions": {
                "client": [{"label": name, "value": name} for name in top5]
            },
            "next_question": {
                "text": "Which client should I invoice?",
                "options": [{"label": name, "value": name} for name in top5],
            },
            "canvas_events": [
                {"type": "progress", "title": "Understanding request", "status": "success"},
                {"type": "warning", "title": "Missing client", "status": "success"},
            ],
            "artifacts": {"invoice_drafts": [], "ap_drafts": []},
            "next_actions": [],
        }

    return {
        "intent": "UNKNOWN",
        "narration": "I didn't understand that request.",
        "missing": {},
        "suggestions": {},
        "next_question": None,
        "canvas_events": [],
        "artifacts": {"invoice_drafts": [], "ap_drafts": []},
        "next_actions": [],
    }