# Step 8: did the 2013 price signals change how ToU homes used electricity?
# Flat-rate (Std) homes saw no prices, so they show what weather, holidays and time of day
# do on their own. We compare ToU with Std at every half-hour, in High/Low-price periods
# versus normal-price periods at the same clock time and month.
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

IN = "data/clean/readings_2013_final.parquet"
N_BOOT = 200    # resamples for the uncertainty range
SEED = 42

# ---- 1. Load the 2013 price schedule and look at it first ---------------------------
files = [f for f in Path("data/raw").rglob("*")
         if "tariff" in f.name.lower() and f.suffix in (".xlsx", ".xls", ".csv")]
if not files:
    raise SystemExit("No Tariffs file in data/raw. Download 'Tariffs' from the London Datastore page.")
raw = pd.read_csv(files[0]) if files[0].suffix == ".csv" else pd.read_excel(files[0])
# The price column is the one holding High / Low / Normal; the time column has date or time in its name
price_col = next(c for c in raw.columns
                 if raw[c].astype(str).str.strip().str.lower().isin(["high", "low", "normal"]).mean() > 0.9)
time_col = next((c for c in raw.columns if "date" in str(c).lower() or "time" in str(c).lower()),
                [c for c in raw.columns if c != price_col][0])
tariffs = pd.DataFrame({"slot_start": pd.to_datetime(raw[time_col], dayfirst=True),   # UK dates are day-first
                        "price": raw[price_col].astype(str).str.strip().str.title()})
tariffs = tariffs[tariffs["slot_start"].dt.year == 2013].sort_values("slot_start")
dupes = tariffs["slot_start"].duplicated().sum()             # e.g. a repeated hour on a clock-change day
tariffs = tariffs.drop_duplicates("slot_start").reset_index(drop=True)
print(f"Tariff file: {files[0].name} | columns {list(raw.columns)} | 2013 half-hours: {len(tariffs):,} "
      f"| duplicate times dropped: {dupes}")
print(tariffs["price"].value_counts().to_string())

# Group consecutive half-hours with the same price into events (the Step 5 run trick again)
tariffs["event_id"] = (tariffs["price"] != tariffs["price"].shift()).cumsum()
events = (tariffs[tariffs["price"] != "Normal"].groupby("event_id")
          .agg(price=("price", "first"), start=("slot_start", "min"), slots=("slot_start", "size")))
print("\nPrice events:")
print(events.groupby("price").agg(events=("slots", "size"),
                                  median_hours=("slots", lambda s: s.median() / 2)).to_string())
for p in ["High", "Low"]:
    common = events.loc[events["price"] == p, "start"].dt.strftime("%H:%M").value_counts().head(3)
    print(f"Most common {p} start times: {common.to_dict()}")

# ---- 2. One row per home, one column per half-hour ----------------------------------
df = pd.read_parquet(IN)
df["slot_start"] = df["ts"] - pd.Timedelta(minutes=30)   # Step 7: a reading covers the 30 min before its stamp
wide = df.pivot_table(index="household_id", columns="slot_start", values="kwh")
group_of = df.drop_duplicates("household_id").set_index("household_id")["tariff_group"]
tou = wide[group_of.reindex(wide.index) == "ToU"].to_numpy()
std = wide[group_of.reindex(wide.index) == "Std"].to_numpy()
slots = wide.columns
month, hour = slots.month.to_numpy(), (slots.hour + slots.minute / 60).to_numpy()
schedule = tariffs.set_index("slot_start")["price"]
price = schedule.reindex(slots).to_numpy()                # price in force during each half-hour
matched = pd.notna(price).mean()
print(f"\nHalf-hours of readings matched to a price: {matched:.1%}")
if matched < 0.9:
    raise SystemExit(f"Too few matches. Tariff times look like {schedule.index[:2].tolist()}, "
                     f"reading half-hours like {slots[:2].tolist()}")

# ---- 3. The estimate -----------------------------------------------------------------
def relative_use(tou_avg, std_avg, price):
    """ToU use relative to Std at each half-hour, divided by its usual value in normal-price
    half-hours of the same month and clock time. 1.0 = behaving as usual; 0.9 = 10% less."""
    ratio = tou_avg / std_avg
    normal = price == "Normal"
    usual = pd.Series(ratio[normal]).groupby([month[normal], hour[normal]]).mean()
    expected = usual.reindex(pd.MultiIndex.from_arrays([month, hour])).to_numpy()
    return ratio / expected

