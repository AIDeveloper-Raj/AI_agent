import os
import json
import random
from datetime import date, timedelta

def generate_db():
    # Create the data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    
    # 1. Clients
    clients = [
        {"client_id": 1, "name": "Google", "industry": "Tech", "payment_terms": "Net 30"},
        {"client_id": 2, "name": "Client ABC", "industry": "Finance", "payment_terms": "Net 15"},
        {"client_id": 3, "name": "TechCorp", "industry": "Software", "payment_terms": "Net 30"}
    ]
    
    # 2. Vendors (1099 workers are their own vendors, C2C use firm vendors)
    vendors = [
        {"vendor_id": 1, "name": "Rajesh Jonnalagadda", "type": "1099 Independent"},
        {"vendor_id": 2, "name": "TechStaff Inc", "type": "C2C Firm"},
        {"vendor_id": 3, "name": "CloudWorks LLC", "type": "C2C Firm"},
        {"vendor_id": 4, "name": "Michael Chen", "type": "1099 Independent"}
    ]
    
    # 3. Workers
    workers = [
        {"worker_id": 101, "first_name": "Rajesh", "last_name": "Jonnalagadda", "email": "rajesh@example.com"},
        {"worker_id": 102, "first_name": "John", "last_name": "Doe", "email": "john@example.com"},
        {"worker_id": 103, "first_name": "Jane", "last_name": "Smith", "email": "jane@example.com"},
        {"worker_id": 104, "first_name": "Alice", "last_name": "Brown", "email": "alice@example.com"},
        {"worker_id": 105, "first_name": "Bob", "last_name": "Wilson", "email": "bob@example.com"},
        {"worker_id": 106, "first_name": "Michael", "last_name": "Chen", "email": "michael@example.com"},
        {"worker_id": 107, "first_name": "Sarah", "last_name": "Davis", "email": "sarah@example.com"},
        {"worker_id": 108, "first_name": "David", "last_name": "Miller", "email": "david@example.com"},
        {"worker_id": 109, "first_name": "Emily", "last_name": "Taylor", "email": "emily@example.com"},
        {"worker_id": 110, "first_name": "James", "last_name": "Anderson", "email": "james@example.com"}
    ]
    
    # 4. Worker Details (Employment types & vendor mapping)
    workers_details = [
        {"worker_id": 101, "employment_type": "1099", "vendor_id": 1},
        {"worker_id": 102, "employment_type": "W-2", "vendor_id": None},
        {"worker_id": 103, "employment_type": "C2C", "vendor_id": 2},
        {"worker_id": 104, "employment_type": "W-2", "vendor_id": None},
        {"worker_id": 105, "employment_type": "C2C", "vendor_id": 3},
        {"worker_id": 106, "employment_type": "1099", "vendor_id": 4},
        {"worker_id": 107, "employment_type": "W-2", "vendor_id": None},
        {"worker_id": 108, "employment_type": "W-2", "vendor_id": None},
        {"worker_id": 109, "employment_type": "C2C", "vendor_id": 2},
        {"worker_id": 110, "employment_type": "W-2", "vendor_id": None}
    ]
    
    # 5. Placements (The Nexus: Google has 4 active workers to test batching)
    placements = [
        {"placement_id": 1001, "client_id": 1, "worker_id": 101, "vendor_id": 1, "status": "Active"},
        {"placement_id": 1002, "client_id": 1, "worker_id": 102, "vendor_id": None, "status": "Active"},
        {"placement_id": 1003, "client_id": 1, "worker_id": 103, "vendor_id": 2, "status": "Active"},
        {"placement_id": 1004, "client_id": 1, "worker_id": 104, "vendor_id": None, "status": "Active"},
        {"placement_id": 1005, "client_id": 2, "worker_id": 105, "vendor_id": 3, "status": "Active"},
        {"placement_id": 1006, "client_id": 2, "worker_id": 106, "vendor_id": 4, "status": "Active"},
        {"placement_id": 1007, "client_id": 2, "worker_id": 107, "vendor_id": None, "status": "Active"},
        {"placement_id": 1008, "client_id": 3, "worker_id": 108, "vendor_id": None, "status": "Active"},
        {"placement_id": 1009, "client_id": 3, "worker_id": 109, "vendor_id": 2, "status": "Active"},
        {"placement_id": 1010, "client_id": 3, "worker_id": 110, "vendor_id": None, "status": "Active"}
    ]
    
    # 6. Placements Rates (Bill vs Pay, with Standard, OT, and DT variants)
    placements_rates = []
    for p in placements:
        base_bill = random.choice([80, 100, 120, 150])
        base_pay = round(base_bill * 0.7, 2)  # 30% margin
        placements_rates.extend([
            {"placement_id": p["placement_id"], "pay_code": "Standard", "bill_rate": base_bill, "pay_rate": base_pay},
            {"placement_id": p["placement_id"], "pay_code": "OT", "bill_rate": base_bill * 1.5, "pay_rate": round(base_pay * 1.5, 2)},
            {"placement_id": p["placement_id"], "pay_code": "DT", "bill_rate": base_bill * 2.0, "pay_rate": round(base_pay * 2.0, 2)}
        ])
        
    # 7. Placement Invoice Policy (AR)
    placements_invoice_policy = [
        {"placement_id": p["placement_id"], "billing_cycle": "Monthly", "invoice_format": "Consolidated"} for p in placements
    ]
    
    # 8. Placement AP Policy
    placement_ap_policy = [
        {"placement_id": p["placement_id"], "payment_cycle": "Semi-Monthly", "terms": "Net 15"} for p in placements if p["vendor_id"] is not None
    ]
    
    # 9 & 10. Timesheets & Daywise Details
    timesheets = []
    timesheets_daywise_details = []
    ts_id = 5000
    detail_id = 10000
    
    # Generate exactly 50 timesheets (5 per placement)
    for p in placements:
        for i in range(5):
            ts_id += 1
            # Jan/Feb 2026 timesheets
            start_date = date(2026, 1, 5) + timedelta(days=7*i)
            end_date = start_date + timedelta(days=6)
            
            # Status: Mostly Approved, some just Submitted
            status = "APPROVED" if random.random() > 0.2 else "SUBMITTED"
            
            # Invoice Flags
            ar_flag = 1 if status == "APPROVED" and random.random() > 0.6 else 0
            ap_flag = 1 if status == "APPROVED" and random.random() > 0.6 else 0
            
            total_hours = 0
            
            # Daywise breakdown (Mon-Fri)
            for day_offset in range(5): 
                current_day = start_date + timedelta(days=day_offset)
                std_hrs = 8
                ot_hrs = random.choice([0, 0, 0, 2, 4]) # Sprinkle some overtime
                
                total_hours += (std_hrs + ot_hrs)
                
                detail_id += 1
                timesheets_daywise_details.append({
                    "detail_id": detail_id,
                    "ts_id": ts_id,
                    "date": current_day.isoformat(),
                    "pay_code": "Standard",
                    "hours": std_hrs
                })
                
                if ot_hrs > 0:
                    detail_id += 1
                    timesheets_daywise_details.append({
                        "detail_id": detail_id,
                        "ts_id": ts_id,
                        "date": current_day.isoformat(),
                        "pay_code": "OT",
                        "hours": ot_hrs
                    })

            timesheets.append({
                "ts_id": ts_id,
                "placement_id": p["placement_id"],
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "status": status,
                "total_hours": total_hours,
                "ar_invoiced_flag": ar_flag,
                "ap_invoiced_flag": ap_flag
            })

    # 11. Expenses
    expenses = []
    exp_id = 8000
    for i in range(5):
        exp_id += 1
        p = random.choice(placements)
        expenses.append({
            "exp_id": exp_id,
            "placement_id": p["placement_id"],
            "date": "2026-02-12",
            "category": "Travel",
            "amount": round(random.uniform(50.0, 450.0), 2),
            "status": "APPROVED",
            "ar_invoiced_flag": 0,
            "ap_invoiced_flag": 0
        })
        
    # 12 & 13. Historical Invoices & Details (For Revenue Impact Cards)
    invoices = [
        {"invoice_id": "INV-2026-001", "client_id": 1, "status": "Paid", "total_amount": 18500.00, "issue_date": "2026-01-01", "due_date": "2026-01-31"},
        {"invoice_id": "INV-2026-002", "client_id": 1, "status": "Due", "total_amount": 14200.00, "issue_date": "2026-01-15", "due_date": "2026-02-15"},
        {"invoice_id": "INV-2026-003", "client_id": 2, "status": "Paid", "total_amount": 9400.00, "issue_date": "2026-01-05", "due_date": "2026-01-20"}
    ]
    
    invoice_details = [
        {"inv_detail_id": 1, "invoice_id": "INV-2026-001", "placement_id": 1001, "description": "Services", "amount": 18500.00},
        {"inv_detail_id": 2, "invoice_id": "INV-2026-002", "placement_id": 1002, "description": "Services", "amount": 14200.00},
        {"inv_detail_id": 3, "invoice_id": "INV-2026-003", "placement_id": 1005, "description": "Services", "amount": 9400.00}
    ]
    
    # 14 & 15. Historical Vendor Bills & Details
    vendor_bills = [
        {"bill_id": "BILL-2026-001", "vendor_id": 1, "status": "Paid", "total_amount": 12950.00, "issue_date": "2026-01-01"},
        {"bill_id": "BILL-2026-002", "vendor_id": 2, "status": "Due", "total_amount": 7100.00, "issue_date": "2026-01-15"}
    ]
    
    vendor_bills_details = [
        {"bill_detail_id": 1, "bill_id": "BILL-2026-001", "placement_id": 1001, "description": "Contractor Services", "amount": 12950.00},
        {"bill_detail_id": 2, "bill_id": "BILL-2026-002", "placement_id": 1003, "description": "Contractor Services", "amount": 7100.00}
    ]

    # 16. Discounts
    discounts = [
        {"discount_id": 1, "client_id": 1, "type": "Volume", "percentage": 5.0, "status": "Active"},
        {"discount_id": 2, "client_id": 2, "type": "Early Payment", "percentage": 2.0, "status": "Active"}
    ]

    # Package files and write to disk
    files = {
        "clients.json": clients, "vendors.json": vendors, "workers.json": workers,
        "workers_details.json": workers_details, "placements.json": placements,
        "placements_rates.json": placements_rates, "placements_invoice_policy.json": placements_invoice_policy,
        "placement_ap_policy.json": placement_ap_policy, "timesheets.json": timesheets,
        "timesheets_daywise_details.json": timesheets_daywise_details, "expenses.json": expenses,
        "invoices.json": invoices, "invoice_details.json": invoice_details,
        "vendor_bills.json": vendor_bills, "vendor_bills_details.json": vendor_bills_details,
        "discounts.json": discounts
    }
    
    for filename, data in files.items():
        with open(os.path.join("data", filename), "w") as f:
            json.dump(data, f, indent=2)
            
    print(f"✅ Successfully generated {len(files)} JSON database files in the /data directory!")

if __name__ == "__main__":
    generate_db()