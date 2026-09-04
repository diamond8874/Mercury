import sys
import requests
import json
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://localhost:5000"

def test_pin_and_report_flow():
    print("1. Uploading dataset...")
    test_file = "test_dirty_data.xlsx"
    if not os.path.exists(test_file):
        print(f"Error: {test_file} not found.")
        return

    with open(test_file, "rb") as f:
        resp = requests.post(f"{BASE_URL}/api/upload", files={"file": f})
    
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    session_id = resp.json()["session_id"]
    print(f"Session ID: {session_id}")

    cols = resp.json().get("columns", [])
    col_name = cols[0]["name"] if cols else "Department"

    print("2. Processing dataset...")
    proc_resp = requests.post(f"{BASE_URL}/api/process", json={
        "session_id": session_id,
        "actions": {col_name: {"action": "keep", "reason": "", "transformation": ""}},
        "api_key": "MOCK"
    })
    assert proc_resp.status_code == 200, f"Process failed: {proc_resp.text}"

    import time
    for _ in range(10):
        st = requests.get(f"{BASE_URL}/api/sessions/{session_id}/status").json().get("status")
        if st == "done": break
        time.sleep(1)

    print("3. Generating Custom Waterfall Visual...")
    chart_resp = requests.post(f"{BASE_URL}/api/sessions/{session_id}/custom_chart", json={
        "chart_category": "change_flow",
        "chart_type": "waterfall",
        "x_col": "Department",
        "y_col": "Salary"
    })
    assert chart_resp.status_code == 200, f"Custom chart failed: {chart_resp.text}"
    chart_data = chart_resp.json()
    print(f"Custom Chart Generated Success: {chart_data.get('success')}")

    print("4. Pinning Visual to PDF Report...")
    pin_payload = {
        "chart": {
            "title": "Salary by Department (WATERFALL)",
            "chart_type": "waterfall",
            "x_axis": "Department",
            "y_axis": "Salary",
            "description": "Waterfall chart pinned by user"
        }
    }
    pin_resp = requests.post(f"{BASE_URL}/api/sessions/{session_id}/pin_chart", json=pin_payload)
    assert pin_resp.status_code == 200, f"Pin failed: {pin_resp.text}"
    pin_res = pin_resp.json()
    print(f"Pin Response: {pin_res['message']} (Total Pinned: {pin_res['pinned_count']})")

    print("5. Generating Custom PDF Report with Pinned Visuals...")
    pdf_resp = requests.post(f"{BASE_URL}/api/sessions/{session_id}/pdf")
    assert pdf_resp.status_code == 200, f"PDF generation failed: {pdf_resp.text}"
    pdf_res = pdf_resp.json()
    print(f"PDF Generated Success: {pdf_res['pdf_url']}")

    print("\n✅ PIN & REPORT TEST PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_pin_and_report_flow()
