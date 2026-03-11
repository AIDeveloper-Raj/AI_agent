import json
import requests
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _load(table):
    file_path = DATA_DIR / f"{table}.json"
    if not file_path.exists(): return []
    with open(file_path, "r") as f: return json.load(f)

# ==========================================
# 🚀 NEW CEIPAL API ADAPTER (AR ONLY)
# ==========================================
API_BASE = "https://wfvmsnodeservice.ceipal.com"

def _fetch_ceipal(endpoint):
    url = f"{API_BASE}{endpoint}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        print(f"API Error [{response.status_code}]: {url}")
        return None
    except Exception as e:
        print(f"API Exception [{endpoint}]: {str(e)}")
        return None

def execute_universal_ar_billing(client_name=None, worker_name=None, period=None, hours_filter=None, mode=None):
    resolved_client_id = None
    resolved_client_name = client_name
    resolved_worker_ids = []

    # ---------------------------------------------------------
    # PHASE 0: THE "EMPTY INTENT" INTERCEPTOR
    # ---------------------------------------------------------
    if not client_name and not worker_name:
        client_data = _fetch_ceipal("/invoices/clients/search?name=a")
        if client_data and "clients" in client_data:
            clients = client_data["clients"]
            options = [{"label": c["name"], "value": f"Run AR billing for {c['name']}"} for c in clients[:5]]
            return {
                "error": "I am ready to run AR. Here are your top clients. Please select one to begin:",
                "ambiguity_options": options
            }
        return {"error": "I am ready to run AR. Please reply with the exact name of the client you want to bill."}

    # ---------------------------------------------------------
    # PHASE 1: SCOPE RESOLUTION & AMBIGUITY INTERCEPTION
    # ---------------------------------------------------------
    
    # A. Resolve the Client
    if client_name:
        encoded_cname = urllib.parse.quote(client_name)
        client_data = _fetch_ceipal(f"/invoices/clients/search?name={encoded_cname}")
        
        # Explicit Error Catching for the API
        if not client_data:
            return {"error": f"API Error: Failed to reach the Client Search service for '{client_name}'."}
            
        if "clients" in client_data:
            clients = client_data["clients"]
            if len(clients) > 1:
                options = [{"label": c["name"], "value": f"Run AR billing for {c['name']}"} for c in clients[:4]]
                return {
                    "error": f"Multiple clients found matching '{client_name}'. Please ask the user to clarify.", 
                    "ambiguity_options": options
                }
            elif len(clients) == 1:
                resolved_client_id = clients[0]["client_id"]
                resolved_client_name = clients[0]["name"]
            else:
                return {"error": f"No active client found matching '{client_name}'."}
        else:
            return {"error": f"Unexpected API response when searching for client '{client_name}'."}

    # B. Resolve the Worker
    if worker_name and worker_name != "ALL_INDIVIDUAL":
        encoded_wname = urllib.parse.quote(worker_name)
        worker_data = _fetch_ceipal(f"/invoices/workers/search?name={encoded_wname}")
        
        if not worker_data:
             return {"error": f"API Error: Failed to reach the Worker Search service for '{worker_name}'."}

        if "workers" in worker_data:
            workers = worker_data["workers"]
            if len(workers) > 1:
                options = [{"label": w["name"], "value": f"Run AR billing for {w['name']} at {resolved_client_name or 'their client'}"} for w in workers[:4]]
                return {"error": f"Multiple workers found matching '{worker_name}'. Please ask the user to clarify.", "ambiguity_options": options}
            elif len(workers) == 1:
                emp_id = workers[0]["employee_id"]
                resolved_worker_ids.append(emp_id)

                if not resolved_client_id:
                    details = _fetch_ceipal(f"/invoices/workers/{emp_id}")
                    if details and "current_assignments" in details:
                        active_clients = [a for a in details["current_assignments"] if a["status"] == "active"]
                        if len(active_clients) > 1:
                            options = [{"label": a["client_name"], "value": f"Run AR billing for {worker_name} at {a['client_name']}"} for a in active_clients]
                            return {"error": f"{worker_name} has multiple active client assignments. Which client?", "ambiguity_options": options}
                        elif len(active_clients) == 1:
                            resolved_client_id = active_clients[0]["client_id"]
                            resolved_client_name = active_clients[0]["client_name"]
            else:
                return {"error": f"No active worker found matching '{worker_name}'."}
                
    # C. Handle Null Worker (Fetch ALL workers for the resolved client)
    elif resolved_client_id:
        is_explicit_batch = worker_name == "ALL_INDIVIDUAL" or (mode and str(mode).lower() in ["consolidated", "individual"])
        
        client_workers = _fetch_ceipal(f"/invoices/clients/{resolved_client_id.split('-')[-1]}/workers")
        
        if not client_workers:
            return {"error": f"API Error: Failed to fetch workers for client '{resolved_client_name}'."}
            
        active_workers = [w for w in client_workers.get("workers", []) if w.get("employee_status", "").lower() == "active"]
        
        if is_explicit_batch:
            resolved_worker_ids = [w["employee_id"] for w in active_workers]
        else:
            # INTERCEPTOR: Count who actually has timesheets
            workers_with_ts = []
            for w in active_workers:
                ts_query = f"?worker_id={w['employee_id']}&client_id={resolved_client_id.split('-')[-1]}"
                if period: ts_query += f"&period={urllib.parse.quote(period)}"
                
                ts_data = _fetch_ceipal(f"/invoices/timesheets{ts_query}")
                
                has_ts = False
                if ts_data and "timesheets" in ts_data and ts_data["timesheets"]:
                    for role, periods in ts_data["timesheets"].items():
                        if periods: has_ts = True
                if has_ts:
                    workers_with_ts.append(w)
            
            # Condition 1: No data found
            if len(workers_with_ts) == 0:
                fallback = _fetch_ceipal("/invoices/clients/search?name=a")
                options = []
                if fallback and "clients" in fallback:
                     other = [c for c in fallback["clients"] if c["client_id"] != resolved_client_id][:4]
                     options = [{"label": c["name"], "value": f"Run AR billing for {c['name']}"} for c in other]
                return {
                    "error": f"{resolved_client_name} has no approved, unbilled timesheets matching your criteria. Try another client:",
                    "ambiguity_options": options
                }
            
            # Condition 2: Only 1 worker
            elif len(workers_with_ts) == 1:
                resolved_worker_ids = [workers_with_ts[0]["employee_id"]]
            
            # Condition 3: 2 to 5 workers (Show Buttons)
            elif len(workers_with_ts) <= 5:
                options = [
                    {"label": "Consolidate all workers", "value": f"Run consolidated AR billing for {resolved_client_name}"},
                    {"label": "Bill all individually", "value": f"Run individual AR billing for ALL_INDIVIDUAL at {resolved_client_name}"}
                ]
                for w in workers_with_ts:
                    options.append({"label": f"Bill {w['name']} individually", "value": f"Run AR billing for {w['name']} at {resolved_client_name}"})
                    
                names = ", ".join([w['name'] for w in workers_with_ts])
                return {
                    "error": f"{resolved_client_name} has {len(workers_with_ts)} workers with pending AR billables: {names}. How would you like to generate the invoices?",
                    "ambiguity_options": options
                }
            
            # Condition 4: > 5 workers (Show Canvas Table)
            else:
                options = [
                    {"label": "Consolidate all workers", "value": f"Run consolidated AR billing for {resolved_client_name}"},
                    {"label": "Bill all individually", "value": f"Run individual AR billing for ALL_INDIVIDUAL at {resolved_client_name}"}
                ]
                table_data = [{"Worker Name": w["name"], "Employee Type": w["employee_type"], "Status": "Pending Timesheets"} for w in workers_with_ts]
                return {
                    "error": f"{resolved_client_name} has {len(workers_with_ts)} workers with pending AR. I have listed them on the canvas. How would you like to proceed?",
                    "ambiguity_options": options,
                    "data_views": [{"list_name": f"{resolved_client_name} - Pending Workers", "data": table_data}]
                }

    # Final Catch-All Failsafe
    if not resolved_client_id or not resolved_worker_ids:
        return {"error": "Execution stopped. Either the client/worker could not be resolved, or they have no active data available."}

    # ---------------------------------------------------------
    # PHASE 2: FETCH TIMESHEETS & BUILD PREVIEWS
    # ---------------------------------------------------------
    drafts = []
    
    for emp_id in resolved_worker_ids:
        ts_query = f"?worker_id={emp_id}&client_id={resolved_client_id.split('-')[-1]}"
        if period: ts_query += f"&period={urllib.parse.quote(period)}"

        timesheet_data = _fetch_ceipal(f"/invoices/timesheets{ts_query}")
        if not timesheet_data or "timesheets" not in timesheet_data:
            continue

        identifiers = []
        for role, periods in timesheet_data["timesheets"].items():
            for p_name, p_data in periods.items():
                if "unique_identifier" in p_data:
                    identifiers.append(p_data["unique_identifier"])

        for uid in identifiers:
            preview_data = _fetch_ceipal(f"/invoices/preview?unique_identifier={uid}")
            if preview_data and "setDataTopreview" in preview_data:
                preview = preview_data["setDataTopreview"]
                inv_meta = preview.get("Invoice", {})
                inv_details = preview.get("InvoiceDetail", {})

                draft = {
                    "client_name": resolved_client_name or inv_meta.get("client_name", "Unknown Client"),
                    "status": "Draft",
                    "grand_total": float(inv_meta.get("sub_total", 0.0)),
                    "line_items": []
                }

                for key, item in inv_details.items():
                    if hours_filter and hours_filter.upper() not in str(item.get("class_name", "")).upper():
                        continue 

                    draft["line_items"].append({
                        "description": item.get("description") or f"Contractor Services ({inv_meta.get('invoice_period')})",
                        "hours": float(item.get("working_hours", 0.0)),
                        "rate": float(item.get("sell_rate", 0.0)),
                        "total": float(item.get("amount", 0.0))
                    })
                
                if draft["line_items"]:
                    drafts.append(draft)

    if not drafts:
        return {"error": f"No unbilled timesheets found matching your criteria for {resolved_client_name}."}

    # ---------------------------------------------------------
    # PHASE 3: CONSOLIDATION MATH
    # ---------------------------------------------------------
    if mode and str(mode).lower() == "consolidated" and len(drafts) > 1:
        consolidated_draft = {
            "client_name": resolved_client_name,
            "status": "Draft",
            "grand_total": sum(d["grand_total"] for d in drafts),
            "line_items": []
        }
        for d in drafts:
            consolidated_draft["line_items"].extend(d["line_items"])
        return {"multiple_drafts": [consolidated_draft]}

    return {"multiple_drafts": drafts}

# ==========================================
# 🛑 LEGACY AP & WORKER FUNCTIONS (Untouched)
# ==========================================
def get_unbilled_ap_for_vendor(vendor_name, worker_name=None, pay_code=None, start_date=None, end_date=None):
    vendors = _load("vendors")
    vendor = next((v for v in vendors if v["name"].lower() == vendor_name.lower()), None)
    if not vendor: return None
    return {
        "vendor_name": vendor["name"], "status": "Draft", "grand_total": 0.0,
        "line_items": [{"description": "Legacy AP Logic", "hours": 0, "rate": 0, "total": 0}]
    }

def get_worker_info(worker_name):
    workers = _load("workers")
    w = next((x for x in workers if f"{x['first_name']} {x['last_name']}".lower() == worker_name.lower()), None)
    return {"worker_details": w} if w else {"error": "Worker not found locally."}

def get_worker_list(target):
    return {"error": "List logic temporarily disabled during AR transition."}