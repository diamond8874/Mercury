import json
import json_repair

raw = """```json
{
  "message": "The dataset will be sorted in ascending order by the Age column as you requested.",
  "schema_updates": {
    "Age": {
      "action": "transform",
      "reason": "Sort data in ascending order",
      "transformation": "Sort data in ascending order"
    }
  }
}
```"""

try:
    data = json_repair.loads(raw)
    print("REPAIRED:", type(data), data)
except Exception as e:
    print("ERROR:", e)
