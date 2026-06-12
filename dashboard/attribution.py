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


def _num(s: pd.Series) -> pd.Series:
    """Coerce a column to numpy ``float64`` (non-numeric / nulls -> ``NaN``).

    BigQuery's ``to_dataframe()`` returns integer columns as pandas *nullable*
    ``Int64`` (e.g. ``is_thunder``, ``is_foggy``, the trip counts). The model math
    here — climatology imputation, ``clip``, and statsmodels — assumes plain
    ``float64``: pandas 3.0 refuses to ``fillna`` a nullable-integer column with a
    fractional value ("cannot safely cast non-equivalent object to int64"), so leave
    no nullable ints in the model frame. ``astype`` maps ``pd.NA`` to ``np.nan``.
    """
    return pd.to_numeric(s, errors="coerce").astype("float64")


def _prep(df: pd.DataFrame, trips_col: str) -> pd.DataFrame:
    """Daily frame -> model frame (log trips, calendar controls, weather bands)."""
    d = df.copy()
    d["y"] = _num(d[trips_col])
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
        d[c] = _num(d[c]).fillna(0.0)
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
    d["y"] = _num(d[trips_col])
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


# ------------------------------------------------------------------------ hourly
# Hourly weather-shock models over `hourly_trips_weather`. The hourly grain lets
# the calendar controls saturate one level further than the daily model: a fixed
# effect for every *calendar day* (absorbed by within-day demeaning — the within
# estimator; 4.7k dummies would be infeasible dense). Day FE swallow growth,
# season, weekday, holidays and the day's overall weather, so a rain coefficient
# is identified purely from *within-day* contrasts: raining 8am vs dry 6pm of
# the same day, net of the diurnal pattern (hour-of-day x weekend dummies).
#
# The estimand is deliberately different from fit_impacts': "what happens in
# the very hour rain falls", which includes riders shifting to drier hours of
# the same day. The daily model's rain bars give the net day effect; together
# they bracket displacement (a lesson of the distributed-lag literature).
# Inference clusters on the day — hours within a day share weather and demand
# shocks, so HAC-by-observation would be too optimistic.
HOUR_BANDS = [(0, 6, "overnight 12–6a"), (7, 9, "AM rush 7–9a"), (10, 15, "midday 10a–3p"),
              (16, 19, "PM rush 4–7p"), (20, 23, "evening 8–11p")]
HEAVY_RAIN_IN = 0.10   # >= 0.10 in/hour: heavy at the hourly grain
PROFILE_LEADS = 2      # hours before the rain (anticipation / falsification)
PROFILE_LAGS = 4       # hours after (wet streets, rebound) -> cumulative effect


def _hourly_frame(df: pd.DataFrame, trips_col: str) -> pd.DataFrame:
    """Hourly frame -> model frame (log trips, clock keys, rain leads/lags)."""
    d = df.copy()
    d["y"] = _num(d[trips_col])
    for c in ["is_raining", "is_snowing", "prcp_inches"]:
        d[c] = _num(d[c])
    d["ts"] = d["date"] + pd.to_timedelta(d["hour"].astype(int), unit="h")
    d = d.sort_values("ts")
    d["heavy_rain"] = ((d["is_raining"] == 1) & (d["prcp_inches"] >= HEAVY_RAIN_IN)).astype(float)
    # Leads/lags must align to real clock hours, so shift on the complete hourly
    # grid (zero-trip hours are absent from the mart; their weather reads NaN and
    # those rows drop later rather than mis-aligning the event time).
    grid = pd.date_range(d["ts"].min(), d["ts"].max(), freq="h")
    rain = d.set_index("ts")["is_raining"].reindex(grid)
    for k in range(1, PROFILE_LEADS + 1):
        d[f"rain_lead{k}"] = d["ts"].map(rain.shift(-k))
    for k in range(1, PROFILE_LAGS + 1):
        d[f"rain_lag{k}"] = d["ts"].map(rain.shift(k))
    d = d[d["y"] > 0].copy()  # log outcome; zero-trip hours carry no signal here
    d["logy"] = np.log(d["y"])
    d["hw"] = (d["hour"].astype(int).astype(str) + "_"
               + (d["date"].dt.dayofweek >= 5).astype(int).astype(str))
    return d


