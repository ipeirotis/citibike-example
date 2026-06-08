-- weather_daily: daily GHCN-D weather for every US station, one row per
-- (station, date), with a unifying superset of useful elements.
--
-- This EXTENDS the original view additively: every pre-existing column is kept
-- byte-for-byte in its original position, and new columns are appended at the
-- end so downstream consumers (other projects + weather_daily_nyc) do not break.
--
-- What was added beyond the original tmin/tmax/tavg/prcp/snow set, after
-- confirming each is actually reported (verified against NY CITY CNTRL PARK,
-- station USW00094728) and after checking raw units against known weather:
--
--   * Relative humidity   RHAV/RHMN/RHMX  -> already whole percent (no /10)
--   * Dew point           ADPT            -> tenths degC   (value/10)
--   * Wet-bulb temp       AWBT            -> tenths degC   (value/10)
--   * Pressure            ASLP/ASTP       -> tenths hPa     (value/10)
--   * Wind speed/gust     AWND/WSF2       -> tenths m/s     (value/10)
--   * Wind direction      WDF2            -> degrees        (no scaling)
--   * Snow on the ground  SNWD            -> mm             (no scaling)
--   * Weather-type flags  WT01/WT03/WT08  -> fog / thunder / smoke-haze (1/0)
--
-- Coverage caveat: the humidity / dew-point / wet-bulb / pressure block comes
-- from ASOS-equipped stations and only exists for recent years (~2016 onward;
-- for Central Park it runs 2016-01-01..2024-12-31). It is therefore NULL where
-- the station did not report it -- the same superset philosophy as the rest of
-- the dataset. Temperature, precip, snow, wind and snow-depth span the full
-- record. For the post-2024 humidity tail, NOAA GSOD (noaa_gsod.gsod*, wban
-- 94728) carries daily mean dew point through the present as a fallback source.
--
-- Adding elements to the WHERE..IN list does NOT materially change scan cost:
-- the view already reads the id/element/date/value/qflag columns across every
-- ghcnd_* yearly table; the IN clause only changes which rows survive the scan.

CREATE OR REPLACE VIEW `nyu-datasets.weather.weather_daily` AS

WITH
Station_Map AS (
  SELECT
    S.id AS station_id,
    S.name AS station_name,
    S.longitude, S.latitude,
    ST_GEOGPOINT(S.longitude, S.latitude) AS geo_coord,
    Z.zip_code,
    Z.city,
    S.state,
    C.county_name
  FROM `bigquery-public-data.ghcn_d.ghcnd_stations` S
  JOIN `bigquery-public-data.geo_us_boundaries.zip_codes` Z
    ON ST_CONTAINS(Z.zip_code_geom, ST_GEOGPOINT(S.longitude, S.latitude))
  JOIN `bigquery-public-data.geo_us_boundaries.counties` C
    ON ST_CONTAINS(C.county_geom, ST_GEOGPOINT(S.longitude, S.latitude))
  WHERE
    S.id LIKE 'US%'
    AND S.latitude IS NOT NULL
    AND S.longitude IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY Z.zip_code ORDER BY S.name) = 1
),

Daily_Weather AS (
  SELECT
    id AS station_id,
    date,
    COALESCE(
      MAX(IF(element = 'TAVG' AND qflag IS NULL, value/10.0, NULL)),
      (MAX(IF(element = 'TMAX' AND qflag IS NULL, value/10.0, NULL)) +
       MAX(IF(element = 'TMIN' AND qflag IS NULL, value/10.0, NULL))) / 2
    ) AS tavg_c,
    MAX(IF(element = 'TMIN' AND qflag IS NULL, value/10.0, NULL)) AS tmin_c,
    MAX(IF(element = 'TMAX' AND qflag IS NULL, value/10.0, NULL)) AS tmax_c,
    COALESCE(MAX(IF(element = 'PRCP' AND qflag IS NULL, value/10.0, NULL)), 0) AS prcp_mm,
    COALESCE(MAX(IF(element = 'SNOW' AND qflag IS NULL, value, NULL)), 0) AS snow_mm,
    -- Snow depth on the ground (mm) -- distinct from SNOW (fresh snowfall).
    -- Left NULL (not 0) where unreported, so it is not confused with a measured 0.
    MAX(IF(element = 'SNWD' AND qflag IS NULL, value, NULL)) AS snow_depth_mm,
    -- Relative humidity is stored as whole percent already (no /10).
    MAX(IF(element = 'RHAV' AND qflag IS NULL, value, NULL)) AS rh_avg,
    MAX(IF(element = 'RHMN' AND qflag IS NULL, value, NULL)) AS rh_min,
    MAX(IF(element = 'RHMX' AND qflag IS NULL, value, NULL)) AS rh_max,
    -- Dew point / wet-bulb temperature (tenths of degC).
    MAX(IF(element = 'ADPT' AND qflag IS NULL, value/10.0, NULL)) AS dewpoint_c,
    MAX(IF(element = 'AWBT' AND qflag IS NULL, value/10.0, NULL)) AS wetbulb_c,
    -- Barometric pressure (tenths of hPa).
    MAX(IF(element = 'ASLP' AND qflag IS NULL, value/10.0, NULL)) AS slp_hpa,
    MAX(IF(element = 'ASTP' AND qflag IS NULL, value/10.0, NULL)) AS stp_hpa,
    -- Wind: average + fastest 2-minute speed (tenths of m/s), direction (degrees).
    MAX(IF(element = 'AWND' AND qflag IS NULL, value/10.0, NULL)) AS wind_avg_ms,
    MAX(IF(element = 'WSF2' AND qflag IS NULL, value/10.0, NULL)) AS wind_gust_ms,
    MAX(IF(element = 'WDF2' AND qflag IS NULL, value,      NULL)) AS wind_dir_deg,
    -- Weather-type flags: present (1) only on days the phenomenon was observed.
    MAX(IF(element = 'WT01', 1, 0)) AS is_foggy,
    MAX(IF(element = 'WT03', 1, 0)) AS is_thunder,
    MAX(IF(element = 'WT08', 1, 0)) AS is_hazy
  FROM `bigquery-public-data.ghcn_d.ghcnd_*`
  WHERE
    _TABLE_SUFFIX BETWEEN '1900' AND '2030'
    AND element IN ('TMIN', 'TMAX', 'TAVG', 'PRCP', 'SNOW',
                    'SNWD', 'RHAV', 'RHMN', 'RHMX', 'ADPT', 'AWBT',
                    'ASLP', 'ASTP', 'AWND', 'WSF2', 'WDF2',
                    'WT01', 'WT03', 'WT08')
  GROUP BY station_id, date
)