def effects(rel, price):
    return {p: np.nanmean(rel[price == p]) - 1 for p in ["High", "Low"]}

tou_avg, std_avg = np.nanmean(tou, axis=0), np.nanmean(std, axis=0)
rel = relative_use(tou_avg, std_avg, price)
estimate = effects(rel, price)

# The "four averages" behind it (kW per home), for intuition
four = pd.DataFrame({p: {"ToU homes": np.nanmean(tou_avg[price == p]) * 2,
                         "Std homes": np.nanmean(std_avg[price == p]) * 2} for p in ["High", "Normal", "Low"]}).T
four["ToU / Std"] = four["ToU homes"] / four["Std homes"]
print("\nThe four averages (kW per home):")
print(four.round(3).to_string())

# Uncertainty: resample homes with replacement and recompute, N_BOOT times
rng = np.random.default_rng(SEED)
boot = []
for _ in range(N_BOOT):
    t = np.nanmean(tou[rng.integers(0, len(tou), len(tou))], axis=0)
    s = np.nanmean(std[rng.integers(0, len(std), len(std))], axis=0)
    boot.append(effects(relative_use(t, s, price), price))
boot = pd.DataFrame(boot)

# Sensitivity: what if the tariff times marked the END of each half-hour instead of the start?
price_alt = schedule.reindex(slots + pd.Timedelta(minutes=30)).to_numpy()
alt = effects(relative_use(tou_avg, std_avg, price_alt), price_alt)

summary = pd.DataFrame({
    "effect_pct": {p: 100 * estimate[p] for p in estimate},
    "low_95_pct": 100 * boot.quantile(0.025),
    "high_95_pct": 100 * boot.quantile(0.975),
    "half_hours": {p: int((price == p).sum()) for p in estimate},
    "events": events["price"].value_counts(),
    "if_tariff_times_were_ends_pct": {p: 100 * alt[p] for p in alt},
}).round(1)
print("\nResponse of ToU homes vs usual (negative = used less):")
print(summary.to_string())
summary.to_csv("reports/analysis/price_response.csv")
for p in ["High", "Low"]:
    word = "less" if summary.loc[p, "effect_pct"] < 0 else "more"
    print(f"\n{p} price: ToU homes used {abs(summary.loc[p, 'effect_pct']):.1f}% {word} than usual "
          f"(95% range {summary.loc[p, 'low_95_pct']:.1f}% to {summary.loc[p, 'high_95_pct']:.1f}%)")

# ---- 4. Chart: what happened around the start of each event --------------------------
BLUE = "#2a78d6"
SURFACE, INK, INK_2, GRID, AXIS, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#f0efec"
rel_by_time = pd.Series(rel, index=slots)
offsets = np.arange(-4, 13)                                  # 2 hours before to 6 hours after the start

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True, facecolor=SURFACE)
for ax, p in zip(axes, ["High", "Low"]):
    starts = events.loc[events["price"] == p, "start"].to_numpy()
    times = starts[:, None] + offsets[None, :] * np.timedelta64(30, "m")
    values = rel_by_time.reindex(times.ravel()).to_numpy().reshape(times.shape)
    curve = (np.nanmean(values, axis=0) - 1) * 100
    typical_hours = events.loc[events["price"] == p, "slots"].median() / 2
    ax.axvspan(0, typical_hours, color=BAND, lw=0, zorder=0)
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.plot(offsets / 2 + 0.25, curve, color=BLUE, lw=1.5)   # each half-hour at its midpoint
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.set_xlabel(f"Hours from the start of a {p.lower()}-price event "
                  f"(shaded: typical length, {typical_hours:g} h)", color=INK_2, fontsize=9)
    ax.set_title(f"{p} price: {summary.loc[p, 'effect_pct']:+.1f}% vs usual", loc="left",
                 fontsize=10, color=INK)
axes[0].set_ylabel("ToU homes' use vs usual (%)", color=INK_2, fontsize=9)
fig.suptitle("How ToU homes responded to day-ahead price signals in 2013 (flat-rate homes as control)",
             x=0.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94))
Path("reports/figures").mkdir(parents=True, exist_ok=True)
fig.savefig("reports/figures/price_response.png", dpi=150, facecolor=SURFACE)
print("\nSaved reports/analysis/price_response.csv and reports/figures/price_response.png")