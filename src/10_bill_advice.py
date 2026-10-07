# Step 10: AI bill advice. Code computes every number; a local LLM (Ollama) only writes the
# words; a checker rejects any note containing a number we didn't give it.
import re
import time
from pathlib import Path
import duckdb
import pandas as pd
import requests

MODEL = "llama3.2"                      # 3B model, ~2 GB, runs on a MacBook Air
OLLAMA = "http://localhost:11434"
N_HOMES = 30                            # every home that pays more, plus random others up to 30
MAX_TRIES = 3
SEED = 42
OUT = Path("reports/advice")
OUT.mkdir(parents=True, exist_ok=True)

# ---- 0. Is Ollama running, with the model downloaded? ---------------------------------
try:
    models = [m["name"] for m in requests.get(f"{OLLAMA}/api/tags", timeout=5).json()["models"]]
except requests.exceptions.ConnectionError:
    raise SystemExit("Ollama isn't running. Open the Ollama app, then run this again.")
if not any(m.startswith(MODEL) for m in models):
    raise SystemExit(f"Model not found. Run:  ollama pull {MODEL}")

# ---- 1. The facts, computed in code (Steps 7 and 9) -----------------------------------
homes = pd.read_csv("reports/analysis/tod_bills.csv")
busiest = duckdb.sql("""
    WITH by_slot AS (
        SELECT household_id,
               hour(ts - INTERVAL 30 MINUTE) * 60 + minute(ts - INTERVAL 30 MINUTE) AS start_min,
               AVG(kwh) AS avg_kwh
        FROM 'data/clean/readings_2013_final.parquet'
        GROUP BY ALL
    )
    SELECT household_id, arg_max(start_min, avg_kwh) AS busiest_start_min
    FROM by_slot
    GROUP BY household_id
""").df()
homes = homes.merge(busiest, on="household_id")
typical_kwh = homes["yearly_kwh"].median()

sample = pd.concat([homes[homes["pays_more"]],
                    homes[~homes["pays_more"]].sample(max(N_HOMES - homes["pays_more"].sum(), 0),
                                                      random_state=SEED)]).head(N_HOMES)

def clock(minutes):
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"

def facts_for(h):
    """Every number the note may use, already rounded and formatted."""
    start = int(h.busiest_start_min)
    facts = {
        "Tariff": "solar hours 09:00-17:00 are 20% cheaper; peak hours 06:00-09:00 and 17:00-22:00 are 10% dearer",
        "Yearly use": f"{h.yearly_kwh:,.0f} kWh ({h.yearly_kwh / typical_kwh:.1f} times a typical home)",
        "Share of use in peak hours": f"{100 * h.peak_share:.0f}%",
        "Share of use in solar hours": f"{100 * h.solar_share:.0f}%",
        "Busiest half-hour of the day": f"{clock(start)}-{clock(start + 30)}",
        "Bill change if habits stay the same": f"{h.bill_change_pct:+.1f}%",
    }
    if h.pays_more:
        facts["Share of peak-hour use to move into solar hours to break even"] = f"{h.shift_to_break_even_pct:.1f}%"
    return "\n".join(f"- {k}: {v}" for k, v in facts.items())

# ---- 2. The guardrail: every number in the note must come from the facts --------------
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

def numbers_in(text):
    return {float(n.replace(",", "")) for n in NUMBER.findall(text)}

def invented_numbers(note, facts):
    allowed = numbers_in(facts)
    allowed |= {float(round(x)) for x in allowed}          # rounding (2.7% -> 3%) is fine
    return sorted(n for n in numbers_in(note) if n not in allowed)

# ---- 3. Ask the local LLM, check, retry with feedback, fall back if needed -----------
SYSTEM = ("You write short, friendly notes about electricity bills for households. "
          "Use ONLY the facts provided and do not use any other numbers. "
          "Write 3 or 4 plain sentences, with no headings and no lists.")

def ask(messages, seed):
    reply = requests.post(f"{OLLAMA}/api/chat", timeout=120, json={
        "model": MODEL, "messages": messages, "stream": False,
        "options": {"temperature": 0.3, "seed": seed}})
    reply.raise_for_status()                       # stop loudly if Ollama returns an error
    return reply.json()["message"]["content"].strip()

def fallback(h):
    """A plain template, used only if the LLM keeps inventing numbers."""
    verb = "rise" if h.pays_more else "fall"
    return (f"Under the new time-of-day tariff your bill would {verb} by about "
            f"{abs(h.bill_change_pct):.1f}% if your habits stay the same. "
            f"{100 * h.peak_share:.0f}% of your electricity is used in peak hours, when it is 10% dearer. "
            "Running appliances such as the washing machine in solar hours (09:00-17:00), "
            "when electricity is 20% cheaper, would lower it.")

rows = []
for i, h in enumerate(sample.itertuples(), 1):
    facts = facts_for(h)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Facts about this household:\n{facts}\n\n"
                 "Write the note: how the new time-of-day tariff changes their bill, why "
                 "(when they use electricity), and one practical tip."}]
    started = time.time()
    note, tries = None, 0
    while tries < MAX_TRIES:
        tries += 1
        draft = ask(messages, seed=SEED + tries)
        bad = invented_numbers(draft, facts)
        if not bad:
            note = draft
            break
        messages += [{"role": "assistant", "content": draft},
                     {"role": "user", "content": f"These numbers are not in the facts: {bad}. "
                      "Rewrite the note using only numbers from the facts."}]
    rows.append({"household_id": h.household_id, "bill_change_pct": h.bill_change_pct,
                 "pays_more": h.pays_more, "tries": tries, "passed_first_try": note is not None and tries == 1,
                 "used_fallback": note is None, "note": note or fallback(h), "facts": facts})
    status = "fallback" if note is None else f"ok after {tries} tr{'y' if tries == 1 else 'ies'}"
    print(f"[{i:>2}/{len(sample)}] {h.household_id}: {status} ({time.time() - started:.0f} s)")

notes = pd.DataFrame(rows)
notes.to_csv(OUT / "advice_notes.csv", index=False)

# ---- 4. How well did the guardrail work? ----------------------------------------------
n = len(notes)
print(f"\nNotes written: {n}")
print(f"  passed the number check first time: {notes['passed_first_try'].sum()} ({notes['passed_first_try'].mean():.0%})")
print(f"  passed after feedback:              {(~notes['passed_first_try'] & ~notes['used_fallback']).sum()}")
print(f"  replaced by the template:           {notes['used_fallback'].sum()}")
unchecked = sum(bool(invented_numbers(r.note, r.facts)) for r in notes.itertuples())
print(f"  final notes containing a number not in the facts: {unchecked}")
examples = pd.concat([notes[notes["pays_more"]].head(1), notes[~notes["pays_more"]].head(1)])
for _, r in examples.iterrows():                    # one home that pays more, one that pays less
    print(f"\n--- {r.household_id} (bill {r.bill_change_pct:+.1f}%) ---\n{r.note}")
print(f"\nSaved {OUT / 'advice_notes.csv'}")