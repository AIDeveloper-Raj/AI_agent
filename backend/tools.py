import json
from pathlib import Path
from backend.db import get_unbilled_ap_for_vendor, get_worker_info, get_worker_list

# We will build this new function in db.py in our next step!
from backend.db import execute_universal_ar_billing 

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _load(table):
    file_path = DATA_DIR / f"{table}.json"
    if not file_path.exists(): return []
    with open(file_path, "r") as f: return json.load(f)

# --- NEW UNIVERSAL AR ENDPOINT ---
def run_ar_billing(client_name: str = None, worker_name: str = None, period: str = None, hours_filter: str = None, mode: str = None):
    """
    The Master AR Billing endpoint. 
    Passes intent directly to the Python backend to handle all CEIPAL API calls and default logic.
    """
    return execute_universal_ar_billing(client_name, worker_name, period, hours_filter, mode)

# --- LEGACY AP ENDPOINT (Untouched for now) ---
def draft_ap_bill(vendor_name: str, worker_name: str = None):
    # Keeping your existing logic here until we rebuild AP
    if worker_name == "ALL_INDIVIDUAL":
        # ... your existing batching logic ...
        return {"error": "Legacy AP logic placeholder"}
        
    result = get_unbilled_ap_for_vendor(vendor_name, worker_name)
    return result if result else {"error": "No unbilled AP data found."}

def query_database(query_type: str, target_name: str = None):
    if query_type == "worker_info" and target_name:
        return get_worker_info(target_name)
    elif query_type == "worker_list" and target_name:
        return get_worker_list(target_name)
    return {"error": "Invalid query type or missing target."}

# ==========================================
# OPENAI TOOL SCHEMAS
# ==========================================
FINANCE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_ar_billing",
            "description": "Master endpoint for AR invoice generation. DO NOT guess defaults. If the user does not specify a field, leave it null.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string", "description": "Target client company name. If user doesn't specify, leave null."},
                    "worker_name": {"type": "string", "description": "Specific worker name. Pass null to let backend resolve all active workers."},
                    "period": {"type": "string", "description": "Billing period. Pass null to use all approved unbilled timesheets."},
                    "hours_filter": {"type": "string", "enum": ["ST", "OT", "DT"], "description": "Filter by pay code. Pass null to include all."},
                    "mode": {"type": "string", "enum": ["Individual", "Consolidated"], "description": "Leave null unless user explicitly specifies."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Use this to answer questions about worker employment types, pending hours, or to fetch lists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string", "enum": ["worker_info", "worker_list"]},
                    "target_name": {"type": "string", "description": "Worker name OR Emp Type (W-2, 1099)"}
                },
                "required": ["query_type", "target_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draft_ap_bill",
            "description": "Generates an AP bill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": "string"}, 
                    "worker_name": {"type": "string"}
                },
                "required": ["vendor_name"]
            }
        }
    }
]