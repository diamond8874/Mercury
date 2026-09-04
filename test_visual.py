import requests
import json
import time
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

base_url = "http://localhost:5000"
file_path = r"C:\Users\ACER\OneDrive\Desktop\MIT\EV_Dataset.csv"
if not os.path.exists(file_path):
    file_path = os.path.join(os.path.dirname(__file__), "test_dirty_data.xlsx")

if __name__ == "__main__":
    print("1. Uploading file...")
    with open(file_path, "rb") as f:
        files = {"file": f}
        upload_res = requests.post(f"{base_url}/api/upload", files=files)

    session_id = upload_res.json()["session_id"]
    print(f"Session ID: {session_id}")

    cols = upload_res.json().get("columns", [])
    num_cols = [c["name"] for c in cols if 'int' in c.get("type", "").lower() or 'float' in c.get("type", "").lower()]
    cat_cols = [c["name"] for c in cols if c["name"] not in num_cols]

    first_col = cat_cols[0] if cat_cols else (cols[0]["name"] if cols else "Model_Year")
    second_col = num_cols[0] if num_cols else (cols[1]["name"] if len(cols) > 1 else first_col)

    print("2. Processing data...")
    process_payload = {
        "session_id": session_id,
        "actions": {first_col: {"action": "keep", "reason": "", "transformation": ""}}
    }
    process_res = requests.post(f"{base_url}/api/process", json=process_payload)
    print(f"Process Response: {process_res.status_code}")

    print("Waiting for processing to finish...")
    for i in range(15):
        status_res = requests.get(f"{base_url}/api/sessions/{session_id}/status")
        status = status_res.json().get("status")
        print(f"Status: {status}")
        if status == "done":
            break
        time.sleep(2)

    print(f"\n3. Requesting a Bar Chart (comparison, bar) for {first_col} and {second_col}...")
    viz_payload = {
        "chart_category": "comparison",
        "chart_type": "bar",
        "x_col": first_col,
        "y_col": second_col
    }
    viz_res = requests.post(f"{base_url}/api/sessions/{session_id}/custom_chart", json=viz_payload)

    if viz_res.status_code != 200:
        print("Viz failed:", viz_res.text)
        exit(1)

    res_json = viz_res.json()
    print("Success:", res_json.get("success"))
    print("Chart Type:", res_json.get("chart", {}).get("type"))
    print("Chart Data length:", len(res_json.get("chart", {}).get("data", "")))

