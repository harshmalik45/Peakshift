# Step 9: what would J&K's time-of-day (ToD) tariff do to these homes' bills?
# J&K (JERC, from 1 Sept 2026): solar hours 09:00-17:00 at 20% off; peak hours 06:00-09:00
# and 17:00-22:00 at 10% extra (non-commercial consumers); other hours at the normal rate.
import numpy as np
import pandas as pd
import duckdb
import matplotlib.pyplot as plt

SOLAR_DISCOUNT = 0.20
PEAK_SURCHARGE = 0.10
LONDON_PRICE = {"High": 67.20 / 11.76, "Low": 3.99 / 11.76}   # 2013 trial prices vs its normal price

# Each home's split across the slots (Step 7) and its yearly use
homes = pd.read_csv("reports/analysis/tod_slot_shares.csv")
yearly = duckdb.sql("""
    SELECT household_id, SUM(kwh) / COUNT(DISTINCT CAST(ts AS DATE)) * 365 AS yearly_kwh
    FROM 'data/clean/readings_2013_final.parquet'
    GROUP BY household_id
""").df()
homes = homes.merge(yearly, on="household_id")
solar, peak, normal = homes["solar_share"], homes["peak_share"], homes["normal_share"]

def bill_ratio(solar, peak, normal, d=SOLAR_DISCOUNT, s=PEAK_SURCHARGE):
    """New bill / old flat bill: each slot's share of use times its price (normal price = 1)."""
    return ((1 - d) * solar + (1 + s) * peak + normal) / (solar + peak + normal)

# ---- 1. Bills with NO change in habits ------------------------------------------------
# Because shares add up to 1, the change is simply  -20% x solar share + 10% x peak share,
# so a home pays more only if its peak share is more than DOUBLE its solar share.
homes["bill_change_pct"] = 100 * (bill_ratio(solar, peak, normal) - 1)
homes["pays_more"] = homes["bill_change_pct"] > 0

# Break-even: every kWh moved from peak to solar hours saves 10% + 20% = 30% of the normal price
homes["shift_to_break_even_pct"] = np.where(
    homes["pays_more"],
    100 * (homes["bill_change_pct"] / 100) / (SOLAR_DISCOUNT + PEAK_SURCHARGE) / peak,
    0.0)

print(f"Homes: {len(homes)}")
print(f"Pay MORE under ToD (no change in habits): {homes['pays_more'].mean():.1%}")
print(f"Median bill change: {homes['bill_change_pct'].median():+.1f}%  "
      f"(10th-90th percentile: {homes['bill_change_pct'].quantile(0.1):+.1f}% to "
      f"{homes['bill_change_pct'].quantile(0.9):+.1f}%)")
print(f"Biggest rise: {homes['bill_change_pct'].max():+.1f}% | biggest fall: {homes['bill_change_pct'].min():+.1f}%")
if homes["pays_more"].any():
    print(f"Homes paying more would break even by moving a median "
          f"{homes.loc[homes['pays_more'], 'shift_to_break_even_pct'].median():.1f}% of their peak-hour use to solar hours")

# Fairness check: does the change depend on how much a home uses?
homes["use_quartile"] = pd.qcut(homes["yearly_kwh"], 4, labels=["Lowest 25%", "2nd", "3rd", "Highest 25%"])
print("\nMedian bill change by yearly use:")
print(homes.groupby("use_quartile", observed=True)["bill_change_pct"].median().round(2).to_string())

# ---- 2. The power company's view -------------------------------------------------------
w = homes["yearly_kwh"]                                       # weight each home by its use
revenue_change = (w * bill_ratio(solar, peak, normal)).sum() / w.sum() - 1
neutral_surcharge = SOLAR_DISCOUNT * (w * solar).sum() / (w * peak).sum()
print(f"\nDiscom revenue change (no change in habits): {revenue_change:+.2%}")
print(f"To stay revenue-neutral it could raise all rates by {1 / (1 + revenue_change) - 1:+.2%},")
print(f"or keep the 20% solar discount and set the peak surcharge to {neutral_surcharge:.1%} (J&K uses 10%)")

