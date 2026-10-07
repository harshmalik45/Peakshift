# Step 10 (v2): AI bill advice. Code computes every number AND the reason the bill changes;
# a local LLM (Ollama) only writes the words. Two checks guard every note:
#   1. no invented numbers: every number in the note must come from the facts
#   2. no missing facts: the note must state the bill change and the numbers that explain it
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
SOLAR_DISCOUNT, PEAK_SURCHARGE = 0.20, 0.10
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
# The reason a bill changes, in % of the old bill: bill change = extra_pct - saving_pct (Step 9)
homes["saving_pct"] = 100 * SOLAR_DISCOUNT * homes["solar_share"]
homes["extra_pct"] = 100 * PEAK_SURCHARGE * homes["peak_share"]

sample = pd.concat([homes[homes["pays_more"]],
                    homes[~homes["pays_more"]].sample(max(N_HOMES - homes["pays_more"].sum(), 0),
                                                      random_state=SEED)]).head(N_HOMES)

def clock(minutes):
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"

def slot_of(minutes):
    hour = minutes / 60
    if 9 <= hour < 17:
        return "solar hours"
    if 6 <= hour < 9 or 17 <= hour < 22:
        return "peak hours"
    return "normal hours"

def shown(x):
    """A number exactly as the facts show it (1 decimal place)."""
    return float(f"{x:.1f}")

def facts_for(h):
    """The facts for one home, and the key numbers its note must include."""
    start = int(h.busiest_start_min)
    change = abs(h.bill_change_pct)
    facts = {
        "Tariff": "solar hours 09:00-17:00 are 20% cheaper; peak hours 06:00-09:00 and 17:00-22:00 "
                  "are 10% dearer; other hours cost the same as now",
        "Your bill if habits stay the same": f"{'rises' if h.pays_more else 'falls'} by {change:.1f}%",
        "Why": f"the solar-hour discount saves {h.saving_pct:.1f}% of your bill (you use "
               f"{100 * h.solar_share:.0f}% of your electricity in solar hours); the peak-hour "
               f"surcharge adds {h.extra_pct:.1f}% (you use {100 * h.peak_share:.0f}% in peak hours)",
        "Your busiest half-hour": f"{clock(start)}-{clock(start + 30)}, in {slot_of(start)}",
    }
    must = [shown(change), shown(h.saving_pct), shown(h.extra_pct)]
    if h.pays_more:
        facts["To break even"] = f"move {h.shift_to_break_even_pct:.1f}% of your peak-hour use into solar hours"
        must.append(shown(h.shift_to_break_even_pct))
    return "\n".join(f"- {k}: {v}" for k, v in facts.items()), must

# ---- 2. The two checks ------------------------------------------------------------------
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")

def numbers_in(text):
    return {float(n.replace(",", "")) for n in NUMBER.findall(text)}

def nearest_whole(x):
    return float(int(x + 0.5))             # round half up: 4.5 -> 5 (Python's round(4.5) gives 4)

def invented_numbers(note, facts):
    """Check 1: numbers in the note that aren't in the facts (rounding to a whole number is fine)."""
    allowed = numbers_in(facts)
    allowed |= {nearest_whole(x) for x in allowed}
    return sorted(n for n in numbers_in(note) if n not in allowed)

def missing_numbers(note, must):
    """Check 2: key numbers the note leaves out (rounding is fine here too)."""
    found = numbers_in(note)
    return [x for x in must if x not in found and nearest_whole(x) not in found]

# ---- 3. Ask the local LLM, check, retry with feedback, fall back if needed -----------
SYSTEM = ("You write short, friendly notes to households about their electricity bill under a new "
          "time-of-day tariff. Write to the household as 'you'. Use only the facts provided: no other "
          "numbers and no other claims. Write 3 or 4 plain sentences, with no headings and no lists.")

