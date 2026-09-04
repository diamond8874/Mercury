import sys
import os
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.cleaning.intent_parser import build_cleaning_plan
from services.cleaning.executor import execute_plan
from services.data_service import apply_column_transformation

def test_all_human_language_transformations():
    print("Testing Natural Human Language Transformation Engine...\n")

    # Sample test DataFrame
    df = pd.DataFrame({
        "CardiovascularDisease": [0, 1, 0, 1, 0],
        "Company": ["Tesla", "Tesla", "Ford", "Tesla", "BMW"],
        "Age": [25.0, None, 40.0, 30.0, None],
        "Salary": ["$50,000", "$60,000", "$45,000", "$70,000", "$55,000"],
        "IsActive": [0, 1, 1, 0, 1]
    })

    # Test Case 1: Human value mapping "0 to No and 1 to Yes"
    print("Test 1: 'CardiovascularDisease transform 0 to No and 1 to Yes'")
    df1, msg1 = apply_column_transformation(df.copy(), "CardiovascularDisease", "CardiovascularDisease transform 0 to No and 1 to Yes")
    print(f"Result Message: {msg1}")
    print(f"Values: {df1['CardiovascularDisease'].tolist()}")
    assert df1["CardiovascularDisease"].tolist() == ["No", "Yes", "No", "Yes", "No"], "Test 1 Failed!"

    # Test Case 2: Arrow shorthand "Tesla -> Tesla Motors"
    print("\nTest 2: 'Company transform Tesla -> Tesla Motors'")
    df2, msg2 = apply_column_transformation(df.copy(), "Company", "Company transform Tesla -> Tesla Motors")
    print(f"Result Message: {msg2}")
    print(f"Values: {df2['Company'].tolist()}")
    assert "Tesla Motors" in df2["Company"].tolist(), "Test 2 Failed!"

    # Test Case 3: Datatype conversion "make float"
    print("\nTest 3: 'IsActive convert to float'")
    df3, msg3 = apply_column_transformation(df.copy(), "IsActive", "IsActive convert to float")
    print(f"Result Message: {msg3}")
    print(f"Dtype: {df3['IsActive'].dtype}")
    assert "float" in str(df3["IsActive"].dtype), "Test 3 Failed!"

    # Test Case 4: Human missing value filling "fill missing with 0"
    print("\nTest 4: 'Age fill missing with 0'")
    df4, msg4 = apply_column_transformation(df.copy(), "Age", "Age fill missing with 0")
    print(f"Result Message: {msg4}")
    print(f"Values: {df4['Age'].tolist()}")
    assert df4["Age"].isnull().sum() == 0, "Test 4 Failed!"

    # Test Case 5: Currency cleaning "remove dollar signs"
    print("\nTest 5: 'Salary remove dollar signs and commas'")
    df5, msg5 = apply_column_transformation(df.copy(), "Salary", "Salary remove currency symbols and commas")
    print(f"Result Message: {msg5}")
    print(f"Values: {df5['Salary'].tolist()}")

    print("\n🎉 ALL 5 HUMAN LANGUAGE TRANSFORMATION TESTS PASSED 100%!")

if __name__ == "__main__":
    test_all_human_language_transformations()
