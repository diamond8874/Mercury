import pandas as pd
from services.cleaning.intent_parser import build_cleaning_plan
from services.cleaning.executor import execute_plan

# Generate a small comprehensive dummy dataframe
df = pd.DataFrame({
    'Age': [25, 30, None, 45, 50, 50],
    'Name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve', 'Eve'],
    'Income': ['$50,000', '$60,000', '£70,000', None, '$90,000', '$90,000'],
    'Date': ['2021-01-01', '2021-02-01', 'invalid', '2021-04-01', '2021-05-01', '2021-05-01'],
    'IsActive': ['Yes', 'No', 'T', 'False', '1', '0'],
    'Category': ['A', 'B', 'A', 'C', 'B', 'B'],
    'Text': ['  hello world  ', 'TESTING', 'Some HTML <b>tag</b>', 'Punctuation!!!', 'Stopwords are here', 'Stopwords are here'],
    'Phone': ['+1 (555) 123-4567', '555-987-6543', 'invalid', '1234567890', '0987654321', '0987654321'],
    'Email': ['alice@example.com', 'bob@test.org', 'invalid', 'david@domain.com', 'eve@site.net', 'eve@site.net']
})

test_cases = [
    ("Age", "Drop column", "drop_column"),
    ("Age", "Rename to Years", "rename_column"),
    ("Age", "Move to front", "move_column_front"),
    ("Age", "Move to end", "move_column_end"),
    ("Age", "Drop if constant", "drop_constant_column"),
    ("Age", "Keep only Age", "keep_only_columns"),
    ("Age", "Normalize missing placeholders", "normalize_missing_placeholders"),
    ("Age", "Handle infinity", "handle_infinity"),
    ("Age", "Impute mean", "impute_mean"),
    ("Age", "Impute median", "impute_median"),
    ("Age", "Impute mode", "impute_mode"),
    ("Age", "Impute zero", "impute_zero"),
    ("Age", "Drop null rows", "drop_null_rows"),
    ("Name", "Drop duplicates", "drop_duplicates_full"),
    ("Text", "Convert to uppercase", "uppercase"),
    ("Text", "Convert to lowercase", "lowercase"),
    ("Text", "Convert to titlecase", "titlecase"),
    ("Text", "Strip whitespace", "strip_whitespace"),
    ("Text", "Remove punctuation", "remove_punctuation"),
    ("Text", "Remove html", "remove_html"),
    ("Text", "Remove stopwords", "remove_stopwords"),
    ("Text", "String length", "string_length"),
    ("Phone", "Extract digits", "extract_digits"),
    ("Email", "Extract email", "extract_email"),
    ("Phone", "Extract phone", "extract_phone"),
    ("Name", "Split column by space", "split_column"),
    ("Name", "Replace Alice with Alicia", "replace_value_exact"),
    ("Category", "One hot encode", "one_hot_encode"),
    ("Category", "Ordinal encode", "ordinal_encode"),
    ("Category", "Frequency encode", "frequency_encode"),
    ("Category", "Label encode", "label_encode"),
    ("IsActive", "Normalize boolean", "normalize_boolean"),
    ("Income", "Remove currency symbol", "remove_currency_symbol"),
    ("Age", "Normalize minmax", "normalize_minmax"),
    ("Age", "Standardize zscore", "standardize_zscore"),
    ("Age", "Log transform", "log_transform"),
    ("Age", "Round values", "round_values"),
    ("Age", "Convert datatype to string", "convert_datatype"),
    ("Date", "Standardize datetime", "standardize_datetime"),
    ("Date", "Extract year", "extract_year"),
    ("Age", "Sort data in ascending order", "sort_ascending"),
    ("Age", "Sort data in descending order", "sort_descending"),
    ("Date", "Calculate age", "calculate_age"),
    ("Name", "Anonymize text", "anonymize_text")
]

passed = 0
failed = 0

print("="*60)
print("RUNNING COMPREHENSIVE QUERY TESTS")
print("="*60)

for col, prompt, expected_op in test_cases:
    print(f"Testing: '{prompt}' on column '{col}'")
    try:
        # Build plan
        plan = build_cleaning_plan(col, prompt, df)
        if not plan:
            print(f"  [PARSE FAILED] Could not parse intent to plan.")
            failed += 1
            continue
            
        op_name = plan[0].get('operation')
        if op_name != expected_op:
            print(f"  [PARSE FAILED] Expected '{expected_op}' but got '{op_name}'.")
            failed += 1
            continue
            
        # Execute plan
        res = execute_plan(plan, df.copy())
        
        if res.get('errors'):
            print(f"  [EXEC FAILED] {res['errors']}")
            failed += 1
        elif res.get('warnings') and "skipped" in str(res.get('warnings')).lower():
            print(f"  [EXEC SKIPPED] {res['warnings']}")
            failed += 1
        else:
            print(f"  [SUCCESS] ({op_name}) executed perfectly.")
            passed += 1
    except Exception as e:
        print(f"  [SYSTEM CRASH] {str(e)}")
        failed += 1

print("="*60)
print(f"RESULTS: {passed} PASSED, {failed} FAILED")
print("="*60)
