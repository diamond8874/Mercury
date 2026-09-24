import pytest
import pandas as pd
from services.cleaning.intent_parser import build_cleaning_plan
from services.data_service import apply_column_transformation

def test_round_off_intent_parsing():
    """Verify 'Round off to nearest whole number' is correctly parsed into round_values with 0 decimals."""
    df = pd.DataFrame({"AlcoholConsumption": [13.297, 4.542]})
    step_str = "Round off all numerical values in the AlcoholConsumption column to the nearest whole number"
    plan = build_cleaning_plan("AlcoholConsumption", step_str, df)

    assert len(plan) > 0
    assert plan[0]["operation"] == "round_values"
    assert plan[0]["parameters"].get("decimals") == 0

def test_round_values_execution():
    """Verify apply_column_transformation rounds float numbers and removes decimal point when 0 decimals requested."""
    df = pd.DataFrame({
        "AlcoholConsumption": [13.29721772827684, 4.542523817722191, 19.55508452555359]
    })
    
    cleaned_df, msg = apply_column_transformation(
        df, "AlcoholConsumption", 
        "Round off all numerical values in the AlcoholConsumption column to the nearest whole number"
    )

    assert cleaned_df["AlcoholConsumption"].tolist() == [13, 5, 20]

def test_chat_route_handles_round_off(client):
    """Verify chat route parses 'round off' instructions and updates column actions."""
    df = pd.DataFrame({
        "AlcoholConsumption": [13.29721772827684, 4.542523817722191]
    })
    import io
    csv_buf = io.BytesIO()
    df.to_csv(csv_buf, index=False)
    csv_buf.seek(0)

    upload_res = client.post('/api/upload', data={'file': (csv_buf, 'alcohol.csv')}, content_type='multipart/form-data')
    session_id = upload_res.get_json()["session_id"]

    chat_payload = {
        "message": "Round off all numerical values in the AlcoholConsumption column to the nearest whole number",
        "api_key": "MOCK"
    }
    chat_res = client.post(f'/api/sessions/{session_id}/chat', json=chat_payload)
    assert chat_res.status_code == 200
    res_data = chat_res.get_json()

    assert "AlcoholConsumption" in res_data.get("schema_updates", {})
    assert res_data["schema_updates"]["AlcoholConsumption"]["action"] == "transform"
