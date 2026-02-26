import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _load(table):
    """Helper to load a JSON table."""
    file_path = DATA_DIR / f"{table}.json"
    if not file_path.exists():
        return []
    with open(file_path, "r") as f:
        return json.load(f)

def get_unbilled_ar_for_client(client_name, worker_name=None):
    """
    AR LOGIC:
    1. Finds client & active placements.
    2. Pulls APPROVED timesheets/expenses where ar_invoiced_flag == 0.
    3. Splits hours by pay_code (Standard, OT, DT) using timesheets_daywise_details.
    4. Applies BILL RATES from placements_rates.
    5. Adds expenses as direct pass-throughs.
    """
    clients = _load("clients")
    client = next((c for c in clients if c["name"].lower() == client_name.lower()), None)
    if not client: return None

    placements = _load("placements")
    workers = _load("workers")
    timesheets = _load("timesheets")
    ts_details = _load("timesheets_daywise_details")
    rates = _load("placements_rates")
    expenses = _load("expenses")

    client_placements = [p for p in placements if p["client_id"] == client["client_id"]]
    placement_ids = [p["placement_id"] for p in client_placements]

    # Filter unbilled AR timesheets
    valid_ts = [ts for ts in timesheets if ts["placement_id"] in placement_ids and ts["status"] == "APPROVED" and ts["ar_invoiced_flag"] == 0]
    
    line_items = []
    grand_total = 0.0

    for ts in valid_ts:
        pid = ts["placement_id"]
        worker_id = next(p["worker_id"] for p in client_placements if p["placement_id"] == pid)
        worker = next(w for w in workers if w["worker_id"] == worker_id)
        worker_full_name = f"{worker['first_name']} {worker['last_name']}"

        # Filter by worker if requested
        if worker_name and worker_name.lower() not in worker_full_name.lower():
            continue

        # Group hours by pay_code (Standard, OT, etc.)
        details = [d for d in ts_details if d["ts_id"] == ts["ts_id"]]
        hours_by_code = {}
        for d in details:
            hours_by_code[d["pay_code"]] = hours_by_code.get(d["pay_code"], 0) + d["hours"]

        # Calculate line items using BILL RATE
        for code, hrs in hours_by_code.items():
            if hrs > 0:
                rate_record = next((r for r in rates if r["placement_id"] == pid and r["pay_code"] == code), None)
                bill_rate = rate_record["bill_rate"] if rate_record else 0
                total = hrs * bill_rate
                grand_total += total
                line_items.append({
                    "description": f"{code} Services - {worker_full_name} ({ts['start_date']} to {ts['end_date']})",
                    "hours": hrs,
                    "rate": bill_rate,
                    "total": round(total, 2)
                })

    # Add unbilled AR expenses
    valid_exp = [e for e in expenses if e["placement_id"] in placement_ids and e["status"] == "APPROVED" and e["ar_invoiced_flag"] == 0]
    for exp in valid_exp:
        grand_total += exp["amount"]
        line_items.append({
            "description": f"Expense: {exp['category']} ({exp['date']})",
            "hours": 1,
            "rate": exp["amount"],
            "total": exp["amount"]
        })

    return {
        "client_name": client["name"],
        "payment_terms": client["payment_terms"],
        "line_items": line_items,
        "grand_total": round(grand_total, 2),
        "ts_consumed": [ts["ts_id"] for ts in valid_ts],
        "exp_consumed": [e["exp_id"] for e in valid_exp]
    }

