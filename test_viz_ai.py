import requests
import json
import time

import os

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

    print("2. Processing data...")
    process_payload = {
        "session_id": session_id,
        "actions": {"Model_Year": {"action": "keep", "reason": "", "transformation": ""}}
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

    print("\n3. Testing AI Text-to-Chart API...")
    viz_chat_payload = {
        "message": "Show me a pie chart of Salary",
        "api_key": ""
    }
    viz_chat_res = requests.post(f"{base_url}/api/sessions/{session_id}/viz_chat", json=viz_chat_payload)

    if viz_chat_res.status_code != 200:
        print("Viz Chat failed:", viz_chat_res.text)
        exit(1)

    res_json = viz_chat_res.json()
    print("Parsed Parameters from AI:")
    print(json.dumps(res_json, indent=2))

    if "params" in res_json:
        print("\n4. Triggering actual visual rendering with parsed parameters...")
        viz_res = requests.post(f"{base_url}/api/sessions/{session_id}/custom_chart", json=res_json["params"])

        if viz_res.status_code != 200:
            print("Chart Rendering failed:", viz_res.text)
            exit(1)

        chart_json = viz_res.json()
        print("Success:", chart_json.get("success"))
        print("Chart Type:", chart_json.get("chart", {}).get("type"))
        print("Chart Data length:", len(chart_json.get("chart", {}).get("data", "")))

