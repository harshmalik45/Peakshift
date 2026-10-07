# PeakShift: Do time-of-day prices change how homes use electricity?
## Data

Source: [Low Carbon London smart-meter data](https://data.london.gov.uk/dataset/smartmeter-energy-use-data-in-london-households)
(UK Power Networks, London Datastore, CC BY 4.0). 168 CSV files of 1M rows each
(~167M rows, 8.5 GB). One row = one home's electricity use in one half-hour, Nov 2011 – Feb 2014.

| Column in file | Renamed to | Meaning | Example | Stored as |
|---|---|---|---|---|
| `LCLid` | `household_id` | Smart-meter / household ID | MAC000002 | text |
| `stdorToU` | `tariff_group` | `Std` = flat rate, `ToU` = dynamic time-of-use prices in 2013 | Std | text |
| `DateTime` | `ts_text` | Half-hour of the reading | 2012-10-12 00:30:00.0000000 | text, 7 decimal places |
| `KWH/hh (per half hour) ` | `kwh_text` | Energy used in that half-hour (kWh) | 0.347 | text with a leading space; the name ends in a space |