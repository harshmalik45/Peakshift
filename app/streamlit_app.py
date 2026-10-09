# Step 11: the PeakShift dashboard. It reads only small files that are committed to GitHub
# (reports/ and app/data/), so it runs the same on your laptop and on Streamlit Community Cloud.
# Run it locally with:  streamlit run app/streamlit_app.py
from pathlib import Path
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent          # the repo folder, wherever the app runs
REPORTS, APP_DATA = ROOT / "reports", ROOT / "app" / "data"
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#898781"
INK_2, GRID, AXIS, BAND, SURFACE = "#52514e", "#e1e0d9", "#c3c2b7", "#f0efec", "#fcfcfb"
JK_DISCOUNT, JK_SURCHARGE = 20, 10                     # J&K's ToD tariff (%), as in Step 9

st.set_page_config(page_title="PeakShift", page_icon="⚡", layout="wide")


@st.cache_data                                         # read each file once, not on every click
def load(path, index_col=None):
    return pd.read_csv(path, index_col=index_col)


def show_image(path, caption):
    if path.exists():
        st.image(str(path), caption=caption)
    else:
        st.caption(f"({path.name} not found: run the earlier steps and commit reports/)")


def clock(hour):                                       # 18.5 -> "18:30"
    return f"{int(hour):02d}:{int(round(hour % 1 * 60)):02d}"


def style(chart, height=340):
    """The same quiet look as the matplotlib charts: hairline grid, grey axes and labels."""
    return (chart.properties(height=height)
            .configure_axis(gridColor=GRID, domainColor=AXIS, tickColor=AXIS, labelColor=INK_2,
                            titleColor=INK_2, titleFontWeight="normal")
            .configure_legend(labelColor=INK_2, orient="top", title=None)
            .configure_view(strokeWidth=0))

# The app's own data comes from src/11_app_data.py: if it hasn't been run, say so instead of crashing
missing = [name for name in ["funnel.csv", "ai_vs_rule.csv", "home_curves.csv"] if not (APP_DATA / name).exists()]
if missing:
    st.error(f"Missing in app/data/: {', '.join(missing)}. From the project folder, run "
             "`python src/11_app_data.py`, then refresh this page.")
    st.stop()

    
funnel = load(APP_DATA / "funnel.csv")
ai = load(APP_DATA / "ai_vs_rule.csv").iloc[0]
curves = load(APP_DATA / "home_curves.csv")
daily = load(REPORTS / "analysis" / "daily_curve.csv")
monthly = load(REPORTS / "analysis" / "monthly.csv")
drivers = load(REPORTS / "analysis" / "peak_drivers.csv")
diversity = load(REPORTS / "analysis" / "diversity.csv").iloc[0]
response = load(REPORTS / "analysis" / "price_response.csv", index_col=0)
bills = load(REPORTS / "analysis" / "tod_bills.csv")
notes = load(REPORTS / "advice" / "advice_notes.csv")

# ---- Header: the story in four numbers ---------------------------------------------------
final, high, low = funnel.iloc[-1], response.loc["High"], response.loc["Low"]
st.title("PeakShift")
st.markdown(f"**Do time-of-day prices change how homes use electricity?** "
            f"{final.readings / 1e6:.1f}M half-hourly smart-meter readings from {final.homes} London homes "
            "(2013), a real price trial, and what India's J&K time-of-day tariff would do to their bills.")
kpis = [
    ("Readings after cleaning", f"{final.readings / 1e6:.2f}M",
     f"from {funnel.readings.iloc[0] / 1e6:.2f}M raw, {final.homes} homes kept"),
    ("Use when prices were high", f"{high.effect_pct:+.1f}%",
     f"95% range {high.low_95_pct:+.1f}% to {high.high_95_pct:+.1f}%"),
    ("Homes paying less under J&K ToD", f"{(~bills.pays_more).mean():.0%}",
     f"median bill {bills.bill_change_pct.median():+.1f}%, with no change in habits"),
    ("AI notes passing checks first try", f"{notes.passed_first_try.sum()} of {len(notes)}",
     f"{(~notes.passed_first_try & ~notes.used_fallback).sum()} more after feedback, "
     f"{notes.used_fallback.sum()} used the template"),
]
for col, (label, value, caption) in zip(st.columns(4), kpis):
    with col.container(border=True):
        st.metric(label, value)
        st.caption(caption)

