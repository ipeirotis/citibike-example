"""Weather-impact attribution for the Citibike × Weather dashboard.

The other tabs answer a *descriptive* question — "how does a day like this compare
to its surrounding month?" — via the ridership index. That index removes the growth
trend and the seasonal level, but it still reports **marginal** effects: a windy day
is also a cold day, a thunderstorm day is also a wet day, so the index credits the
whole drop to whichever variable you happen to be looking at.

This module estimates the **partial** (ceteris-paribus) effect of each weather factor
instead, by fitting one model and reading off each coefficient with the others held
fixed:

    log(trips) ~ C(year_month)              # growth trend + seasonal level + COVID, as fixed effects
               + C(day_of_week) + holiday    # weekly cycle + US federal holidays
               + C(temp_band)                # temperature, non-linear (bins vs a mild reference)
               + C(rain_band)                # dry / light / moderate / heavy
               + snow_inches + snow_depth_inches
               + wind_avg_mph + is_thunder + is_foggy

Month fixed effects absorb the trend, the seasonal level and one-off shocks, so the
weather terms are identified purely from day-to-day variation *within* each month.
Standard errors are Newey–West (HAC), because daily residuals are autocorrelated and
naive OLS errors would be too optimistic. Each effect is reported as ``exp(beta) - 1``
— a multiplicative % change in ridership.

Pure pandas/statsmodels (no Streamlit, no cloud), so it is importable and testable.
Run ``python attribution.py path/to/daily_trips_weather.csv`` for a quick self-check.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from pandas.tseries.holiday import USFederalHolidayCalendar

# Temperature is binned (it has an inverted-U effect); "55-65" mild is the reference.
TEMP_EDGES = [-100, 32, 45, 55, 65, 75, 85, 200]
TEMP_LABELS = ["<32", "32-45", "45-55", "55-65", "65-75", "75-85", "85+"]
TEMP_REF = "55-65"
RAIN_EDGES = [-1, 1e-4, 0.25, 0.75, 100]
RAIN_LABELS = ["dry", "light", "moderate", "heavy"]  # "dry" is the reference

_HAC = dict(cov_type="HAC", cov_kwds={"maxlags": 14})


def _prep(df: pd.DataFrame, trips_col: str) -> pd.DataFrame:
    """Daily frame -> model frame (log trips, calendar controls, weather bands)."""
    d = df.copy()
    d["y"] = pd.to_numeric(d[trips_col], errors="coerce")
    d = d[d["y"] > 0].dropna(subset=["tavg_f", "wind_avg_mph", "prcp_inches"]).copy()
    d["logy"] = np.log(d["y"])
    d["ym"] = d["date"].dt.year * 12 + d["date"].dt.month
    d["dow"] = d["date"].dt.dayofweek
    hol = USFederalHolidayCalendar().holidays(d["date"].min(), d["date"].max())
    d["holiday"] = d["date"].isin(hol).astype(int)
    cats = [TEMP_REF] + [l for l in TEMP_LABELS if l != TEMP_REF]  # reference first
    d["temp_band"] = (pd.cut(d["tavg_f"], TEMP_EDGES, labels=TEMP_LABELS)
                        .cat.reorder_categories(cats).cat.remove_unused_categories())
    d["rain_band"] = (pd.cut(d["prcp_inches"].fillna(0), RAIN_EDGES, labels=RAIN_LABELS)
                        .cat.remove_unused_categories())
    for c in ["snow_inches", "snow_depth_inches", "is_thunder", "is_foggy"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    return d


def _contrast(res, deltas: dict[str, float]) -> tuple[float, float, float]:
    """A linear combination of coefficients -> (pct, lo95, hi95) as % effects."""
    names = [n for n in deltas if n in res.params]
    vec = np.array([deltas[n] for n in names])
    b = float(vec @ res.params[names].values)
    se = float(np.sqrt(vec @ res.cov_params().loc[names, names].values @ vec))
    return ((np.exp(b) - 1) * 100,
            (np.exp(b - 1.96 * se) - 1) * 100,
            (np.exp(b + 1.96 * se) - 1) * 100)


def fit_impacts(df: pd.DataFrame, trips_col: str) -> tuple[pd.DataFrame, dict]:
    """Fit the model and return (effects, meta).

    ``effects`` has one row per interpretable contrast: label, group, pct, lo, hi.
    ``meta`` carries the sample size and the R² variance decomposition.
    """
    d = _prep(df, trips_col)
    formula = ("logy ~ C(ym) + C(dow) + holiday + C(temp_band) + C(rain_band)"
               " + snow_inches + snow_depth_inches + wind_avg_mph + is_thunder + is_foggy")
    res = smf.ols(formula, data=d).fit(**_HAC)
    controls = smf.ols("logy ~ C(ym) + C(dow) + holiday", data=d).fit()
    meta = {
        "n": int(res.nobs),
        "r2_controls": controls.rsquared,
        "r2_full": res.rsquared,
        # share of the *within-month* (control-residual) variance explained by weather
        "weather_partial_r2": (res.rsquared - controls.rsquared) / (1 - controls.rsquared),
    }

    rows: list[dict] = []

    def add(label, group, deltas):
        pct, lo, hi = _contrast(res, deltas)
        rows.append({"label": label, "group": group, "pct": pct, "lo": lo, "hi": hi})

    for lbl in [l for l in TEMP_LABELS if l != TEMP_REF]:
        add(f"{lbl}°F", "Temperature (vs 55–65°F)", {f"C(temp_band)[T.{lbl}]": 1.0})
    for lbl in ["light", "moderate", "heavy"]:
        add(f"{lbl} rain", "Rain (vs dry)", {f"C(rain_band)[T.{lbl}]": 1.0})

    # Representative day-level contrasts for the continuous terms.
    snow = d.loc[d.snow_inches > 0, "snow_inches"].mean()
    depth = d.loc[d.snow_depth_inches > 0, "snow_depth_inches"].mean()
    windy = d.loc[d.wind_avg_mph >= 10, "wind_avg_mph"].mean()
    add("typical snow day", "Snow", {"snow_inches": snow, "snow_depth_inches": depth})
    add(f"windy day (~{windy:.0f} mph)", "Wind",
        {"wind_avg_mph": windy - d["wind_avg_mph"].mean()})
    add("thunderstorm", "Storms (vs same rain/temp)", {"is_thunder": 1.0})
    add("fog", "Storms (vs same rain/temp)", {"is_foggy": 1.0})

    hum = fit_humidity_impact(df, trips_col)
    if hum is not None:
        rows.append({"label": "+10°F muggier (warm days)", "group": "Humidity (warm days, 2016–24)",
                     "pct": hum["p10"], "lo": hum["lo10"], "hi": hum["hi10"]})

    return pd.DataFrame(rows), meta


def fit_humidity_impact(df: pd.DataFrame, trips_col: str) -> dict | None:
    """Dew-point partial effect on warm days (>=68°F), holding temperature constant.

    Dew point and temperature are collinear, so this is fit only on warm days with a
    *continuous* temperature control — it isolates mugginess at a given temperature.
    Humidity is Central Park 2016–2024 only; returns None if too few rows.
    """
    d = df.copy()
    d["y"] = pd.to_numeric(d[trips_col], errors="coerce")
    d = d[(d["y"] > 0) & (d["tavg_f"] >= 68) & d["dewpoint_f"].notna()]
    d = d.dropna(subset=["wind_avg_mph"]).copy()
    if len(d) < 100:
        return None
    d["logy"] = np.log(d["y"])
    d["ym"] = d["date"].dt.year * 12 + d["date"].dt.month
    d["dow"] = d["date"].dt.dayofweek
    hol = USFederalHolidayCalendar().holidays(d["date"].min(), d["date"].max())
    d["holiday"] = d["date"].isin(hol).astype(int)
    # Control for rain too: muggy days are often wet, and mugginess must be isolated
    # from rain's own suppression (otherwise dew point absorbs the rain effect).
    d["rain_band"] = (pd.cut(d["prcp_inches"].fillna(0), RAIN_EDGES, labels=RAIN_LABELS)
                        .cat.remove_unused_categories())
    res = smf.ols("logy ~ C(ym) + C(dow) + holiday + tavg_f + dewpoint_f"
                  " + C(rain_band) + wind_avg_mph", data=d).fit(**_HAC)
    b, se = res.params["dewpoint_f"], res.bse["dewpoint_f"]
    return {
        "per_F": (np.exp(b) - 1) * 100,
        "p10": (np.exp(b * 10) - 1) * 100,
        "lo10": (np.exp((b - 1.96 * se) * 10) - 1) * 100,
        "hi10": (np.exp((b + 1.96 * se) * 10) - 1) * 100,
        "n": int(res.nobs),
    }


if __name__ == "__main__":  # quick self-check against a CSV dump of daily_trips_weather
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "daily_trips_weather.csv"
    frame = pd.read_csv(path, parse_dates=["date"])
    col = "num_nyc_trips" if "num_nyc_trips" in frame.columns else "num_trips"
    eff, meta = fit_impacts(frame, col)
    print(f"n={meta['n']}  controls R2={meta['r2_controls']:.3f}  full R2={meta['r2_full']:.3f}  "
          f"weather within-month partial-R2={meta['weather_partial_r2']:.3f}\n")
    with pd.option_context("display.max_rows", None, "display.width", 100):
        print(eff.assign(pct=eff.pct.round(1), lo=eff.lo.round(1), hi=eff.hi.round(1)))
