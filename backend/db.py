import json
import re
import requests
import urllib.parse
from datetime import date, datetime, timedelta
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

API_BASE = "https://wfvmsnodeservice.ceipal.com"
REQUEST_TIMEOUT = 15


def _load(table: str):
    file_path = DATA_DIR / f"{table}.json"
    if not file_path.exists():
        return []
    with open(file_path, "r") as f:
        return json.load(f)


# =========================================================
# CEIPAL API HELPERS
# =========================================================
def _fetch_ceipal(endpoint: str) -> Optional[Dict[str, Any]]:
    url = f"{API_BASE}{endpoint}"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return response.json()

        print(f"API Error [{response.status_code}] {url}")
        return None
    except Exception as e:
        print(f"API Exception [{endpoint}] -> {e}")
        return None


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", _safe_str(value)).strip()


def _clean_client_name(value: str) -> str:
    value = _normalize_spaces(value)
    return value.strip(" ,.-_").strip()


def _extract_numeric_client_id(client_id: Any) -> Optional[int]:
    """
    Handles values like:
    - 7
    - "7"
    - "CLN-1001"
    - "CLN001"
    """
    if client_id is None:
        return None

    raw = str(client_id).strip()
    match = re.search(r"(\d+)$", raw)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


# =========================================================
# PHASE 1 WELCOME
# =========================================================
def get_finance_welcome_payload() -> Dict[str, Any]:
    return {
        "phase1_status": "welcome",
        "message": "Hi, what would you like to do today?",
        "action_cards": [
            {"label": "Create AR", "value": "Create AR"},
            {"label": "Create AP", "value": "Create AP"},
        ],
    }


# =========================================================
# INTENT / FUZZY PROMPT HELPERS
# =========================================================
AR_INTENT_KEYWORDS = [
    "create ar",
    "run ar",
    "invoice",
    "billing",
    "bill",
    "generate invoice",
    "create invoice",
]

AP_INTENT_KEYWORDS = [
    "create ap",
    "accounts payable",
    "vendor bill",
    "payable",
]


def detect_ar_intent(user_text: Optional[str]) -> Dict[str, Any]:
    """
    Business-safe fuzzy detection.
    Supports rough user phrasing and spelling mistakes.
    """
    original_text = _normalize_spaces(user_text or "")
    text = original_text.lower()

    if not text:
        return {"is_ar_intent": False, "client_hint": None, "is_ap_intent": False}

    # Strong AP detection first
    is_ap = any(keyword in text for keyword in AP_INTENT_KEYWORDS)

    # AR intent signals, including common misspellings / short forms
    ar_signals = [
        "create ar",
        "run ar",
        " ar ",
        "invoice",
        "invoe",
        "invec",
        "billing",
        "bill",
        "generate invoice",
        "generate billing",
        "create invoice",
        "create billing",
    ]

    is_ar = any(signal in f" {text} " for signal in ar_signals)

    # If clearly AP and not AR, keep it AP
    if is_ap and not is_ar:
        return {"is_ar_intent": False, "client_hint": None, "is_ap_intent": True}

    # Strip command words; keep remaining text as possible client hint
    cleaned = text
    filler_patterns = [
        r"\blet(?:'s|s)? do the same for\b",
        r"\blet(?:'s|s)? bill\b",
        r"\bdo ar for\b",
        r"\bcreate ar for\b",
        r"\brun ar for\b",
        r"\bcreate ar\b",
        r"\brun ar\b",
        r"\bcreate invoice for\b",
        r"\bgenerate invoice for\b",
        r"\bcreate billing for\b",
        r"\binvoice for\b",
        r"\bbill for\b",
        r"\binvoice\b",
        r"\binvoe\b",
        r"\binvec\b",
        r"\bbilling\b",
        r"\bbill\b",
        r"\bcreate\b",
        r"\bgenerate\b",
        r"\brun\b",
        r"\bfor\b",
        r"\bclient\b",
        r"\bar\b",
        r"\bplease\b",
        r"\bthe\b",
    ]

    for pattern in filler_patterns:
        cleaned = re.sub(pattern, " ", cleaned)

    cleaned = _normalize_spaces(cleaned)
    cleaned = cleaned.strip(" ,.-_")

    # Ignore trivial leftovers that are not a client name
    if cleaned in {"yes", "no", "ok", "okay", "sure"}:
        cleaned = ""

    client_hint = cleaned if cleaned else None

    return {
        "is_ar_intent": bool(is_ar),
        "client_hint": client_hint,
        "is_ap_intent": is_ap and not is_ar,
    }