tabs = st.tabs(["Tariff designer", "One household", "When homes use power", "Price response", "Data & AI cleaning"])

# ---- 1. Tariff designer: Step 9's formula, live ------------------------------------------
with tabs[0]:
    st.markdown("Each home's bill changes by **−discount × its solar-hour share + surcharge × its peak-hour "
                "share** (no change in habits). The sliders start at J&K's tariff.")
    left, right = st.columns(2)
    discount = left.slider("Solar-hour discount, 09:00-17:00 (%)", 0, 40, JK_DISCOUNT)
    surcharge = right.slider("Peak-hour surcharge, 06:00-09:00 and 17:00-22:00 (%)", 0, 40, JK_SURCHARGE)

    sim = bills[["household_id", "solar_share", "peak_share", "yearly_kwh"]].copy()
    sim["bill_change_pct"] = -discount * sim.solar_share + surcharge * sim.peak_share
    sim["result"] = np.where(sim.bill_change_pct > 0, "Pays more", "Pays less")
    sim["solar_pct"], sim["peak_pct"] = 100 * sim.solar_share, 100 * sim.peak_share
    w = sim.yearly_kwh                                 # big users weigh more in the utility's revenue
    revenue_change = (w * sim.bill_change_pct).sum() / w.sum()

    m = st.columns(4)
    m[0].metric("Homes paying more", f"{(sim.result == 'Pays more').mean():.1%}")
    m[1].metric("Median bill change", f"{sim.bill_change_pct.median():+.1f}%")
    m[2].metric("Utility revenue change", f"{revenue_change:+.2f}%")
    if discount and surcharge:
        neutral = discount * (w * sim.solar_share).sum() / (w * sim.peak_share).sum()
        m[3].metric("Surcharge for no revenue loss", f"{neutral:.1f}%", help=f"at a {discount}% solar discount")

    x_max, y_max = sim.solar_pct.max() + 5, sim.peak_pct.max() + 5
    points = alt.Chart(sim).mark_circle(size=64, opacity=0.9, stroke=SURFACE, strokeWidth=2).encode(
        x=alt.X("solar_pct:Q", title="Share of use in solar hours (%)", scale=alt.Scale(domain=[0, x_max]),
                axis=alt.Axis(values=list(range(0, 101, 10)))),
        y=alt.Y("peak_pct:Q", title="Share of use in peak hours (%)", scale=alt.Scale(domain=[0, y_max]),
                axis=alt.Axis(values=list(range(0, 101, 10)))),
        color=alt.Color("result:N", scale=alt.Scale(domain=["Pays less", "Pays more"], range=[BLUE, ORANGE])),
        tooltip=[alt.Tooltip("household_id:N", title="Home"),
                 alt.Tooltip("bill_change_pct:Q", title="Bill change (%)", format="+.1f"),
                 alt.Tooltip("solar_pct:Q", title="Solar-hour share (%)", format=".0f"),
                 alt.Tooltip("peak_pct:Q", title="Peak-hour share (%)", format=".0f")])
    chart = points
    if surcharge:                                      # pays more above the line: peak > (discount / surcharge) x solar
        line = pd.DataFrame({"solar_pct": [0, x_max], "peak_pct": [0, x_max * discount / surcharge]})
        chart = points + alt.Chart(line).mark_line(color=INK_2, strokeWidth=1.5, clip=True).encode(
            x="solar_pct:Q", y="peak_pct:Q")
    st.altair_chart(style(chart, height=420))
    st.caption(f"Homes above the line pay more. Its slope is discount ÷ surcharge"
               f"{f' = {discount / surcharge:g}' if surcharge else ''}, so with J&K's 20% and 10% a home "
               "pays more only if its peak-hour share is more than double its solar-hour share. "
               "These are London load shapes: the method transfers to India, the numbers don't.")
    with st.expander("Table view"):
        st.dataframe(sim[["household_id", "solar_pct", "peak_pct", "bill_change_pct", "result"]]
                     .sort_values("bill_change_pct", ascending=False).round(2), hide_index=True)

