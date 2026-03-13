from backend.db import (
    execute_universal_ar_billing,
    get_finance_welcome_payload,
    run_ar_phase1,
)


# ---------------------------------------------------------
# PHASE 1 WELCOME
# ---------------------------------------------------------
def get_finance_welcome():
    """
    Returns the initial greeting and the two starting cards:
    [Create AR] [Create AP]
    """
    payload = get_finance_welcome_payload()

    return {
        "intent": "FINANCE_WELCOME",
        "narration": payload.get("message", "Hi, what would you like to do today?"),
        "buttons": payload.get("action_cards", []),
        "artifacts": {},
        "next_question": None,
    }


# ---------------------------------------------------------
# MAIN PHASE 1 AR TOOL
# ---------------------------------------------------------
def run_ar_billing(
    client_name=None,
    worker_name=None,
    period=None,
    hours_filter=None,
    mode=None
):
    """
    Compatibility wrapper for the current tool contract.

    March 12 Phase 1 only:
    - Create AR entry
    - client resolution
    - pending-items table display
    """

    result = execute_universal_ar_billing(
        client_name=client_name,
        worker_name=worker_name,
        period=period,
        hours_filter=hours_filter,
        mode=mode,
    )

    phase1_status = result.get("phase1_status")
    message = result.get("error")
    ambiguity_options = result.get("ambiguity_options", [])
    summary = result.get("summary")
    advisor = result.get("advisor")
    data_views = result.get("data_views", [])

    # Safety fallback — ensure every state has a meaningful narration
    if not message:
        if phase1_status == "show_pending_table":
            message = "Pending invoice items are ready for review."
        elif phase1_status == "choose_client":
            message = "Please select one client to continue."
        elif phase1_status == "ap_placeholder":
            message = "AP flow is not part of this phase yet. Please choose Create AR to continue."
        elif phase1_status == "no_pending_clients":
            message = "There are no clients with approved timesheets pending invoicing right now."
        elif phase1_status == "no_match":
            message = "I couldn't find a matching client. Please try another client name."
        elif phase1_status == "empty":
            message = "I found the client, but there are no approved timesheets pending invoicing right now."
        elif phase1_status == "error":
            message = "I ran into an issue while loading the pending invoice details."
        else:
            message = "Done."

    response = {
        "intent": "AR_PHASE1",
        "narration": message,
        "buttons": [],
        "artifacts": {},
        "next_question": None,
    }

    # 1) Client choice state
    if phase1_status == "choose_client":
        response["intent"] = "ASK_CLIENT_SELECTION"
        response["buttons"] = ambiguity_options
        return response

    # 2) Canvas table state
    if phase1_status == "show_pending_table" and data_views:
        response["intent"] = "SHOW_PENDING_ITEMS"
        response["artifacts"] = {
            "summary": summary,
            "advisor": advisor,
            "data_views": data_views,
        }
        return response

    # 3) AP placeholder
    if phase1_status == "ap_placeholder":
        response["intent"] = "AP_PLACEHOLDER"
        return response

    # 4) Info / empty / error states
    if phase1_status in ["empty", "no_match", "no_pending_clients", "error"]:
        response["intent"] = "AR_PHASE1_INFO"
        return response

    return response


# ---------------------------------------------------------
# OPTIONAL DIRECT TOOL FOR FUTURE CLEANUP
# ---------------------------------------------------------
def run_ar_phase1_tool(
    user_text=None,
    selected_client_id=None,
    selected_client_name=None,
    action=None,
    period=None,
):
    """
    Deterministic Phase 1 tool.
    Use this for:
    - welcome
    - Create AR / Create AP
    - selected client card click
    - typed prompt fallback if needed
    """
    result = run_ar_phase1(
        user_text=user_text,
        selected_client_id=selected_client_id,
        selected_client_name=selected_client_name,
        action=action,
        period=period,
    )

    phase1_status = result.get("phase1_status")
    message = result.get("message")

    if not message:
        if phase1_status == "show_pending_table":
            message = "Pending invoice items are ready for review."
        elif phase1_status == "choose_client":
            message = "Please select one client to continue."
        elif phase1_status == "ap_placeholder":
            message = "AP flow is not part of this phase yet. Please choose Create AR to continue."
        elif phase1_status == "no_pending_clients":
            message = "There are no clients with approved timesheets pending invoicing right now."
        elif phase1_status == "no_match":
            message = "I couldn't find a matching client. Please try another client name."
        elif phase1_status == "empty":
            message = "I found the client, but there are no approved timesheets pending invoicing right now."
        elif phase1_status == "error":
            message = "I ran into an issue while loading the pending invoice details."
        else:
            message = "Done."

    response = {
        "intent": "AR_PHASE1",
        "narration": message,
        "buttons": result.get("ambiguity_options", []) or result.get("action_cards", []),
        "artifacts": {},
        "next_question": None,
    }

    if phase1_status == "show_pending_table":
        response["intent"] = "SHOW_PENDING_ITEMS"
        response["artifacts"] = {
            "summary": result.get("summary"),
            "advisor": result.get("advisor"),
            "data_views": result.get("data_views", []),
        }
        response["buttons"] = []

    elif phase1_status == "choose_client":
        response["intent"] = "ASK_CLIENT_SELECTION"

    elif phase1_status == "welcome":
        response["intent"] = "FINANCE_WELCOME"

    elif phase1_status == "ap_placeholder":
        response["intent"] = "AP_PLACEHOLDER"

    elif phase1_status in ["empty", "no_match", "no_pending_clients", "error"]:
        response["intent"] = "AR_PHASE1_INFO"

    return response
