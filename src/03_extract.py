# Step 3: use SQL (DuckDB) to pull 2013 data for 250 ToU + 250 Std homes out of all 168 files
import time
import duckdb

N_PER_GROUP = 250   # homes to sample from each tariff group
SEED = 42           # fixed seed, so every run picks the same homes
OUT = "data/interim/readings_2013_sample.parquet"

start = time.time()
con = duckdb.connect()   # in-memory DuckDB database: no server, nothing else to install

# 1. Treat all 168 CSV files as ONE table called "raw".
#    Nothing is loaded yet: DuckDB streams through the files only when a query runs.
#    We give the columns clean names (the original kWh name even ends in a hidden space)
#    and keep every value as text, so this step changes nothing in the data itself.
con.sql("""
    CREATE VIEW raw AS
    SELECT *
    FROM read_csv('data/raw/**/LCL-*.csv',
                  header = true,
                  names = ['household_id', 'tariff_group', 'ts_text', 'kwh_text'],
                  all_varchar = true)
""")

# 2. Which homes have readings in 2013, and in which tariff group?
#    Dates written as '2013-05-01 ...' sort like text, so a text comparison filters by date.
homes = con.sql("""
    SELECT household_id, tariff_group, COUNT(*) AS readings_2013
    FROM raw
    WHERE ts_text >= '2013-01-01' AND ts_text < '2014-01-01'
    GROUP BY household_id, tariff_group
    ORDER BY household_id
""").df()

print("Homes with 2013 data, by tariff group:")
print(homes["tariff_group"].value_counts().to_string())
print("Homes listed under both groups (should be 0):", homes["household_id"].duplicated().sum())

# 3. Random sample of homes from each group (pandas, fixed seed), saved for the record
sample = homes.groupby("tariff_group").sample(n=N_PER_GROUP, random_state=SEED)
sample.to_csv("data/interim/sample_households.csv", index=False)

# 4. Pull only the sampled homes' 2013 rows and save them as one Parquet file
con.register("sample_homes", sample)
con.sql(f"""
    COPY (
        SELECT r.*
        FROM raw AS r
        JOIN sample_homes AS s USING (household_id)
        WHERE r.ts_text >= '2013-01-01' AND r.ts_text < '2014-01-01'
        ORDER BY r.household_id, r.ts_text
    ) TO '{OUT}' (FORMAT parquet)
""")

# 5. Check what we saved
print()
print(con.sql(f"""
    SELECT tariff_group,
           COUNT(DISTINCT household_id) AS homes,
           COUNT(*)                     AS readings,
           MIN(ts_text)                 AS first_reading,
           MAX(ts_text)                 AS last_reading
    FROM '{OUT}'
    GROUP BY tariff_group
    ORDER BY tariff_group
""").df().to_string(index=False))
print(f"\nDone in {time.time() - start:.0f} seconds")