# Step 11 (part A): the small files the dashboard needs. The Parquet files stay on your laptop
# (data/ is git-ignored and too big for a free cloud app), so we pre-compute what the app shows
# and commit only these few hundred KB.
from pathlib import Path
import duckdb
import pandas as pd

OUT = Path("app/data")
OUT.mkdir(parents=True, exist_ok=True)

# ---- 1. Each home's average day: kW in each half-hour (443 homes x 48 = ~21k rows) ----
curves = duckdb.sql("""
    SELECT household_id,
           hour(ts - INTERVAL 30 MINUTE) + minute(ts - INTERVAL 30 MINUTE) / 60.0 AS hour_of_day,
           ROUND(AVG(kwh) * 2, 4) AS avg_kw
    FROM 'data/clean/readings_2013_final.parquet'
    GROUP BY ALL
    ORDER BY ALL
""").df()
curves.to_csv(OUT / "home_curves.csv", index=False)

# ---- 2. The cleaning funnel: readings and homes left after each stage ----------------
stages = [("Raw sample (Step 3)", "data/interim/readings_2013_sample.parquet"),
          ("After cleaning rules (Step 5)", "data/clean/readings_2013_clean.parquet"),
          ("After AI-assisted fault removal (Step 6)", "data/clean/readings_2013_final.parquet")]
rows = []
for stage, path in stages:
    readings, homes = duckdb.sql(f"SELECT COUNT(*), COUNT(DISTINCT household_id) FROM '{path}'").fetchone()
    rows.append({"stage": stage, "readings": readings, "homes": homes})
funnel = pd.DataFrame(rows)
funnel.to_csv(OUT / "funnel.csv", index=False)

# ---- 3. How well the AI's flags matched the fault rule (Step 6), from saved reports ---
# The rule: 6+ hours of zeros (zero_share >= 0.25, i.e. 12 of 48 half-hours) or 6+ hours
# stuck on one value. Any 6-hour flat run on a day with under 6 zero hours can't be zeros,
# so on the flagged days this is exactly Step 6B's rule.
flags = pd.read_csv("reports/anomaly_days.csv")
flags["fault"] = (flags["zero_share"] >= 0.25) | (flags["longest_flat_h"] >= 6)
fault_log = pd.read_csv("reports/fault_log.csv")
fault_days = int(fault_log.loc[fault_log["rule"].str.startswith("fault days"), "affected"].iloc[0])
ai = pd.DataFrame([{"flagged_days": len(flags), "flagged_that_were_faults": int(flags["fault"].sum()),
                    "fault_days": fault_days}])
ai.to_csv(OUT / "ai_vs_rule.csv", index=False)

print(f"home_curves.csv: {len(curves):,} rows, {curves['household_id'].nunique()} homes")
print("\nfunnel.csv:")
print(funnel.to_string(index=False))
r = ai.iloc[0]
print(f"\nai_vs_rule.csv: {r.flagged_that_were_faults / r.flagged_days:.0%} of AI flags were faults; "
      f"the flags covered {r.flagged_that_were_faults / r.fault_days:.0%} of all fault days "
      "(these should match your Step 6 output)")
size_kb = sum(f.stat().st_size for f in OUT.glob("*.csv")) / 1024
print(f"\nSaved 3 files to {OUT}/ ({size_kb:,.0f} KB in total)")