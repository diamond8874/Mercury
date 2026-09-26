from services.cleaning.intent_parser import build_cleaning_plan
import pandas as pd
df = pd.DataFrame({'Gender': [0, 1, 0, 1, 1]})
tests = [
    'change 0 to Male and 1 to Female',
    'replace 0 with Male and 1 with Female',
    'change value 0 to Male and 1 to Female',
    '0 to Male, 1 to Female',
    'map 0 as Male and 1 as Female',
    'change value of 0 and 1 into Male and Female',
    'convert 0 to Male and 1 to Female',
    '0 -> Male, 1 -> Female',
]
for t in tests:
    plan = build_cleaning_plan('Gender', t, df)
    print(f"Prompt: {t!r}")
    if plan:
        op = plan[0].get('operation')
        params = plan[0].get('parameters', {})
        print(f"  op: {op}, mapping: {params.get('mapping', 'N/A')}")
    else:
        print("  -> NO PLAN")
    print()
