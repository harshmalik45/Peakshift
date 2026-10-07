# Step 2: look at the raw data before changing anything
from pathlib import Path
import pandas as pd

# 1. What did we download?
files = sorted(Path("data/raw").rglob("*.csv"))
print("CSV files:", len(files))
print("Total size (GB):", round(sum(f.stat().st_size for f in files) / 1e9, 2))

# 2. Read ONE file, every column as plain text,
#    so pandas doesn't silently convert anything we need to see
df = pd.read_csv(files[0], dtype=str, keep_default_na=False)
print("\nFile:", files[0].name)
print("Rows, columns:", df.shape)

# 3. Column names. repr() puts quotes around them, so hidden spaces show up
print("\nColumn names:")
for col in df.columns:
    print("  ", repr(col))

# 4. What the rows look like
print("\nFirst 5 rows:")
print(df.head().to_string())

# 5. How many different values each column has
print("\nDistinct values per column:")
print(df.nunique().to_string())

# 6. Full counts for columns with only a few different values (categories)
for col in df.columns:
    if df[col].nunique() <= 20:
        print(f"\nValue counts for {col!r}:")
        print(df[col].value_counts().to_string())