# ---- 2. One household: its day, its bill and its AI note ---------------------------------
with tabs[1]:
    noted = notes.set_index("household_id")
    choices = list(noted.index) + sorted(set(bills.household_id) - set(noted.index))
    home = st.selectbox("Household (the first 30 have an AI-written note)", choices,
                        format_func=lambda h: f"{h}  ·  AI note" if h in noted.index else h)
    b = bills.set_index("household_id").loc[home]
    m = st.columns(4)
    m[0].metric("Yearly use", f"{b.yearly_kwh:,.0f} kWh")
    m[1].metric("Used in solar hours", f"{b.solar_share:.0%}")
    m[2].metric("Used in peak hours", f"{b.peak_share:.0%}")
    m[3].metric("Bill under J&K ToD", f"{b.bill_change_pct:+.1f}%", help="with no change in habits")

    # This home's average day next to the all-home average, J&K's peak hours shaded
    wide = pd.DataFrame({"this_home": curves[curves.household_id == home].set_index("hour_of_day")["avg_kw"],
                         "all_homes": curves.groupby("hour_of_day")["avg_kw"].mean()}).reset_index()
    wide["time"] = wide.hour_of_day + 0.25            # draw each half-hour at its midpoint
    wide["half_hour"] = [f"{clock(h)}-{clock(h + 0.5)}" for h in wide.hour_of_day]
    lines_data = wide.melt(["time", "half_hour"], ["this_home", "all_homes"], var_name="series", value_name="kW")
    lines_data["series"] = lines_data.series.map({"this_home": home, "all_homes": "All homes"})

    x = alt.X("time:Q", title=None, scale=alt.Scale(domain=[0, 24]),
              axis=alt.Axis(values=list(range(0, 25, 3)), grid=False,
                            labelExpr="(datum.value < 10 ? '0' : '') + datum.value + ':00'"))
    bands = alt.Chart(pd.DataFrame({"start": [6, 17], "end": [9, 22]})).mark_rect(color=BAND).encode(
        x=alt.X("start:Q", scale=alt.Scale(domain=[0, 24])), x2="end:Q")
    lines = alt.Chart(lines_data).mark_line(strokeWidth=2).encode(
        x=x, y=alt.Y("kW:Q", title="Average kW"),
        color=alt.Color("series:N", scale=alt.Scale(domain=[home, "All homes"], range=[BLUE, GREY]),
                        legend=alt.Legend(symbolType="stroke")))
    nearest = alt.selection_point(nearest=True, on="pointerover", fields=["time"], empty=False)
    dots = lines.mark_point(filled=True, size=70, stroke=SURFACE, strokeWidth=2).encode(
        opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
    rule = alt.Chart(wide).mark_rule(color=INK_2).encode(
        x="time:Q", opacity=alt.condition(nearest, alt.value(0.4), alt.value(0)),
        tooltip=[alt.Tooltip("half_hour:N", title="Half-hour"),
                 alt.Tooltip("this_home:Q", title="This home (kW)", format=".2f"),
                 alt.Tooltip("all_homes:Q", title="All homes (kW)", format=".2f")]).add_params(nearest)
    st.altair_chart(style(alt.layer(bands, lines, dots, rule)))
    st.caption("Shaded: J&K peak hours (10% dearer). Solar hours, 09:00-17:00, are 20% cheaper.")

    if home in noted.index:
        n = noted.loc[home]
        st.markdown("**Bill note for this home**")
        with st.container(border=True):
            st.markdown(n.note.replace("$", "\\$"))
        if n.used_fallback:
            st.caption("The model failed the checks three times, so this home got the plain template note.")
        else:
            st.caption(f"Written by Llama 3.2 (3B) running locally with Ollama; passed both checks "
                       f"{'first time' if n.tries == 1 else f'after {n.tries} tries'}: every number comes "
                       "from the facts below, and none of the key numbers is missing.")
        with st.expander("Facts given to the model"):
            st.text(n.facts)
    else:
        st.caption("Bill notes were written for 30 homes: every home that pays more, plus a random sample. "
                   "Pick one marked 'AI note' to read one.")

# ---- 3. When homes use power (Step 7) ----------------------------------------------------
with tabs[2]:
    busiest = daily.nsmallest(1, "busiest_rank").iloc[0]
    quietest = daily.nsmallest(1, "all_days_kw").iloc[0]
    top_share = drivers.loc[drivers.decile == 1, "share_pct"].iloc[0]
    st.markdown(
        f"- The busiest half-hour is **{clock(busiest.hour_of_day)}-{clock(busiest.hour_of_day + 0.5)}** at "
        f"{busiest.all_days_kw:.2f} kW per home, {busiest.all_days_kw / quietest.all_days_kw:.1f}× the quietest.\n"
        f"- The heaviest 10% of homes use **{top_share:.1f}%** of evening-peak electricity.\n"
        f"- Diversity factor **{diversity.diversity_factor:.1f}**: the average home's own peak is "
        f"{diversity.avg_own_peak_kw:.2f} kW, but all homes together never needed more than "
        f"{diversity.group_peak_kw_per_home:.2f} kW each.")
    show_image(REPORTS / "figures" / "daily_curve.png", f"SQL analysis of {final.homes} homes, 2013")
    left, right = st.columns(2)
    with left:
        swing = monthly.avg_daily_kwh.max() / monthly.avg_daily_kwh.min()
        show_image(REPORTS / "figures" / "monthly.png", f"The busiest month uses {swing:.1f}× the quietest")
    with right:
        show_image(REPORTS / "figures" / "peak_drivers.png", "A few homes drive the evening peak")

# ---- 4. Price response (Step 8) ----------------------------------------------------------
with tabs[3]:
    st.markdown(
        "In 2013, time-of-use homes got day-ahead High, Normal or Low prices; flat-rate homes are the "
        f"control group (difference-in-differences). At High prices ToU homes used **{high.effect_pct:+.1f}%** "
        f"(95% range {high.low_95_pct:+.1f}% to {high.high_95_pct:+.1f}%); at Low prices "
        f"**{low.effect_pct:+.1f}%** ({low.low_95_pct:+.1f}% to {low.high_95_pct:+.1f}%).")
    show_image(REPORTS / "figures" / "price_response.png", "Use vs usual around the start of each price event")
    with st.expander("Table view"):
        st.dataframe(response)

# ---- 5. Data & AI cleaning (Steps 3-6) ---------------------------------------------------
with tabs[4]:
    table = funnel.assign(readings=funnel.readings.map("{:,}".format)).rename(columns=str.capitalize)
    st.dataframe(table, hide_index=True)
    st.markdown(
        f"An Isolation Forest scored every home-day and flagged the most unusual 1% ({ai.flagged_days:,} days). "
        f"**{ai.flagged_that_were_faults / ai.flagged_days:.0%}** of them were meter faults (6+ hours of zeros, "
        "or stuck on one value); the rest were real but unusual days, so they were kept. The flags covered "
        f"**{ai.flagged_that_were_faults / ai.fault_days:.0%}** of all {ai.fault_days:,} fault days, "
        "which a simple rule then removed.")
    show_image(REPORTS / "top_anomalies.png", "The 12 most unusual home-days, each against its home's usual day")
    show_image(REPORTS / "fault_spot_check.png", "Spot check: days the rule removes vs flagged days it keeps")
    with st.expander("Cleaning logs"):
        st.dataframe(load(REPORTS / "cleaning_log.csv"), hide_index=True)
        st.dataframe(load(REPORTS / "fault_log.csv"), hide_index=True)

st.divider()
st.caption("Data: Low Carbon London smart-meter trial (UK Power Networks), via the London Datastore, CC BY 4.0. "
           "Tariff: J&K time-of-day tariff (JERC), effective 1 Sep 2026. "
           "Code: [github.com/harshmalik45/Peakshift](https://github.com/harshmalik45/Peakshift)")