# ---- 3. Would habits change? Use the sensitivity measured in Step 8 ------------------
# Price elasticity = % change in use / % change in price (on a log scale)
resp = pd.read_csv("reports/analysis/price_response.csv", index_col=0)["effect_pct"] / 100
elasticity = {p: np.log(1 + resp[p]) / np.log(LONDON_PRICE[p]) for p in ["High", "Low"]}
peak_change = (1 + PEAK_SURCHARGE) ** elasticity["High"] - 1      # J&K's +10% vs London's 5.7x
solar_change = (1 - SOLAR_DISCOUNT) ** elasticity["Low"] - 1      # J&K's -20% vs London's -66%
new_bill = ((1 - SOLAR_DISCOUNT) * solar * (1 + solar_change)      # ToD bill after the response
            + (1 + PEAK_SURCHARGE) * peak * (1 + peak_change) + normal)
with_response = new_bill / (solar + peak + normal)                  # vs the old flat bill
print(f"\nLondon trial elasticity: {elasticity['High']:.3f} (high price), {elasticity['Low']:.3f} (low price)")
print(f"At J&K's price gaps that means peak-hour use {peak_change:+.2%} and solar-hour use {solar_change:+.2%}")
print(f"Median bill change with that response: {100 * (with_response.median() - 1):+.1f}% "
      f"(vs {homes['bill_change_pct'].median():+.1f}% with no response)")

homes.drop(columns="use_quartile").round(4).to_csv("reports/analysis/tod_bills.csv", index=False)

# ---- 4. Charts --------------------------------------------------------------------------
BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, INK_2, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"

def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)

fig, (left, right) = plt.subplots(1, 2, figsize=(13, 4.8), facecolor=SURFACE)

# Left: how bills change across homes
bins = np.arange(np.floor(homes["bill_change_pct"].min()), homes["bill_change_pct"].max() + 0.5, 0.5)
left.hist(homes["bill_change_pct"], bins=bins, color=BLUE, edgecolor=SURFACE, linewidth=1)
left.axvline(0, color=INK_2, lw=1)
left.text(0.2, 0.97, f"{homes['pays_more'].mean():.0%} pay more", transform=left.get_xaxis_transform(),
          va="top", fontsize=8, color=INK)
style(left)
left.set_xlabel("Change in yearly bill with no change in habits (%)", color=INK_2, fontsize=9)
left.set_ylabel("Homes", color=INK_2, fontsize=9)

# Right: the 2x rule. Homes above the line (peak share > 2 x solar share) pay more
right.scatter(solar[~homes["pays_more"]] * 100, peak[~homes["pays_more"]] * 100, s=18,
              color=BLUE, edgecolor=SURFACE, linewidth=0.5, label="Pays less")
right.scatter(solar[homes["pays_more"]] * 100, peak[homes["pays_more"]] * 100, s=18,
              color=ORANGE, edgecolor=SURFACE, linewidth=0.5, label="Pays more")
x = np.linspace(0, solar.max() * 100 + 5, 50)
right.plot(x, 2 * x, color=INK_2, lw=1)
right.text(1, peak.max() * 100 + 3, "Above the line: peak share > 2 × solar share,\nso the bill goes up",
           fontsize=8, color=INK_2, va="top")
style(right)
right.grid(axis="x", color=GRID, lw=0.6)
right.set_xlim(0, solar.max() * 100 + 5)
right.set_ylim(0, peak.max() * 100 + 5)
right.set_xlabel("Share of use in solar hours, 09:00-17:00 (%)", color=INK_2, fontsize=9)
right.set_ylabel("Share of use in peak hours (%)", color=INK_2, fontsize=9)
right.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper right")

fig.suptitle(f"J&K's ToD tariff on 443 London homes: median bill {homes['bill_change_pct'].median():+.1f}%, "
             f"{homes['pays_more'].mean():.0%} pay more", x=0.01, ha="left", fontsize=12, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig("reports/figures/tod_bills.png", dpi=150, facecolor=SURFACE)
print("\nSaved reports/analysis/tod_bills.csv and reports/figures/tod_bills.png")