SELECT
  W.date,
  EXTRACT(YEAR FROM W.date) AS year,
  EXTRACT(MONTH FROM W.date) AS month,
  EXTRACT(DAY FROM W.date) AS day,
  EXTRACT(DAYOFWEEK FROM W.date) AS day_of_week,
  IF(EXTRACT(DAYOFWEEK FROM W.date) IN (1, 7), 1, 0) AS is_weekend,
  CASE
    WHEN EXTRACT(MONTH FROM W.date) IN (12, 1, 2) THEN 'Winter'
    WHEN EXTRACT(MONTH FROM W.date) IN (3, 4, 5) THEN 'Spring'
    WHEN EXTRACT(MONTH FROM W.date) IN (6, 7, 8) THEN 'Summer'
    ELSE 'Fall'
  END AS season,
  M.station_name,
  M.city,
  M.state,
  M.zip_code,
  M.county_name,
  M.longitude,
  M.latitude,
  M.geo_coord,
  W.tmin_c,
  W.tmax_c,
  ROUND(W.tavg_c, 1) AS tavg_c,
  ROUND((W.tmin_c * 9/5) + 32, 1) AS tmin_f,
  ROUND((W.tmax_c * 9/5) + 32, 1) AS tmax_f,
  ROUND((W.tavg_c * 9/5) + 32, 1) AS tavg_f,
  W.prcp_mm,
  ROUND(W.prcp_mm / 25.4, 2) AS prcp_inches,
  W.snow_mm,
  ROUND(W.snow_mm / 25.4, 1) AS snow_inches,
  IF(W.prcp_mm > 0, 1, 0) AS is_rainy,
  IF(W.snow_mm > 0, 1, 0) AS is_snowy,
  IF((W.tmax_c * 9/5) + 32 > 90, 1, 0) AS is_hot_day,
  IF((W.tmin_c * 9/5) + 32 < 32, 1, 0) AS is_freezing,
  ROUND(GREATEST(0, 65 - (W.tavg_c * 9/5 + 32)), 1) AS heating_degree_days,
  ROUND(GREATEST(0, (W.tavg_c * 9/5 + 32) - 65), 1) AS cooling_degree_days,
  -- ── Extended attributes (NULL where the station did not report them) ──────────
  -- Snow depth on the ground (vs snow_mm / snow_inches = fresh snowfall).
  W.snow_depth_mm,
  ROUND(W.snow_depth_mm / 25.4, 1) AS snow_depth_inches,
  -- Relative humidity (percent).
  W.rh_avg,
  W.rh_min,
  W.rh_max,
  CASE WHEN W.rh_avg IS NULL THEN NULL WHEN W.rh_avg >= 70 THEN 1 ELSE 0 END AS is_humid,
  -- Dew point and wet-bulb temperature.
  ROUND(W.dewpoint_c, 1) AS dewpoint_c,
  ROUND((W.dewpoint_c * 9/5) + 32, 1) AS dewpoint_f,
  ROUND(W.wetbulb_c, 1) AS wetbulb_c,
  ROUND((W.wetbulb_c * 9/5) + 32, 1) AS wetbulb_f,
  -- Barometric pressure (hPa).
  ROUND(W.slp_hpa, 1) AS sea_level_pressure_hpa,
  ROUND(W.stp_hpa, 1) AS station_pressure_hpa,
  -- Wind. Note: some stations (e.g. Central Park) are sheltered and read low in
  -- absolute terms; the values are most useful as a relative day-to-day signal.
  ROUND(W.wind_avg_ms, 1) AS wind_avg_ms,
  ROUND(W.wind_avg_ms * 2.23694, 1) AS wind_avg_mph,
  ROUND(W.wind_gust_ms, 1) AS wind_gust_ms,
  ROUND(W.wind_gust_ms * 2.23694, 1) AS wind_gust_mph,
  W.wind_dir_deg,
  -- Weather-type flags (1 = phenomenon observed that day).
  W.is_foggy,
  W.is_thunder,
  W.is_hazy
FROM Daily_Weather W
JOIN Station_Map M ON W.station_id = M.station_id
