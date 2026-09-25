"""
baseline_engine.py — The Python Muscle
======================================
This module generates a 95% complete data cleaning plan using standard
data science heuristics. It analyzes the schema metadata (not the full DataFrame)
and produces a JSON-compatible list of operations.
"""

import re

def generate_baseline_plan(schema_summary, row_count, goal=""):
    """
    Generates a deterministic baseline cleaning plan based on schema heuristics.
    Returns a list of dictionaries matching the JSON schema expected by the executor.
    """
    recommendations = []
    
    # Regex patterns for advanced heuristics
    date_pattern = re.compile(r'^\d{4}[-/]\d{2}[-/]\d{2}.*$')
    email_pattern = re.compile(r'^[\w\.-]+@[\w\.-]+\.\w+$')
    
    for col_info in schema_summary:
        col = col_info.get("column_name")
        if col.startswith("[..."):
            continue
            
        dtype = str(col_info.get("data_type", "")).lower()
        null_pct = float(col_info.get("null_percentage", 0.0))
        unique_count = int(col_info.get("unique_values_count", 0))
        samples = col_info.get("sample_values", [])
        
        # Strip <untrusted_sample_value> tags for regex checking
        clean_samples = []
        for s in samples:
            clean = str(s).replace("<untrusted_sample_value>", "").replace("</untrusted_sample_value>", "")
            if clean and str(clean).lower() not in ["nan", "none", "null"]:
                clean_samples.append(clean)
            
        action = "keep"
        reason = "Column appears standard; keeping by default."
        operations = []
        
        is_numeric = any(x in dtype for x in ["int", "float", "numeric"])
        is_object = "object" in dtype or "string" in dtype
        
        # Rule 1: Drop empty or mostly empty columns
        if null_pct >= 60.0:
            action = "drop"
            reason = f"Statistical Rule: Column has {null_pct}% missing values (>= 60% threshold)."
        
        # Rule 2: Drop constant columns
        elif unique_count == 1:
            action = "drop"
            reason = "Statistical Rule: Column has only 1 unique value (zero variance)."
            
        # Rule 3: Drop high cardinality text (likely IDs/Names)
        elif is_object and unique_count == row_count and row_count > 100:
            action = "drop"
            reason = "Statistical Rule: All values are unique text (likely an ID or Name), low predictive value."
            
        # Rule 4: Email extraction
        elif is_object and clean_samples and all(email_pattern.match(s) for s in clean_samples):
            action = "transform"
            reason = "Pattern Rule: Detected email addresses. Extracting emails for normalization."
            operations.append({"operation": "extract_email", "parameters": {}})
            
        # Rule 5: Date parsing
        elif is_object and clean_samples and all(date_pattern.match(s) for s in clean_samples):
            action = "transform"
            reason = "Pattern Rule: Detected date strings. Standardizing to datetime format."
            operations.append({"operation": "standardize_datetime", "parameters": {}})
            
        # Rule 6: One-hot encode low cardinality categorical
        elif is_object and 1 < unique_count <= 15:
            action = "transform"
            reason = f"Statistical Rule: Low cardinality categorical feature ({unique_count} unique values). One-hot encoding recommended."
            operations.append({"operation": "encode", "parameters": {"method": "one_hot"}})
            
        # Rule 7: Impute missing numerics with median
        elif is_numeric and 0 < null_pct < 60.0:
            action = "transform"
            reason = f"Statistical Rule: Numeric column has {null_pct}% missing values. Imputing with median."
            operations.append({"operation": "impute", "parameters": {"method": "median"}})
            
        recommendations.append({
            "column": col,
            "action": action,
            "reason": reason,
            "transformation": "Automated pipeline heuristic" if action == "transform" else None,
            "operations": operations
        })
        
    return recommendations
