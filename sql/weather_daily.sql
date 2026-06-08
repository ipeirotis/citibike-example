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

CREATE OR REPLACE VIEW `nyu-datasets.weather.weather_daily`
(
  date OPTIONS(description="Calendar date of the daily summary; one row per station per day."),
  year OPTIONS(description="Year component of date."),
  month OPTIONS(description="Month component of date (1-12)."),
  day OPTIONS(description="Day-of-month component of date (1-31)."),
  day_of_week OPTIONS(description="Day of week, BigQuery convention: 1=Sunday ... 7=Saturday."),
  is_weekend OPTIONS(description="1 if date is Saturday or Sunday, else 0."),
  season OPTIONS(description="Northern-Hemisphere meteorological season: Winter (Dec-Feb), Spring (Mar-May), Summer (Jun-Aug), Fall (Sep-Nov)."),
  station_name OPTIONS(description="GHCN-Daily station name (e.g. 'NY CITY CNTRL PARK')."),
  city OPTIONS(description="City of the ZIP code containing the station (from geo_us_boundaries.zip_codes)."),
  state OPTIONS(description="Two-letter US state code of the station."),
  zip_code OPTIONS(description="ZIP code whose polygon contains the station coordinates."),
  county_name OPTIONS(description="County whose polygon contains the station coordinates (from geo_us_boundaries.counties)."),
  longitude OPTIONS(description="Station longitude in decimal degrees (WGS84)."),
  latitude OPTIONS(description="Station latitude in decimal degrees (WGS84)."),
  geo_coord OPTIONS(description="Station location as a GEOGRAPHY point built from (longitude, latitude)."),
  tmin_c OPTIONS(description="Daily minimum air temperature in degrees Celsius (GHCN-D element TMIN)."),
  tmax_c OPTIONS(description="Daily maximum air temperature in degrees Celsius (GHCN-D element TMAX)."),
  tavg_c OPTIONS(description="Daily mean air temperature in degrees Celsius: GHCN-D TAVG when reported, otherwise the average of TMIN and TMAX."),
  tmin_f OPTIONS(description="Daily minimum air temperature in degrees Fahrenheit (converted from tmin_c)."),
  tmax_f OPTIONS(description="Daily maximum air temperature in degrees Fahrenheit (converted from tmax_c)."),
  tavg_f OPTIONS(description="Daily mean air temperature in degrees Fahrenheit (converted from tavg_c)."),
  prcp_mm OPTIONS(description="Total daily precipitation (rain plus melted snow) in millimeters (GHCN-D PRCP); 0 when none reported."),
  prcp_inches OPTIONS(description="Total daily precipitation in inches (converted from prcp_mm)."),
  snow_mm OPTIONS(description="Daily new snowfall in millimeters (GHCN-D SNOW); 0 when none reported. New snowfall, not depth on the ground."),
  snow_inches OPTIONS(description="Daily new snowfall in inches (converted from snow_mm)."),
  is_rainy OPTIONS(description="1 if any measurable precipitation fell (prcp_mm > 0), else 0."),
  is_snowy OPTIONS(description="1 if any measurable snow fell (snow_mm > 0), else 0."),
  is_hot_day OPTIONS(description="1 if the daily high exceeded 90 degrees F (tmax_f > 90), else 0."),
  is_freezing OPTIONS(description="1 if the daily low was below freezing, 32 degrees F (tmin_f < 32), else 0."),
  heating_degree_days OPTIONS(description="Heating degree days = max(0, 65 - tavg_f). Larger values mean colder days with more heating demand."),
  cooling_degree_days OPTIONS(description="Cooling degree days = max(0, tavg_f - 65). Larger values mean hotter days with more cooling demand."),
  snow_depth_mm OPTIONS(description="Depth of snow lying on the ground in millimeters (GHCN-D SNWD); NULL when not reported. Distinct from snow_mm (new snowfall)."),
  snow_depth_inches OPTIONS(description="Depth of snow on the ground in inches (converted from snow_depth_mm)."),
  rh_avg OPTIONS(description="Daily mean relative humidity, percent (GHCN-D RHAV). Reported only by automated (ASOS) stations in recent years; NULL otherwise."),
  rh_min OPTIONS(description="Daily minimum relative humidity, percent (GHCN-D RHMN). ASOS stations in recent years only; NULL otherwise."),
  rh_max OPTIONS(description="Daily maximum relative humidity, percent (GHCN-D RHMX). ASOS stations in recent years only; NULL otherwise."),
  is_humid OPTIONS(description="1 if mean relative humidity was 70 percent or higher (rh_avg >= 70), 0 if lower, NULL when humidity is unavailable."),
  dewpoint_c OPTIONS(description="Daily mean dew-point temperature in degrees Celsius (GHCN-D ADPT). ASOS stations in recent years only; NULL otherwise."),
  dewpoint_f OPTIONS(description="Daily mean dew-point temperature in degrees Fahrenheit (converted from dewpoint_c)."),
  wetbulb_c OPTIONS(description="Daily mean wet-bulb temperature in degrees Celsius (GHCN-D AWBT). ASOS stations in recent years only; NULL otherwise."),
  wetbulb_f OPTIONS(description="Daily mean wet-bulb temperature in degrees Fahrenheit (converted from wetbulb_c)."),
  sea_level_pressure_hpa OPTIONS(description="Daily mean sea-level air pressure in hectopascals (millibars) (GHCN-D ASLP). ASOS stations in recent years only; NULL otherwise."),
  station_pressure_hpa OPTIONS(description="Daily mean station-level air pressure in hectopascals (millibars) (GHCN-D ASTP). ASOS stations in recent years only; NULL otherwise."),
  wind_avg_ms OPTIONS(description="Daily average wind speed in meters per second (GHCN-D AWND); NULL when not reported. Sheltered stations (e.g. Central Park) read low; best used as a relative signal."),
  wind_avg_mph OPTIONS(description="Daily average wind speed in miles per hour (converted from wind_avg_ms)."),
  wind_gust_ms OPTIONS(description="Fastest 2-minute wind speed of the day in meters per second (GHCN-D WSF2); NULL when not reported."),
  wind_gust_mph OPTIONS(description="Fastest 2-minute wind speed of the day in miles per hour (converted from wind_gust_ms)."),
  wind_dir_deg OPTIONS(description="Direction of the fastest 2-minute wind, degrees clockwise from true north 0-360 (GHCN-D WDF2); NULL when not reported."),
  is_foggy OPTIONS(description="1 if fog, ice fog, or freezing fog was observed (GHCN-D WT01), else 0."),
  is_thunder OPTIONS(description="1 if thunder was observed (GHCN-D WT03), else 0."),
  is_hazy OPTIONS(description="1 if smoke or haze was observed (GHCN-D WT08), else 0.")
)
OPTIONS(description="Daily weather summaries for all US GHCN-Daily stations, one row per station per day. Superset of useful elements (temperature, precipitation, snow, snow depth, humidity, dew point, wet-bulb, pressure, wind, weather-type flags) in metric and imperial units, joined to ZIP/city/county. Source: bigquery-public-data.ghcn_d. Humidity/dew-point/wet-bulb/pressure come from ASOS stations in recent years only and are NULL elsewhere.")
AS

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
