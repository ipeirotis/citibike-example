# Target specification — "Citibike × Weather" dashboard

*The high-level brief a team should converge on before handing it to a coding
agent. It says **what to deliver** and **what "good" means** — not how to build it.*

## Deliverable
An interactive, public web dashboard — a Streamlit app, deployed to a shareable
URL — that lets anyone explore **how NYC weather affects Citibike ridership** across
the system's full history, 2013 → today.

## Audience
A curious, non-technical visitor: a journalist, a city planner, a fellow student.
They should *see* the weather–ridership relationship within a minute of landing, then
be able to dig into the details themselves.

## What it must do
- Lead with the **headline story** — ridership rises with warmth, falls with rain,
  and collapses with snow — visible at a glance, with the key numbers called out.
- Be **interactive**: let the visitor choose the time period and slice the data
  (e.g. by region, or weekday vs. weekend), with every view responding.
- Use its visuals to answer questions like:
  - How does ridership change with temperature — and is it ever *too* hot to ride?
  - How much do rain and snow suppress riding?
  - Who is more weather-sensitive — members or casual riders?
  - How do seasonality and year-over-year growth show up?
- Pair each view with a short, plain-language **takeaway**, so the *insight* lands —
  not just the chart.

## The data
Your **trip data is your own** — daily ridership comes from the BigQuery warehouse you
built in Part 1 (the raw Citibike import); roll it up to one row per day (counts by
rider type, region, and bike type, plus durations and distances).

The **weather is provided**: `nyu-datasets.weather.m_weather_daily_nyc` holds daily NYC
temperature, rain, and snow. **Join your daily trips to it on the calendar date** —
assembling that combined daily table is part of the work. The dashboard then reads the
day-level result, not the hundreds of millions of raw trips.

*Fallback:* if your warehouse isn't ready, the instructor provides daily trip
aggregates at `nyu-datasets.citibike.m_daily_trips` (and a `daily_trips` view) that you
can join against the weather table instead.

## What "great" looks like
- **Clear at a glance, deep on demand.**
- **Trustworthy** — handles the data's rough edges gracefully (for instance, the most
  recent days have no weather yet; don't let that distort the picture).
- **Responsive** — interactions feel instant.
- **Polished and readable** — coherent visual design, clean code.
- **Actually deployed** — live at a public URL, not just running on a laptop.

## Out of scope
The raw Citibike ingestion — that was Part 1; here you build on its output (or the
fallback). The focus is joining trips to weather and turning the result into the
dashboard.
