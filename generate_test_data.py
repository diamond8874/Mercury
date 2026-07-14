import pandas as pd
import numpy as np
import random

# Seed for reproducibility
np.random.seed(42)
random.seed(42)

# Size of dataset
n_rows = 150

# Generate columns
ids = [f"USR_{uuid_hash:06d}" for uuid_hash in range(1000, 1000 + n_rows)]
names = ["John Doe", "Jane Smith", "Bob Jones", "Alice Green", "Charlie Brown", "Emily White"]
random_names = [random.choice(names) + f" {random.randint(1,100)}" for _ in range(n_rows)]

age = np.random.randint(18, 70, size=n_rows)
# Add some missing values to age
age_with_nulls = [x if random.random() > 0.05 else None for x in age]

gender = [random.choice(["Male", "Female", None]) for _ in range(n_rows)] # Contains nulls

monthly_fee = np.round(np.random.uniform(20.0, 120.0, size=n_rows), 2)
# Useless noise column
random_noise = np.random.normal(0, 1, size=n_rows)
# Fully empty column
all_empty = [None] * n_rows

# Date column stored as string
date_strings = [f"2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}" for _ in range(n_rows)]

# Target (Churn) related to age & monthly fee
churn = []
for a, f in zip(age, monthly_fee):
    # Probability of churn increases with monthly fee and age
    prob = 0.1
    if f > 80:
        prob += 0.4
    if a > 50:
        prob += 0.2
    churn.append(1 if random.random() < prob else 0)

# Create DataFrame
df = pd.DataFrame({
    "User_ID_Hash": ids,                  # Should be dropped
    "Customer_Profile_Name": random_names, # Should be dropped
    "Age": age_with_nulls,                # Should keep & transform/impute
    "Gender": gender,                     # Should keep & transform
    "Monthly_Subscription_Fee": monthly_fee,# Should keep
    "Duplicated_Fee": monthly_fee,        # Should be dropped
    "System_Noise_Signal": random_noise,  # Should be dropped
    "Null_Column_All_Empty": all_empty,   # Should be dropped
    "Registration_Date": date_strings,    # Should be transformed to datetime
    "Churned_Status": churn               # Target (Keep)
})

# Save to Excel
output_file = "test_dirty_data.xlsx"
df.to_excel(output_file, index=False)
print(f"Dirty test dataset successfully generated and saved to: {output_file}")
print(f"Shape: {df.shape}")
