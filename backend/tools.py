import json
from pathlib import Path
from backend.db import get_unbilled_ar_for_client, get_unbilled_ap_for_vendor

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _load(table):
    file_path = DATA_DIR / f"{table}.json"
    if not file_path.exists():
        return []
    with open(file_path, "r") as f:
        return json.load(f)

def scan_pending_billing():
    """Scans the DB and returns clients/vendors and their specific workers with unbilled timesheets."""
    timesheets = _load("timesheets")
    placements = _load("placements")
    clients = _load("clients")
    vendors = _load("vendors")
    workers_details = _load("workers_details")
    workers = _load("workers")

    pending_ar = {}
    pending_ap = {}

    for ts in timesheets:
        if ts["status"] != "APPROVED": continue
        p = next((x for x in placements if x["placement_id"] == ts["placement_id"]), None)
        if not p: continue

        w = next((x for x in workers if x["worker_id"] == p["worker_id"]), None)
        worker_name = f"{w['first_name']} {w['last_name']}" if w else "Unknown"

        # Check AR
        if ts["ar_invoiced_flag"] == 0:
            c = next((x for x in clients if x["client_id"] == p["client_id"]), None)
            if c:
                if c["name"] not in pending_ar: pending_ar[c["name"]] = []
                if worker_name not in pending_ar[c["name"]]: pending_ar[c["name"]].append(worker_name)

        # Check AP
        if ts["ap_invoiced_flag"] == 0:
            wd = next((x for x in workers_details if x["worker_id"] == p["worker_id"]), None)
            if wd and wd["employment_type"] in ["1099", "C2C"]:
                v = next((x for x in vendors if x["vendor_id"] == p["vendor_id"]), None)
                if v:
                    if v["name"] not in pending_ap: pending_ap[v["name"]] = []
                    if worker_name not in pending_ap[v["name"]]: pending_ap[v["name"]].append(worker_name)

    return {
        "clients_needing_invoices": pending_ar,  # e.g. {"Google": ["Rajesh Jonnalagadda", "John Doe"]}
        "vendors_needing_bills": pending_ap
    }

def draft_ar_invoice(client_name: str, worker_name: str = None):
    """Generates an AR invoice for a client, optionally filtered to a single worker."""
    result = get_unbilled_ar_for_client(client_name, worker_name=worker_name)
    return result if result else {"error": "No unbilled AR data found."}

def draft_ap_bill(vendor_name: str, worker_name: str = None):
    """Generates an AP bill for a vendor, optionally filtered to a single worker."""
    result = get_unbilled_ap_for_vendor(vendor_name, worker_name=worker_name)
    return result if result else {"error": "No unbilled AP data found."}


# ==========================================
# OPENAI TOOL SCHEMAS
# ==========================================
FINANCE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scan_pending_billing",
            "description": "Scans the database to find which clients/vendors need billing, and WHICH specific workers have pending timesheets under them."
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draft_ar_invoice",
            "description": "Generates an AR invoice. Provide worker_name ONLY if the user wants an individual invoice instead of a consolidated one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "worker_name": {"type": "string", "description": "Optional. The specific worker to invoice."}
                },
                "required": ["client_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draft_ap_bill",
            "description": "Generates an AP bill. Provide worker_name ONLY if the user wants an individual bill instead of a consolidated one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendor_name": {"type": "string"},
                    "worker_name": {"type": "string", "description": "Optional. The specific worker to bill for."}
                },
                "required": ["vendor_name"]
            }
        }
    }
]