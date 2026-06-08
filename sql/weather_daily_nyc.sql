-- weather_daily_nyc: Central Park (NY CITY CNTRL PARK) slice of weather_daily,
-- the convenience view most NYC projects (including this Citibike pipeline) read.
--
-- Additive change: the original 16 columns are preserved in their exact
-- positions; the extended attributes (humidity, dew point, wet-bulb, pressure,
-- wind, snow depth, weather-type flags) are appended at the end, favouring the
-- imperial units this view already uses.
--
-- Coverage note: humidity / dew point / wet-bulb / pressure exist for Central
-- Park only over 2016-01-01..2024-12-31, so those columns are NULL outside that
-- window; temperature, precip, snow, snow depth and wind span the full record.

CREATE OR REPLACE VIEW `nyu-datasets.weather.weather_daily_nyc` AS
SELECT
    date, year, month, day, day_of_week, is_weekend, season,
    tmin_f, tmax_f, tavg_f,
    prcp_inches, snow_inches,
    is_rainy, is_snowy, is_hot_day, is_freezing,
    -- ── Appended extended attributes ─────────────────────────────────────────
    snow_depth_inches,
    rh_avg, rh_min, rh_max, is_humid,
    dewpoint_f, wetbulb_f,
    sea_level_pressure_hpa,
    wind_avg_mph, wind_gust_mph, wind_dir_deg,
    is_foggy, is_thunder, is_hazy
  FROM `nyu-datasets.weather.weather_daily`
  WHERE station_name = 'NY CITY CNTRL PARK'
  ORDER BY date DESC