def ask(messages, seed):
    reply = requests.post(f"{OLLAMA}/api/chat", timeout=120, json={
        "model": MODEL, "messages": messages, "stream": False,
        "options": {"temperature": 0.3, "seed": seed}})
    reply.raise_for_status()                       # stop loudly if Ollama returns an error
    return reply.json()["message"]["content"].strip()

def fallback(h):
    """A plain template, used only if the LLM keeps failing the checks."""
    if h.pays_more:
        tip = (f"Moving {h.shift_to_break_even_pct:.1f}% of your peak-hour use into solar hours "
               "(09:00-17:00) would cancel the rise.")
    else:
        tip = "Moving more of your use from peak hours into solar hours (09:00-17:00) would save even more."
    return (f"Under the new time-of-day tariff your bill {'rises' if h.pays_more else 'falls'} by "
            f"{abs(h.bill_change_pct):.1f}% if your habits stay the same. The 20% solar-hour discount "
            f"saves you {h.saving_pct:.1f}% of your bill, while the 10% peak-hour surcharge adds "
            f"{h.extra_pct:.1f}%. " + tip)

rows = []
for i, h in enumerate(sample.itertuples(), 1):
    facts, must = facts_for(h)
    tip = "a practical tip that uses the 'To break even' fact" if h.pays_more else "one practical tip"
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Facts:\n{facts}\n\nWrite the note. First say how the bill "
                 f"changes, then why (using the saving and the extra cost), then {tip}."}]
    started = time.time()
    note, tries = None, 0
    while tries < MAX_TRIES:
        tries += 1
        draft = ask(messages, seed=SEED + tries)
        bad, missing = invented_numbers(draft, facts), missing_numbers(draft, must)
        if tries == 1:
            first_invented, first_missing = bool(bad), bool(missing)
        if not bad and not missing:
            note = draft
            break
        problems = []
        if bad:
            problems.append(f"these numbers are not in the facts: {bad}")
        if missing:
            problems.append(f"it must also include these numbers from the facts: {missing}")
        messages += [{"role": "assistant", "content": draft},
                     {"role": "user", "content": "Rewrite the note: " + "; ".join(problems) + "."}]
    rows.append({"household_id": h.household_id, "bill_change_pct": h.bill_change_pct,
                 "pays_more": h.pays_more, "tries": tries,
                 "first_draft_invented": first_invented, "first_draft_missing": first_missing,
                 "passed_first_try": note is not None and tries == 1, "used_fallback": note is None,
                 "note": note or fallback(h), "facts": facts, "must_include": must})
    status = "fallback" if note is None else f"ok after {tries} tr{'y' if tries == 1 else 'ies'}"
    print(f"[{i:>2}/{len(sample)}] {h.household_id}: {status} ({time.time() - started:.0f} s)")

notes = pd.DataFrame(rows)
notes.to_csv(OUT / "advice_notes.csv", index=False)

# ---- 4. How well did the checks work? ---------------------------------------------------
print(f"\nNotes written: {len(notes)}")
print(f"  first drafts that invented a number:  {notes['first_draft_invented'].sum()}")
print(f"  first drafts missing a key number:    {notes['first_draft_missing'].sum()}")
print(f"  passed both checks first time:        {notes['passed_first_try'].sum()} ({notes['passed_first_try'].mean():.0%})")
print(f"  passed after feedback:                {(~notes['passed_first_try'] & ~notes['used_fallback']).sum()}")
print(f"  replaced by the template:             {notes['used_fallback'].sum()}")
failing = sum(bool(invented_numbers(r.note, r.facts) or missing_numbers(r.note, r.must_include))
              for r in notes.itertuples())
print(f"  final notes failing a check:          {failing}")
examples = pd.concat([notes[notes["pays_more"]].head(1), notes[~notes["pays_more"]].head(1)])
for _, r in examples.iterrows():                    # one home that pays more, one that pays less
    print(f"\n--- {r.household_id} (bill {r.bill_change_pct:+.1f}%) ---\n{r.note}")
print(f"\nSaved {OUT / 'advice_notes.csv'}")