# =========================================================
# CLIENT SEARCH / NORMALIZATION
# =========================================================
def _normalize_client(client: Dict[str, Any], worker_count: Optional[int] = None) -> Dict[str, Any]:
    raw_client_id = client.get("client_id")
    client_unique_id = client.get("client_unique_id")
    client_name = client.get("name") or client.get("client_name") or "Unknown Client"

    normalized = {
        # display/business id from API, e.g. CLN-1001
        "client_id": raw_client_id,

        # real numeric id used by tsdetailsByClient
        "client_unique_id": client_unique_id,

        # numeric id we should use for downstream tsdetailsByClient lookup
        "client_numeric_id": (
            client_unique_id
            if client_unique_id is not None
            else _extract_numeric_client_id(raw_client_id)
        ),

        "client_name": client_name,
        "worker_count": worker_count if worker_count is not None else client.get("worker_count"),
    }

    wc = normalized.get("worker_count")
    if isinstance(wc, int):
        normalized["label"] = f"{client_name} ({wc} Workers)"
    else:
        normalized["label"] = client_name

    return normalized


def get_pending_clients() -> List[Dict[str, Any]]:
    """
    Uses the pending-clients API with no search string.
    This is the default list shown after Create AR.
    """
    payload = _fetch_ceipal("/invoices/clients/search")
    if not payload or "clients" not in payload:
        return []

    normalized = []
    for client in payload.get("clients", []):
        normalized.append(_normalize_client(client))
    return normalized


def search_pending_clients(name: str) -> List[Dict[str, Any]]:
    name = _clean_client_name(name)
    if not name:
        return []

    encoded = urllib.parse.quote(name)
    payload = _fetch_ceipal(f"/invoices/clients/search?name={encoded}")
    if not payload or "clients" not in payload:
        return []

    return [_normalize_client(c) for c in payload.get("clients", [])]


def search_all_clients(name: str) -> List[Dict[str, Any]]:
    name = _clean_client_name(name)
    if not name:
        return []

    encoded = urllib.parse.quote(name)
    payload = _fetch_ceipal(f"/invoices/allclients/search?name={encoded}")
    if not payload:
        return []

    # Some APIs return {"clients": [...]}, others may vary
    raw_clients = payload.get("clients") or payload.get("data") or []
    if not isinstance(raw_clients, list):
        return []

    return [_normalize_client(c) for c in raw_clients]


def _score_client_match(query: str, candidate_name: str) -> int:
    """
    Simple deterministic ranking:
    1. exact
    2. startswith
    3. contains
    4. close text
    """
    q = _clean_client_name(query).lower()
    c = _clean_client_name(candidate_name).lower()

    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.startswith(q):
        return 85
    if q in c:
        return 70

    close = get_close_matches(q, [c], n=1, cutoff=0.65)
    if close:
        return 55

    return 0


