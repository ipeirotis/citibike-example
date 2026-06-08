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

## The data (provided)
A prepared daily table — `nyu-datasets.citibike.daily_trips_weather` — with one row
per day: trip counts (split by rider type, region, and bike type), durations and
distances, and that day's NYC weather (temperature, rain, snow). The dashboard reads
this prepared, day-level data rather than the hundreds of millions of raw trips. (A
coding agent can inspect the table to learn its exact columns.)

## What "great" looks like
- **Clear at a glance, deep on demand.**
- **Trustworthy** — handles the data's rough edges gracefully (for instance, the most
  recent days have no weather yet; don't let that distort the picture).
- **Responsive** — interactions feel instant.
- **Polished and readable** — coherent visual design, clean code.
- **Actually deployed** — live at a public URL, not just running on a laptop.

## Out of scope
Building the daily dataset itself (it's provided) and other heavy data engineering.
The focus is the dashboard.
