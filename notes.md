What does one row of your data represent?
Why did you read every column as text first?
A reading says 0.347 kWh/hh. What was the home's average power in that half-hour?

step 3

Why didn't you load everything into pandas?
Why save as Parquet instead of CSV?
How did you pick the 500 homes, and why 250 from each group?
How do you know your extract is correct?

step 4 

4.2% of your data was missing. How did you handle it?
How did you find gaps using SQL?
Why is 11.5 kWh per half hour the limit?
How did you work out whether the timestamps were in local time?

step 5 

Walk me through your cleaning steps. Why that order?
Why fill gaps of up to an hour but not longer?
You dropped 48 homes. Could that bias your results?
Why treat an all-zero day as missing rather than as real data?

step 6 

How does an Isolation Forest work, in one or two sentences?
Why compare each day with the same home's usual day?
If you had an AI model, why did you still need a rule?
A third of the AI's flags weren't faults. Is the model bad?
Bonus: why use an unsupervised model instead of a classifier?

step 7 

Why did you shift timestamps by 30 minutes for time-of-day analysis, but not for daily totals?
The mean daily use is 10.1 kWh but the median is 8.4. Which do you report, and why?
How did you find the top 10% of homes' share of evening energy in SQL?
What is a load factor, and what does 0.09 tell a power company?
What is diversity, and why does it matter when sizing a transformer?


step 8 

Why do you need the flat-rate homes at all?
Explain difference-in-differences in one sentence.
Why compare against normal-price half-hours at the same clock time and month?
What does "95% range −6.2% to −3.5%" mean, and how did you get it?
ToU homes used 4% less than Std even at normal prices. Does that break your analysis?
What can't this prove? Hint: ToU homes volunteered for the trial.

step 9 

81% of homes use more in peak than in solar hours. Why do 97% still pay less?
Derive the bill-change formula from the three prices. Why does the normal-hours share drop out?
Where does the 30% in the break-even calculation come from?
If 97% of homes pay less, who pays? Give two ways to make the tariff revenue-neutral.
How did you turn Step 8's result into a prediction for J&K, and what does that assume?
Once homes respond to prices, the median bill falls less. Why?