def _dedupe_clients(clients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []

    for client in clients:
        key = (
            str(client.get("client_id")),
            _clean_client_name(client.get("client_name")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(client)

    return result


def _attach_worker_counts_from_pending(
    clients: List[Dict[str, Any]], pending_clients: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    pending_by_name = {
        _clean_client_name(c.get("client_name", "")).lower(): c for c in pending_clients
    }

    enriched = []
    for client in clients:
        key = _clean_client_name(client.get("client_name", "")).lower()
        if key in pending_by_name:
            pending_match = pending_by_name[key]
            client["worker_count"] = pending_match.get("worker_count")
            wc = client.get("worker_count")
            client["label"] = (
                f"{client['client_name']} ({wc} Workers)" if isinstance(wc, int) else client["client_name"]
            )
        enriched.append(client)
    return enriched


def _enrich_clients_from_pending_master(
    clients: List[Dict[str, Any]],
    pending_master: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Enrich search results with the safer IDs from the master pending-client list.
    This is critical because some search APIs return display client_id like CLN-1001,
    while downstream tsdetailsByClient expects client_unique_id like 7.
    """
    master_by_name = {
        _clean_client_name(c.get("client_name", "")).lower(): c
        for c in pending_master
    }

    enriched = []
    for client in clients:
        name_key = _clean_client_name(client.get("client_name", "")).lower()
        master = master_by_name.get(name_key)

        if master:
            # Prefer safer lookup values from the master pending list
            if master.get("client_unique_id") is not None:
                client["client_unique_id"] = master.get("client_unique_id")
                client["client_numeric_id"] = master.get("client_unique_id")

            # Carry worker count if missing
            if client.get("worker_count") is None:
                client["worker_count"] = master.get("worker_count")

            # Rebuild label after enrichment
            wc = client.get("worker_count")
            client["label"] = (
                f"{client['client_name']} ({wc} Workers)"
                if isinstance(wc, int)
                else client["client_name"]
            )

        enriched.append(client)

    return enriched


def _build_client_options(clients: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, str]]:
    options = []
    for client in clients[:limit]:
        selected_id = client.get("client_unique_id") or client.get("client_numeric_id") or client.get("client_id")
        options.append(
            {
                "label": client.get("label") or client.get("client_name") or "Unknown Client",
                "value": f"Select client::{selected_id}::{client.get('client_name')}",
            }
        )
    return options


def resolve_client_for_ar(client_hint: Optional[str]) -> Dict[str, Any]:
    """
    Main client resolution logic for Phase 1.
    """
    client_hint = _clean_client_name(client_hint or "")

    # Case 1: no hint -> show pending clients
    if not client_hint:
        pending_clients = get_pending_clients()
        if not pending_clients:
            return {
                "status": "no_pending_clients",
                "message": "There are no clients with approved timesheets pending invoicing right now.",
                "selected_client": None,
                "client_cards": [],
            }

        return {
            "status": "choose_client",
            "message": "Here are the clients with approved timesheets pending invoicing. Please select one client to continue.",
            "selected_client": None,
            "client_cards": _build_client_options(pending_clients),
            "clients": pending_clients,
        }

    # Case 2: search pending clients first
    pending_matches = search_pending_clients(client_hint)
    pending_matches = _dedupe_clients(pending_matches)

    # IMPORTANT:
    # search_pending_clients may return display client_id values like CLN-1001
    # while tsdetailsByClient expects client_unique_id like 7.
    # Always enrich search results from the master pending list by name.
    pending_master = get_pending_clients()
    pending_matches = _enrich_clients_from_pending_master(pending_matches, pending_master)

    if pending_matches:
        scored = sorted(
            pending_matches,
            key=lambda c: _score_client_match(client_hint, c.get("client_name", "")),
            reverse=True,
        )

        normalized_hint = _clean_client_name(client_hint).lower()

        exact_matches = [
            c for c in scored
            if _clean_client_name(c.get("client_name", "")).lower() == normalized_hint
        ]

        # 1. Exact match always resolves
        if len(exact_matches) == 1:
            return {
                "status": "resolved",
                "message": f"I found {exact_matches[0]['client_name']} with pending invoice items.",
                "selected_client": exact_matches[0],
                "client_cards": [],
            }

        # 2. One strong prefix-style business match can also resolve
        strong_prefix_matches = [
            c for c in scored
            if _clean_client_name(c.get("client_name", "")).lower().startswith(normalized_hint)
        ]

        if len(strong_prefix_matches) == 1:
            return {
                "status": "resolved",
                "message": f"I found {strong_prefix_matches[0]['client_name']} with pending invoice items.",
                "selected_client": strong_prefix_matches[0],
                "client_cards": [],
            }

        # 3. Otherwise require explicit user confirmation
        return {
            "status": "choose_client",
            "message": f"I found matching clients for '{client_hint}'. Please select one client to continue.",
            "selected_client": None,
            "client_cards": _build_client_options(scored),
            "clients": scored,
        }

    # Case 3: fallback to all-clients search for fuzzy spellings / loose lookup
    all_matches = search_all_clients(client_hint)
    all_matches = _dedupe_clients(all_matches)

    if all_matches:
        pending_clients = get_pending_clients()
        all_matches = _attach_worker_counts_from_pending(all_matches, pending_clients)

        scored = sorted(
            all_matches,
            key=lambda c: _score_client_match(client_hint, c.get("client_name", "")),
            reverse=True,
        )

        top_score = _score_client_match(client_hint, scored[0].get("client_name", "")) if scored else 0

        # Prefer clients that actually have pending invoice items
        pending_scored = [c for c in scored if c.get("worker_count") is not None]
        final_options = pending_scored if pending_scored else scored

        if top_score >= 70:
            message = f"I found matching clients for '{client_hint}'. Please select one client to continue."
        elif top_score >= 55:
            message = f"I found a few close client matches for '{client_hint}'. Please select the correct client."
        else:
            message = (
                f"I couldn't find a client matching '{client_hint}'. "
                f"Here are other clients with approved timesheets pending invoicing."
            )

        return {
            "status": "choose_client",
            "message": message,
            "selected_client": None,
            "client_cards": _build_client_options(final_options),
            "clients": final_options,
        }

    return {
        "status": "no_match",
        "message": f"I couldn't find a matching client for '{client_hint}'. Please try another client name.",
        "selected_client": None,
        "client_cards": [],
    }


# =========================================================
# PENDING ITEM TABLE
# =========================================================
def _format_hours(total_hours: Any) -> str:
    try:
        hours = float(total_hours)
        return f"{hours:.2f} Hours"
    except Exception:
        return "0.00 Hours"


def _format_worker_label(employee_name: str, emp_id: Any) -> str:
    emp_part = f"EMP{emp_id}" if emp_id is not None else "EMP-UNKNOWN"
    return f"{employee_name} / {emp_part}"


def _format_job_label(job_title: str, job_id: Any) -> str:
    title = job_title or "Unknown Job"
    jc = f"JC{job_id}" if job_id is not None else "JC-UNKNOWN"
    return f"{title} - {jc}"


def _normalize_pending_item(item: Dict[str, Any]) -> Dict[str, Any]:
    employee_name = item.get("employee_name") or "Unknown Worker"
    emp_id = item.get("emp_id")
    job_id = item.get("job_id")
    job_title = item.get("job_title") or "Unknown Job"

    ts_hours = item.get("ts_hours_breakdown") or {}
    total_hours = ts_hours.get("total_hours", 0)

    return {
        "worker": _format_worker_label(employee_name, emp_id),
        "hours": _format_hours(total_hours),
        "job": _format_job_label(job_title, job_id),
        "billing_cycle": item.get("invoice_cycle") or "Unknown Billing Cycle",
        "status_action": "Invoice",
        "employee_name": employee_name,
        "emp_id": emp_id,
        "job_id": job_id,
        "client_id": item.get("client_id"),
        "client_name": item.get("client_name"),
        "unique_identifier": item.get("unique_identifier"),
        "start_date": item.get("start_date"),
        "end_date": item.get("end_date"),
        "raw": item,
    }


def _apply_period_filter(items: List[Dict[str, Any]], period: Optional[str]) -> List[Dict[str, Any]]:
    """
    Supports:
    - None => no filter
    - "2025-03"
    - "March 2025"
    - "May"
    """
    if not period:
        return items

    p = _normalize_spaces(period).lower()

    # Easy pass-through for YYYY-MM
    yyyy_mm = re.match(r"^(\d{4})-(\d{2})$", p)
    if yyyy_mm:
        y, m = yyyy_mm.groups()
        result = []
        for item in items:
            start_date = _safe_str(item.get("start_date"))
            if start_date.startswith(f"{y}-{m}"):
                result.append(item)
        return result

    month_map = {
        "january": "01", "jan": "01",
        "february": "02", "feb": "02",
        "march": "03", "mar": "03",
        "april": "04", "apr": "04",
        "may": "05",
        "june": "06", "jun": "06",
        "july": "07", "jul": "07",
        "august": "08", "aug": "08",
        "september": "09", "sep": "09", "sept": "09",
        "october": "10", "oct": "10",
        "november": "11", "nov": "11",
        "december": "12", "dec": "12",
    }

    # Try to detect month + optional year
    tokens = p.split()
    month_num = None
    year_num = None

    for token in tokens:
        if token in month_map:
            month_num = month_map[token]
        elif token.isdigit() and len(token) == 4:
            year_num = token

    result = []
    for item in items:
        start_date = _safe_str(item.get("start_date"))
        if not start_date:
            continue

        if month_num and f"-{month_num}-" not in start_date:
            continue
        if year_num and not start_date.startswith(year_num):
            continue

        result.append(item)

    return result


def get_client_pending_items(
    client_id: Any,
    client_name: str,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    # tsdetailsByClient expects the numeric client_unique_id.
    # If we already received a pure numeric id like 7, use it directly.
    if isinstance(client_id, int):
        numeric_client_id = client_id
    else:
        raw = str(client_id).strip() if client_id is not None else ""
        if raw.isdigit():
            numeric_client_id = int(raw)
        else:
            numeric_client_id = _extract_numeric_client_id(client_id)
    if numeric_client_id is None:
        return {
            "status": "error",
            "message": f"Unable to resolve a numeric client id for {client_name}.",
            "rows": [],
        }

    payload = _fetch_ceipal(f"/invoices/tsdetailsByClient?client_id={numeric_client_id}")
    if payload is None:
        return {
            "status": "error",
            "message": f"Failed to fetch pending items for {client_name}.",
            "rows": [],
        }

    raw_items = []
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            raw_items = payload["data"]
        elif isinstance(payload.get("timesheets"), list):
            raw_items = payload["timesheets"]
        elif isinstance(payload.get("items"), list):
            raw_items = payload["items"]
        else:
            # some APIs may directly return a dict keyed by identifiers
            candidate_values = list(payload.values())
            if candidate_values and all(isinstance(x, dict) for x in candidate_values):
                raw_items = candidate_values

    normalized_rows = [_normalize_pending_item(item) for item in raw_items]
    normalized_rows = _apply_period_filter(normalized_rows, period)

    if not normalized_rows:
        return {
            "status": "empty",
            "message": f"I found {client_name}, but there are no approved timesheets pending invoicing right now.",
            "rows": [],
        }

    return {
        "status": "success",
        "message": f"{client_name} has pending invoice items ready for review.",
        "rows": normalized_rows,
    }


def build_pending_items_data_view(
    client_name: str,
    client_id: Any,
    rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    client_label_id = _safe_str(client_id) or "UNKNOWN"

    return {
        "list_name": f"Pending Invoices for {client_name} ({client_label_id})",
        "data": [
            {
                "Worker": row["worker"],
                "Hours": row["hours"],
                "Job": row["job"],
                "Billing Cycle": row["billing_cycle"],
                "Risk": row.get("risk_label", "Monitor"),
                "Status / Action": row["status_action"],
            }
            for row in rows
        ],
    }


# =========================================================
# SUMMARY ENGINE HELPERS
# =========================================================

def _parse_iso_date(value: Any) -> Optional[date]:
    raw = _safe_str(value)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_currency(value: float) -> str:
    return f"${value:,.2f}"


def _format_date_for_ui(value: Optional[date]) -> str:
    if not value:
        return "Unavailable"
    return value.strftime("%b %d, %Y")


def _fetch_worker_details(employee_id: Any) -> Optional[Dict[str, Any]]:
    if employee_id is None:
        return None
    return _fetch_ceipal(f"/invoices/workers/{employee_id}")


def _pick_assignment_for_client(worker_payload: Dict[str, Any], client_unique_id: Any) -> Optional[Dict[str, Any]]:
    """
    Worker API quality is inconsistent.
    We match by client_unique_id and prefer:
    1. active assignment if any
    2. latest start_date
    3. first matching assignment
    """
    assignments = worker_payload.get("current_assignments") or []
    matches = [
        a for a in assignments
        if str(a.get("client_unique_id")) == str(client_unique_id)
    ]

    if not matches:
        return None

    def _assignment_sort_key(a: Dict[str, Any]):
        is_active = 1 if _safe_str(a.get("status")).lower() == "active" else 0
        start_dt = _parse_iso_date(a.get("start_date")) or date(1900, 1, 1)
        return (is_active, start_dt)

    matches = sorted(matches, key=_assignment_sort_key, reverse=True)
    return matches[0]


def _get_row_bill_rate(row: Dict[str, Any], worker_cache: Dict[str, Any]) -> float:
    """
    Prefer bill rate from pending row.
    Fallback to worker assignment API.
    """
    raw = row.get("raw") or {}
    ts_rates = raw.get("ts_rates_breakdown") or {}
    rate = ts_rates.get("bill_rate")

    try:
        if rate is not None:
            return float(rate)
    except Exception:
        pass

    emp_id = row.get("emp_id")
    client_unique_id = row.get("client_id")

    if emp_id not in worker_cache:
        worker_cache[emp_id] = _fetch_worker_details(emp_id) or {}

    worker_payload = worker_cache.get(emp_id) or {}
    assignment = _pick_assignment_for_client(worker_payload, client_unique_id)

    if assignment:
        try:
            return float(assignment.get("bill_rate") or 0)
        except Exception:
            return 0.0

    return 0.0


def _get_row_payment_terms(row: Dict[str, Any], worker_cache: Dict[str, Any]) -> int:
    """
    Payment terms are enriched from worker assignment API.

    Business rule:
    If payment_terms = 0, treat it as standard 30-day terms.
    """
    emp_id = row.get("emp_id")
    client_unique_id = row.get("client_id")

    if emp_id not in worker_cache:
        worker_cache[emp_id] = _fetch_worker_details(emp_id) or {}

    worker_payload = worker_cache.get(emp_id) or {}
    assignment = _pick_assignment_for_client(worker_payload, client_unique_id)

    if assignment:
        try:
            payment_terms = int(assignment.get("payment_terms") or 0)
        except Exception:
            payment_terms = 0
    else:
        payment_terms = 0

    # Business rule: when payment_terms is 0, default to 30 days.
    if payment_terms == 0:
        payment_terms = 30

    return payment_terms


def build_pending_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    today = date.today()
    worker_cache: Dict[Any, Any] = {}

    total_items = len(rows)
    total_hours = 0.0
    older_than_45_hours = 0.0
    within_45_hours = 0.0
    cash_realization_at_risk = 0.0

    oldest_row = None
    oldest_end_date = None
    latest_projected_realization = None

    for row in rows:
        raw = row.get("raw") or {}
        ts_hours = raw.get("ts_hours_breakdown") or {}

        try:
            hours = float(ts_hours.get("total_hours") or 0)
        except Exception:
            hours = 0.0

        total_hours += hours

        end_dt = _parse_iso_date(row.get("end_date"))
        if end_dt:
            age_days = (today - end_dt).days
            if age_days > 45:
                older_than_45_hours += hours
            else:
                within_45_hours += hours

            if oldest_end_date is None or end_dt < oldest_end_date:
                oldest_end_date = end_dt
                oldest_row = row

        bill_rate = _get_row_bill_rate(row, worker_cache)
        cash_realization_at_risk += hours * bill_rate

        payment_terms = _get_row_payment_terms(row, worker_cache)
        projected_realization = today + timedelta(days=payment_terms)

        if latest_projected_realization is None or projected_realization > latest_projected_realization:
            latest_projected_realization = projected_realization

    oldest_pending_cycle = (
        oldest_row.get("billing_cycle")
        if oldest_row and oldest_row.get("billing_cycle")
        else "Unavailable"
    )

    insight = (
        f"{older_than_45_hours:.2f} hours are older than 45 days, increasing cash realization risk. "
        f"If invoiced today, full realization is projected by {_format_date_for_ui(latest_projected_realization)}."
    )

    return {
        "metrics": [
            {"label": "Pending Items", "value": str(total_items)},
            {"label": "Total Pending Hours", "value": f"{total_hours:.2f} hrs"},
            {"label": ">45 Day Hours", "value": f"{older_than_45_hours:.2f} hrs"},
            {"label": "0\u201345 Day Hours", "value": f"{within_45_hours:.2f} hrs"},
            {"label": "Cash Realization at Risk", "value": _format_currency(cash_realization_at_risk)},
            {"label": "Oldest Pending Cycle", "value": oldest_pending_cycle},
            {"label": "Projected Realization by", "value": _format_date_for_ui(latest_projected_realization)},
        ],
        "insight": insight,
    }


def _get_row_age_days(row: Dict[str, Any]) -> Optional[int]:
    end_dt = _parse_iso_date(row.get("end_date"))
    if not end_dt:
        return None
    return (date.today() - end_dt).days


def _get_row_cash_value(row: Dict[str, Any], worker_cache: Dict[str, Any]) -> float:
    raw = row.get("raw") or {}
    ts_hours = raw.get("ts_hours_breakdown") or {}

    try:
        hours = float(ts_hours.get("total_hours") or 0)
    except Exception:
        hours = 0.0

    bill_rate = _get_row_bill_rate(row, worker_cache)
    return hours * bill_rate


def _get_row_risk_label(row: Dict[str, Any], worker_cache: Dict[str, Any]) -> str:
    age_days = _get_row_age_days(row)
    cash_value = _get_row_cash_value(row, worker_cache)

    if age_days is None:
        return "Monitor"

    if age_days > 90:
        return "High Risk"
    if age_days > 45:
        return "Monitor"
    return "On Track"


def _risk_sort_weight(label: str) -> int:
    order = {
        "High Risk": 3,
        "Monitor": 2,
        "On Track": 1,
    }
    return order.get(label, 0)


def enrich_and_sort_pending_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    worker_cache: Dict[Any, Any] = {}
    enriched = []

    for row in rows:
        age_days = _get_row_age_days(row)
        cash_value = _get_row_cash_value(row, worker_cache)
        risk_label = _get_row_risk_label(row, worker_cache)

        row_copy = dict(row)
        row_copy["age_days"] = age_days
        row_copy["cash_value"] = cash_value
        row_copy["risk_label"] = risk_label
        enriched.append(row_copy)

    enriched.sort(
        key=lambda r: (
            _risk_sort_weight(r.get("risk_label")),
            r.get("age_days") if r.get("age_days") is not None else -1,
            r.get("cash_value", 0),
        ),
        reverse=True,
    )

    return enriched


def build_advisor_summary(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = {m["label"]: m["value"] for m in summary.get("metrics", [])}

    total_hours_raw = 0.0
    older_hours_raw = 0.0
    risk_value_raw = 0.0

    for row in rows:
        raw = row.get("raw") or {}
        ts_hours = raw.get("ts_hours_breakdown") or {}

        try:
            total_hours_raw += float(ts_hours.get("total_hours") or 0)
        except Exception:
            pass

        age_days = row.get("age_days")
        try:
            if age_days is not None and age_days > 45:
                older_hours_raw += float(ts_hours.get("total_hours") or 0)
        except Exception:
            pass

        try:
            risk_value_raw += float(row.get("cash_value") or 0)
        except Exception:
            pass

    points = []
    older_ratio = (older_hours_raw / total_hours_raw) if total_hours_raw > 0 else 0

    if total_hours_raw > 0 and older_ratio == 1:
        advisor_summary = "All pending hours are already beyond 45 days, making this a delayed billing risk rather than a normal invoice queue."
        points.append("Prioritize the oldest billing cycles first to reduce delay risk.")
        points.append("Review older pending items before bulk invoicing to avoid readiness issues.")
        points.append("Reduce cash realization exposure by clearing aged items first.")
    elif older_ratio >= 0.7:
        advisor_summary = "Most pending hours are already aged beyond 45 days, which raises billing delay and cash realization risk."
        points.append("Focus first on the oldest billing cycles.")
        points.append("Clear aged items before recent items to reduce exposure faster.")
        points.append("Review older rows for invoice readiness before pushing them in bulk.")
    else:
        advisor_summary = "The pending queue is mixed, with both aged and recent billing items requiring attention."
        points.append("Start with the older billing cycles first.")
        points.append("Keep recent items moving so they do not shift into the aged bucket.")
        points.append("Review high-value rows early to improve cash realization timing.")

    if risk_value_raw >= 50000:
        points.append("Cash realization exposure is significant, so prioritize higher-value pending rows.")
    if metrics.get("Projected Realization by") and metrics.get("Projected Realization by") != "Unavailable":
        points.append(f"If invoiced now, full realization is projected by {metrics.get('Projected Realization by')}.")
    if metrics.get("Oldest Pending Cycle") and metrics.get("Oldest Pending Cycle") != "Unavailable":
        points.append(f"The oldest pending cycle is {metrics.get('Oldest Pending Cycle')}, so older work should be reviewed first.")

    # keep advice compact
    points = points[:6]

    # normal case should show at least 3
    if len(points) < 3:
        points.append("Prioritize older items before newer ones.")
    if len(points) < 3:
        points.append("Clear invoice-ready rows quickly to improve cash timing.")

    return {
        "summary": advisor_summary,
        "points": points[:6],
    }


# =========================================================
# MAIN PHASE 1 AR EXECUTION
# =========================================================
def run_ar_phase1(
    user_text: Optional[str] = None,
    selected_client_id: Optional[Any] = None,
    selected_client_name: Optional[str] = None,
    action: Optional[str] = None,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main Phase 1 flow:
    - greet / action cards
    - Create AR
    - client resolution
    - pending items table
    """

    # 1) Explicit landing/welcome
    if action == "welcome":
        return get_finance_welcome_payload()

    # 2) AP placeholder for now
    if action == "create_ap":
        return {
            "phase1_status": "ap_placeholder",
            "message": "AP flow is not part of this phase yet. Please choose Create AR to continue.",
        }

    # 3) Explicit Create AR click
    if action == "create_ar":
        resolution = resolve_client_for_ar(None)
        if resolution["status"] == "choose_client":
            return {
                "phase1_status": "choose_client",
                "message": resolution["message"],
                "ambiguity_options": resolution["client_cards"],
            }
        return {
            "phase1_status": resolution["status"],
            "message": resolution["message"],
            "ambiguity_options": [],
        }

    # 4) Explicit client selected from a card
    if selected_client_id and selected_client_name:
        pending = get_client_pending_items(selected_client_id, selected_client_name, period=period)
        if pending["status"] != "success":
            return {
                "phase1_status": pending["status"],
                "message": pending["message"],
                "data_views": [],
            }

        sorted_rows = enrich_and_sort_pending_rows(pending["rows"])
        summary = build_pending_summary(sorted_rows)
        advisor = build_advisor_summary(summary, sorted_rows)

        return {
            "phase1_status": "show_pending_table",
            "message": pending["message"],
            "selected_client": {
                "client_id": selected_client_id,
                "client_name": selected_client_name,
            },
            "summary": summary,
            "advisor": advisor,
            "data_views": [
                build_pending_items_data_view(
                    selected_client_name,
                    selected_client_id,
                    sorted_rows,
                )
            ],
            "table_rows": sorted_rows,
        }

    # 5) Typed prompt path
    intent_info = detect_ar_intent(user_text)

    if intent_info["is_ap_intent"] and not intent_info["is_ar_intent"]:
        return {
            "phase1_status": "ap_placeholder",
            "message": "AP flow is not part of this phase yet. Please choose Create AR to continue.",
        }

    if intent_info["is_ar_intent"]:
        resolution = resolve_client_for_ar(intent_info["client_hint"])

        if resolution["status"] == "resolved":
            selected_client = resolution["selected_client"]
            pending = get_client_pending_items(
                selected_client["client_id"],
                selected_client["client_name"],
                period=period,
            )

            if pending["status"] != "success":
                return {
                    "phase1_status": pending["status"],
                    "message": pending["message"],
                    "data_views": [],
                }

            sorted_rows = enrich_and_sort_pending_rows(pending["rows"])
            summary = build_pending_summary(sorted_rows)
            advisor = build_advisor_summary(summary, sorted_rows)

            return {
                "phase1_status": "show_pending_table",
                "message": pending["message"],
                "selected_client": selected_client,
                "summary": summary,
                "advisor": advisor,
                "data_views": [
                    build_pending_items_data_view(
                        selected_client["client_name"],
                        selected_client["client_id"],
                        sorted_rows,
                    )
                ],
                "table_rows": sorted_rows,
            }

        if resolution["status"] in ["choose_client", "no_pending_clients", "no_match"]:
            return {
                "phase1_status": resolution["status"],
                "message": resolution["message"],
                "ambiguity_options": resolution.get("client_cards", []),
                "data_views": [],
            }

    # 6) Fallback = welcome
    welcome = get_finance_welcome_payload()
    return {
        "phase1_status": "welcome",
        "message": welcome["message"],
        "action_cards": welcome["action_cards"],
    }


# =========================================================
# COMPATIBILITY WRAPPER
# Keeps current app working while we refactor other files.
# =========================================================
def execute_universal_ar_billing(
    client_name=None,
    worker_name=None,
    period=None,
    hours_filter=None,
    mode=None
):
    """
    Compatibility wrapper for the current tool wiring.

    Current app still calls this function via run_ar_billing().
    We repurpose it for March 12 Phase 1.
    """
    # Card-driven explicit flow
    if client_name == "Create AR":
        result = run_ar_phase1(action="create_ar", period=period)
        return {
            "error": result.get("message"),
            "ambiguity_options": result.get("ambiguity_options", []),
            "data_views": result.get("data_views", []),
            "phase1_status": result.get("phase1_status"),
        }

    if client_name == "Create AP":
        result = run_ar_phase1(action="create_ap")
        return {
            "error": result.get("message"),
            "phase1_status": result.get("phase1_status"),
        }

    # If a client is explicitly passed, resolve it safely and use the resolved numeric id
    if client_name and client_name not in ["Create AR", "Create AP"]:
        resolution = resolve_client_for_ar(client_name)

        if resolution["status"] == "resolved":
            selected_client = resolution["selected_client"]

            resolved_id = (
                selected_client.get("client_unique_id")
                or selected_client.get("client_numeric_id")
                or selected_client.get("client_id")
            )

            pending = get_client_pending_items(
                resolved_id,
                selected_client["client_name"],
                period=period,
            )

            sorted_rows = []
            summary = None
            advisor = None
            if pending.get("status") == "success":
                sorted_rows = enrich_and_sort_pending_rows(pending["rows"])
                summary = build_pending_summary(sorted_rows)
                advisor = build_advisor_summary(summary, sorted_rows)

            return {
                "error": pending.get("message"),
                "ambiguity_options": [],
                "summary": summary,
                "advisor": advisor,
                "data_views": (
                    [build_pending_items_data_view(
                        selected_client["client_name"],
                        resolved_id,
                        sorted_rows,
                    )]
                    if pending.get("status") == "success"
                    else []
                ),
                "phase1_status": (
                    "show_pending_table"
                    if pending.get("status") == "success"
                    else pending.get("status")
                ),
            }

        return {
            "error": resolution.get("message"),
            "ambiguity_options": resolution.get("client_cards", []),
            "data_views": [],
            "phase1_status": resolution.get("status"),
        }


    # If worker_name contains something useful from current tool wiring,
    # we ignore it in Phase 1.
    if worker_name:
        result = run_ar_phase1(user_text=f"Create invoice for {worker_name}", period=period)
        return {
            "error": result.get("message"),
            "ambiguity_options": result.get("ambiguity_options", []),
            "summary": result.get("summary"),
            "advisor": result.get("advisor"),
            "data_views": result.get("data_views", []),
            "phase1_status": result.get("phase1_status"),
        }

    # Default entry
    result = run_ar_phase1(action="create_ar", period=period)
    return {
        "error": result.get("message"),
        "ambiguity_options": result.get("ambiguity_options", []),
        "summary": result.get("summary"),
        "advisor": result.get("advisor"),
        "data_views": result.get("data_views", []),
        "phase1_status": result.get("phase1_status"),
    }


# =========================================================
# LEGACY AP / WORKER FUNCTIONS (LEFT AS-IS)
# =========================================================
def get_unbilled_ap_for_vendor(vendor_name, worker_name=None, pay_code=None, start_date=None, end_date=None):
    vendors = _load("vendors")
    vendor = next((v for v in vendors if v["name"].lower() == vendor_name.lower()), None)
    if not vendor:
        return None
    return {
        "vendor_name": vendor["name"],
        "status": "Draft",
        "grand_total": 0.0,
        "line_items": [{"description": "Legacy AP Logic", "hours": 0, "rate": 0, "total": 0}],
    }


def get_worker_info(worker_name):
    workers = _load("workers")
    w = next(
        (x for x in workers if f"{x['first_name']} {x['last_name']}".lower() == worker_name.lower()),
        None,
    )
    return {"worker_details": w} if w else {"error": "Worker not found locally."}


def get_worker_list(target):
    return {"error": "List logic temporarily disabled during AR transition."}