def get_unbilled_ap_for_vendor(vendor_name, worker_name=None):
    """
    AP LOGIC:
    1. Finds vendor & active placements.
    2. CHECKS workers_details. Completely ignores W-2 workers.
    3. Pulls APPROVED timesheets/expenses where ap_invoiced_flag == 0.
    4. Splits hours by pay_code.
    5. Applies PAY RATES from placements_rates.
    """
    vendors = _load("vendors")
    vendor = next((v for v in vendors if v["name"].lower() == vendor_name.lower()), None)
    if not vendor: return None

    placements = _load("placements")
    workers = _load("workers")
    workers_details = _load("workers_details")
    timesheets = _load("timesheets")
    ts_details = _load("timesheets_daywise_details")
    rates = _load("placements_rates")
    expenses = _load("expenses")

    vendor_placements = [p for p in placements if p["vendor_id"] == vendor["vendor_id"]]
    
    # CRITICAL: Filter out W-2 workers
    valid_placement_ids = []
    for p in vendor_placements:
        details = next((wd for wd in workers_details if wd["worker_id"] == p["worker_id"]), None)
        if details and details["employment_type"] in ["1099", "C2C"]:
            valid_placement_ids.append(p["placement_id"])

    # Filter unbilled AP timesheets
    valid_ts = [ts for ts in timesheets if ts["placement_id"] in valid_placement_ids and ts["status"] == "APPROVED" and ts["ap_invoiced_flag"] == 0]

    line_items = []
    grand_total = 0.0

    for ts in valid_ts:
        pid = ts["placement_id"]
        worker_id = next(p["worker_id"] for p in vendor_placements if p["placement_id"] == pid)
        worker = next(w for w in workers if w["worker_id"] == worker_id)
        worker_full_name = f"{worker['first_name']} {worker['last_name']}"

        # Filter by worker if requested
        if worker_name and worker_name.lower() not in worker_full_name.lower():
            continue

        details = [d for d in ts_details if d["ts_id"] == ts["ts_id"]]
        hours_by_code = {}
        for d in details:
            hours_by_code[d["pay_code"]] = hours_by_code.get(d["pay_code"], 0) + d["hours"]

        # Calculate line items using PAY RATE
        for code, hrs in hours_by_code.items():
            if hrs > 0:
                rate_record = next((r for r in rates if r["placement_id"] == pid and r["pay_code"] == code), None)
                pay_rate = rate_record["pay_rate"] if rate_record else 0
                total = hrs * pay_rate
                grand_total += total
                line_items.append({
                    "description": f"{code} Contractor Services - {worker_full_name} ({ts['start_date']} to {ts['end_date']})",
                    "hours": hrs,
                    "rate": pay_rate,
                    "total": round(total, 2)
                })

    # Add unbilled AP expenses
    valid_exp = [e for e in expenses if e["placement_id"] in valid_placement_ids and e["status"] == "APPROVED" and e["ap_invoiced_flag"] == 0]
    for exp in valid_exp:
        grand_total += exp["amount"]
        line_items.append({
            "description": f"Contractor Expense Pass-through: {exp['category']} ({exp['date']})",
            "hours": 1,
            "rate": exp["amount"],
            "total": exp["amount"]
        })

    return {
        "vendor_name": vendor["name"],
        "vendor_type": vendor["type"],
        "line_items": line_items,
        "grand_total": round(grand_total, 2),
        "ts_consumed": [ts["ts_id"] for ts in valid_ts],
        "exp_consumed": [e["exp_id"] for e in valid_exp]
    }

def get_worker_info(worker_name):
    """Fetches employment type and pending unbilled hours for a specific worker."""
    workers = _load("workers")
    workers_details = _load("workers_details")
    timesheets = _load("timesheets")
    placements = _load("placements")
    clients = _load("clients")

    worker = next((w for w in workers if worker_name.lower() in f"{w['first_name']} {w['last_name']}".lower()), None)
    if not worker: return {"error": f"Worker {worker_name} not found."}

    details = next((d for d in workers_details if d["worker_id"] == worker["worker_id"]), {})
    
    # Calculate pending hours
    worker_placements = [p["placement_id"] for p in placements if p["worker_id"] == worker["worker_id"]]
    pending_ts = [ts for ts in timesheets if ts["placement_id"] in worker_placements and ts["status"] == "APPROVED" and (ts["ar_invoiced_flag"] == 0 or ts["ap_invoiced_flag"] == 0)]
    
    total_hours = sum(ts["total_hours"] for ts in pending_ts)

    # Find their clients
    client_ids = list(set([p["client_id"] for p in placements if p["worker_id"] == worker["worker_id"]]))
    client_names = [c["name"] for c in clients if c["client_id"] in client_ids]

    return {
        "worker_name": f"{worker['first_name']} {worker['last_name']}",
        "employment_type": details.get("employment_type", "Unknown"),
        "pending_unbilled_hours": total_hours,
        "active_clients": client_names
    }

def get_worker_list(emp_type):
    """Returns a list of workers matching the employment type (W-2, 1099, C2C) and their clients."""
    workers, workers_details = _load("workers"), _load("workers_details")
    placements, clients = _load("placements"), _load("clients")

    results = []
    matched_details = [d for d in workers_details if d["employment_type"].lower() == emp_type.lower()]

    for d in matched_details:
        w = next((x for x in workers if x["worker_id"] == d["worker_id"]), None)
        if w:
            w_placements = [p for p in placements if p["worker_id"] == d["worker_id"]]
            client_names = list(set([
                next((c["name"] for c in clients if c["client_id"] == p["client_id"]), "Unknown")
                for p in w_placements
            ]))
            results.append({
                "worker_name": f"{w['first_name']} {w['last_name']}",
                "employment_type": d["employment_type"],
                "clients": ", ".join(client_names)
            })

    return {"list_name": f"{emp_type.upper()} Contractors/Employees", "data": results}