def _within_day_ols(d: pd.DataFrame, xcols: list[str]):
    """OLS of log trips on `xcols`, with day fixed effects and day-clustered SEs.

    Day FE are absorbed by demeaning outcome and regressors within each date
    (Frisch–Waugh — identical point estimates to 4.7k day dummies). Hour-of-day x
    weekend dummies enter as regressors so the diurnal shape is controlled.
    """
    import statsmodels.api as sm

    hw = pd.get_dummies(d["hw"], prefix="hw", drop_first=True).astype(float)
    X = pd.concat([d[xcols].astype(float), hw], axis=1)
    keep = X.notna().all(axis=1) & d["logy"].notna()
    X, y = X.loc[keep], d.loc[keep, "logy"]
    days = d.loc[keep, "date"].values
    Xd = X - X.groupby(days).transform("mean")
    yd = y - y.groupby(days).transform("mean")
    res = sm.OLS(yd, Xd).fit(cov_type="cluster", cov_kwds={"groups": days})
    res._n_days = len(pd.unique(days))  # carried for reporting
    return res


def _pct(res, name: str) -> dict:
    b, se = res.params[name], res.bse[name]
    return {"pct": (np.exp(b) - 1) * 100,
            "lo": (np.exp(b - 1.96 * se) - 1) * 100,
            "hi": (np.exp(b + 1.96 * se) - 1) * 100}


def fit_hourly_rain_profile(df: pd.DataFrame, trips_col: str) -> tuple[pd.DataFrame, dict]:
    """Event-time footprint of an hour of rain: leads, the hour itself, lags.

    Returns (profile, meta): one row per event hour k (-PROFILE_LEADS … 0 …
    +PROFILE_LAGS, where 0 is the raining hour and negative k is *before* the
    rain), and meta with n / n_days / the cumulative 0..+lags effect. The leads
    double as a falsification check: hours before rain carry no wet streets, so
    a large lead effect would flag leftover confounding (a small one reads as
    anticipation — skies darken before rain reaches the gauge).
    """
    d = _hourly_frame(df, trips_col)
    leads = [f"rain_lead{k}" for k in range(PROFILE_LEADS, 0, -1)]
    lags = [f"rain_lag{k}" for k in range(1, PROFILE_LAGS + 1)]
    terms = leads + ["is_raining"] + lags
    res = _within_day_ols(d, terms + ["is_snowing"])

    rows = []
    for name, k in zip(terms, list(range(-PROFILE_LEADS, 0)) + list(range(0, PROFILE_LAGS + 1))):
        rows.append({"k": k, **_pct(res, name)})
    # Cumulative effect of one raining hour over that hour + the next lags
    # (vector contrast on the joint covariance, as in _contrast).
    names = ["is_raining"] + lags
    vec = np.ones(len(names))
    b = float(vec @ res.params[names].values)
    se = float(np.sqrt(vec @ res.cov_params().loc[names, names].values @ vec))
    meta = {"n": int(res.nobs), "n_days": res._n_days,
            "cum_pct": (np.exp(b) - 1) * 100,
            "cum_lo": (np.exp(b - 1.96 * se) - 1) * 100,
            "cum_hi": (np.exp(b + 1.96 * se) - 1) * 100}
    return pd.DataFrame(rows), meta


def fit_hourly_rain_by_daypart(df: pd.DataFrame, trips_col: str) -> tuple[pd.DataFrame, dict]:
    """Partial effect of rain *falling in that hour*, by daypart.

    Rain enters interacted with the daypart bands (plus one heavy-rain shifter,
    the hourly nonlinearity), so each coefficient is that daypart's own rain
    elasticity under day FE — the commute-vs-leisure contrast, and the casual-
    vs-member gradient when fit per rider segment.
    """
    d = _hourly_frame(df, trips_col)
    cols = []
    for lo, hi, label in HOUR_BANDS:
        col = f"rain_{lo}_{hi}"
        d[col] = d["is_raining"] * d["hour"].between(lo, hi).astype(float)
        cols.append((col, label))
    res = _within_day_ols(d, [c for c, _ in cols] + ["heavy_rain", "is_snowing"])
    rows = [{"daypart": label, **_pct(res, col)} for col, label in cols]
    meta = {"n": int(res.nobs), "n_days": res._n_days, "heavy_extra": _pct(res, "heavy_rain")}
    return pd.DataFrame(rows), meta


# --------------------------------------------------------------------------- KPI
# Weather-adjusted ridership: model the trips you'd expect for each day's weather
# *and* the time of year, then strip the weather out so growth and period-to-period
# comparisons are apples-to-apples. Unlike fit_impacts (which uses month fixed
# effects to isolate within-month weather elasticities), this predicts the seasonal
# level *from weather*, then contrasts each day's actual weather against the
# day-of-year climatological normal to get "how much did the weather help or hurt".
_KPI_WX = ["tavg_f", "wind_avg_mph", "prcp_cap", "rain01", "snow_cap",
           "snow_depth_inches", "is_thunder", "is_foggy"]
