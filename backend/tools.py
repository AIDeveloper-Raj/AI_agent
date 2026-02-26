import json
from pathlib import Path
from backend.db import get_unbilled_ar_for_client, get_unbilled_ap_for_vendor, get_worker_info, get_worker_list

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _load(table):
    file_path = DATA_DIR / f"{table}.json"
    if not file_path.exists(): return []
    with open(file_path, "r") as f: return json.load(f)

def scan_pending_billing():
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

        if ts["ar_invoiced_flag"] == 0:
            c = next((x for x in clients if x["client_id"] == p["client_id"]), None)
            if c:
                if c["name"] not in pending_ar: pending_ar[c["name"]] = []
                if worker_name not in pending_ar[c["name"]]: pending_ar[c["name"]].append(worker_name)

        if ts["ap_invoiced_flag"] == 0:
            wd = next((x for x in workers_details if x["worker_id"] == p["worker_id"]), None)
            if wd and wd["employment_type"] in ["1099", "C2C"]:
                v = next((x for x in vendors if x["vendor_id"] == p["vendor_id"]), None)
                if v:
                    if v["name"] not in pending_ap: pending_ap[v["name"]] = []
                    if worker_name not in pending_ap[v["name"]]: pending_ap[v["name"]].append(worker_name)

    return {"clients_needing_invoices": pending_ar, "vendors_needing_bills": pending_ap}

def draft_ar_invoice(client_name: str, worker_name: str = None):
    # PYTHON HANDLES THE BATCHING LOOP
    if worker_name == "ALL_INDIVIDUAL":
        pending = scan_pending_billing()
        workers = pending["clients_needing_invoices"].get(client_name, [])
        drafts = []
        for w in workers:
            res = get_unbilled_ar_for_client(client_name, w)
            if res: drafts.append(res)
        return {"multiple_drafts": drafts} if drafts else {"error": "No unbilled AR data found."}
    
    result = get_unbilled_ar_for_client(client_name, worker_name)
    return result if result else {"error": "No unbilled AR data found."}

def draft_ap_bill(vendor_name: str, worker_name: str = None):
    # PYTHON HANDLES THE BATCHING LOOP
    if worker_name == "ALL_INDIVIDUAL":
        pending = scan_pending_billing()
        workers = pending["vendors_needing_bills"].get(vendor_name, [])
        drafts = []
        for w in workers:
            res = get_unbilled_ap_for_vendor(vendor_name, w)
            if res: drafts.append(res)
        return {"multiple_drafts": drafts} if drafts else {"error": "No unbilled AP data found."}
        
    result = get_unbilled_ap_for_vendor(vendor_name, worker_name)
    return result if result else {"error": "No unbilled AP data found."}

def query_database(query_type: str, target_name: str = None):
    if query_type == "worker_info" and target_name:
        return get_worker_info(target_name)
    elif query_type == "worker_list" and target_name:
        return get_worker_list(target_name)
    return {"error": "Invalid query type or missing target."}

FINANCE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scan_pending_billing",
            "description": "Scans the DB for pending AR/AP."
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
            "name": "draft_ar_invoice",
            "description": "Generates an AR invoice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"}, 
                    "worker_name": {"type": "string", "description": "Name of specific worker, OR pass exactly 'ALL_INDIVIDUAL' to do everyone."}
                },
                "required": ["client_name"]
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
                    "worker_name": {"type": "string", "description": "Name of specific worker, OR pass exactly 'ALL_INDIVIDUAL' to do everyone."}
                },
                "required": ["vendor_name"]
            }
        }
    }
]