import requests
import json
import time

base_url = "http://localhost:5000"
file_path = r"C:\Users\ACER\OneDrive\Desktop\MIT\EV_Dataset.csv"

if __name__ == "__main__":
    print("1. Uploading file...")
    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            upload_res = requests.post(f"{base_url}/api/upload", files=files)
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        exit(1)

    if upload_res.status_code != 200:
        print("Upload failed:", upload_res.text)
        exit(1)

    session_id = upload_res.json()["session_id"]
    print(f"Session ID: {session_id}")

    print("\n2. Sending chat prompt: 'remove date column'...")
    chat_payload = {
        "message": "remove date column",
        "api_key": ""
    }
    chat_res = requests.post(f"{base_url}/api/sessions/{session_id}/chat", json=chat_payload)

    if chat_res.status_code != 200:
        print("Chat failed:", chat_res.text)
        exit(1)

    res_json = chat_res.json()
    print("\n--- AI Response ---")
    print(res_json.get("message"))
    print("\n--- Schema Updates ---")
    print(json.dumps(res_json.get("schema_updates", {}), indent=2))