_KPI_FORMULA = ("logy ~ C(ym) + C(dow) + holiday + bs(tavg_f, df=5) + wind_avg_mph"
                " + prcp_cap + rain01 + snow_cap + snow_depth_inches + is_thunder + is_foggy")


def _prep_kpi(df: pd.DataFrame, trips_col: str) -> pd.DataFrame:
    d = df.copy()
    d["y"] = _num(d[trips_col])
    d = d[d["y"] > 0].sort_values("date").reset_index(drop=True)
    d["logy"] = np.log(d["y"])
    d["ym"] = d["date"].dt.year * 12 + d["date"].dt.month
    d["dow"] = d["date"].dt.dayofweek
    d["doy"] = d["date"].dt.dayofyear
    hol = USFederalHolidayCalendar().holidays(d["date"].min(), d["date"].max())
    d["holiday"] = d["date"].isin(hol).astype(int)
    # Keep unreported weather as NaN — a NULL precip/snow is "not reported" (the
    # ~2-week lag on the weather feed, or a station gap), NOT a measured dry day.
    # weather_adjusted_daily() imputes these from day-of-year climatology, so an
    # unreported day reads as seasonally neutral rather than as favorable dry
    # weather. (clip and the `> 0` comparison both propagate NaN.)
    for c in ["prcp_inches", "snow_inches", "snow_depth_inches", "is_thunder", "is_foggy",
              "tavg_f", "wind_avg_mph"]:
        d[c] = _num(d[c])
    # Cap precip/snow: past ~1.25in rain / 6in snow the system is already at its
    # weather floor, and uncapped values make the log model over-predict shutdowns.
    d["prcp_cap"] = d["prcp_inches"].clip(0, 1.25)
    d["rain01"] = np.where(d["prcp_inches"].isna(), np.nan, (d["prcp_inches"] > 0).astype(float))
    d["snow_cap"] = d["snow_inches"].clip(0, 6.0)
    return d


def _doy_climatology(d: pd.DataFrame, cols: list[str]) -> dict[str, pd.Series]:
    """Smoothed day-of-year normal for each weather column (circular 15-day mean)."""
    clim = {}
    for v in cols:
        m = d.groupby("doy")[v].mean().reindex(range(1, 367)).interpolate(limit_direction="both")
        sm = pd.concat([m, m, m]).rolling(15, center=True, min_periods=1).mean().iloc[366:732]
        sm.index = range(1, 367)
        clim[v] = sm
    return clim


def weather_adjusted_daily(df: pd.DataFrame, trips_col: str) -> pd.DataFrame:
    """One row per day: actual, model-expected, weather_effect, and weather-adjusted trips.

    * ``expected``        — trips the model predicts for the day (calendar + actual weather).
    * ``weather_effect``  — fractional lift/drag of the day's weather vs the day-of-year
                            climatological normal (``+0.05`` = weather added 5%).
    * ``adjusted``        — ``actual / (1 + weather_effect)``: trips under normal weather.
    """
    d = _prep_kpi(df, trips_col)
    clim = _doy_climatology(d, _KPI_WX)          # day-of-year normals (skip NaNs)
    # Impute any *unreported* weather from climatology — seasonally neutral, never a
    # fabricated dry day — so the ~2-week feed lag and station gaps don't masquerade
    # as favorable weather. An imputed day sits at its seasonal norm, so its weather
    # contribution cancels (weather_effect -> 0, adjusted == actual). Imputing here
    # (vs. dropping) also keeps every month present for the month fixed effects.
    for v in _KPI_WX:
        d[v] = d[v].fillna(d["doy"].map(clim[v]))
    res = smf.ols(_KPI_FORMULA, data=d).fit()
    pred_actual = res.predict(d)
    normal = d.copy()
    for v in _KPI_WX:
        normal[v] = d["doy"].map(clim[v])
    pred_normal = res.predict(normal)
    out = pd.DataFrame({
        "date": d["date"].values,
        "actual": d["y"].values,
        "expected": np.exp(pred_actual).values,
        "weather_effect": (np.exp(pred_actual - pred_normal) - 1).values,
    })
    out["adjusted"] = out["actual"] / (1 + out["weather_effect"])
    return out


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

    adj = weather_adjusted_daily(frame, col)
    adj["year"] = adj["date"].dt.year
    yr = adj.groupby("year").agg(actual=("actual", "sum"), adjusted=("adjusted", "sum"))
    yr["weather_pct"] = (yr["actual"] / yr["adjusted"] - 1) * 100
    print("\nweather-adjusted annual totals + weather favorability:")
    print(yr.assign(actual=(yr.actual / 1e6).round(1), adjusted=(yr.adjusted / 1e6).round(1)).round(1))

