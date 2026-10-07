# Step 7: run every query in sql/07_analysis.sql, save each result, draw three charts.
from pathlib import Path
import duckdb
import matplotlib.pyplot as plt

SQL_FILE = Path("sql/07_analysis.sql")
OUT = Path("reports/analysis")
FIG = Path("reports/figures")
OUT.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

# ---- 1. Run the named SQL blocks in order ----------------------------------------
con = duckdb.connect()
results = {}
for block in SQL_FILE.read_text().split("\n-- name: ")[1:]:   # a new block starts on each "-- name:" line
    name, sql = block.split("\n", 1)
    name = name.strip()
    if name.startswith("setup"):            # creates a view; nothing to save
        con.execute(sql)
        continue
    df = con.sql(sql).df()
    df.to_csv(OUT / f"{name}.csv", index=False)
    results[name] = df
    print(f"\n=== {name} ===")
    if len(df) <= 12:
        print(df.to_string(index=False))
    else:
        print(f"({len(df)} rows, saved to {OUT / name}.csv)")

# A few headline numbers from the long tables
def clock(h):                                   # 18.5 -> "18:30"
    return f"{int(h):02d}:{int(round(h % 1 * 60)):02d}"

curve = results["daily_curve"]
busiest = curve.nsmallest(3, "busiest_rank")
quietest = curve.nsmallest(1, "all_days_kw").iloc[0]
print("\nBusiest half-hours:",
      ", ".join(f"{clock(h)}-{clock(h + 0.5)} ({kw:.2f} kW)"
                for h, kw in zip(busiest["hour_of_day"], busiest["all_days_kw"])))
print(f"Quietest half-hour: {clock(quietest.hour_of_day)}-{clock(quietest.hour_of_day + 0.5)} "
      f"({quietest.all_days_kw:.2f} kW)")
print(f"Busiest / quietest: {busiest['all_days_kw'].iloc[0] / quietest.all_days_kw:.1f}x")

# ---- 2. Charts (same style as Step 6) ---------------------------------------------
BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, INK_2, GRID, AXIS, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#f0efec"

def style(ax, ylabel):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.set_ylabel(ylabel, color=INK_2, fontsize=9)
    ax.set_ylim(bottom=0)

# Chart 1: daily curve, weekday vs weekend, with J&K's ToD slots behind it
fig, ax = plt.subplots(figsize=(10, 4.8), facecolor=SURFACE)
for start, end in [(6, 9), (17, 22)]:
    ax.axvspan(start, end, color=BAND, lw=0, zorder=0)
for x, label in [(7.5, "Peak +10%"), (13, "Solar hours −20%"), (19.5, "Peak +10%"),
                 (2.5, "Normal"), (23.0, "Normal")]:
    ax.text(x, 1.01, label, transform=ax.get_xaxis_transform(), ha="center",
            va="bottom", fontsize=8, color=INK_2)
x = curve["hour_of_day"] + 0.25                       # plot each half-hour at its midpoint
ax.plot(x, curve["weekday_kw"], color=BLUE, lw=1.5, label="Weekday")
ax.plot(x, curve["weekend_kw"], color=ORANGE, lw=1.5, label="Weekend")
style(ax, "Average kW per home")
ax.set_xlim(0, 24)
ax.set_xticks(range(0, 25, 3), [f"{h:02d}:00" for h in range(0, 25, 3)])
ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left")
fig.suptitle("When homes use electricity (2013, 443 London homes), with J&K's ToD slots",
             x=0.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(FIG / "daily_curve.png", dpi=150, facecolor=SURFACE)

# Chart 2: average daily use by month
monthly = results["monthly"]
fig, ax = plt.subplots(figsize=(8, 4), facecolor=SURFACE)
ax.bar(monthly["month"], monthly["avg_daily_kwh"], width=0.3, color=BLUE)
for _, row in monthly.loc[[monthly["avg_daily_kwh"].idxmax(), monthly["avg_daily_kwh"].idxmin()]].iterrows():
    ax.text(row["month"], row["avg_daily_kwh"], f"{row['avg_daily_kwh']:.1f}",
            ha="center", va="bottom", fontsize=8, color=INK)
style(ax, "kWh per home per day")
ax.set_xticks(range(1, 13), ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
fig.suptitle("Average daily use by month, 2013", x=0.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(FIG / "monthly.png", dpi=150, facecolor=SURFACE)

# Chart 3: share of evening-peak energy by decile of homes
drivers = results["peak_drivers"]
top_share = drivers.loc[drivers["decile"] == 1, "share_pct"].iloc[0]
fig, ax = plt.subplots(figsize=(8, 4), facecolor=SURFACE)
ax.bar(drivers["decile"], drivers["share_pct"], width=0.3, color=BLUE)
ax.text(1, top_share, f"{top_share:.0f}%", ha="center", va="bottom", fontsize=8, color=INK)
style(ax, "Share of evening-peak energy (%)")
ax.set_xticks(range(1, 11))
ax.set_xlabel("Decile of homes by evening use, 17:00-22:00 (1 = heaviest 10%)", color=INK_2, fontsize=9)
fig.suptitle(f"The heaviest 10% of homes use {top_share:.0f}% of evening-peak electricity",
             x=0.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(FIG / "peak_drivers.png", dpi=150, facecolor=SURFACE)

print(f"\nSaved {len(results)} tables to {OUT}/ and 3 charts to {FIG}/")