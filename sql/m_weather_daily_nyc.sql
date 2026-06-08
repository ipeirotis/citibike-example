-- m_weather_daily_nyc: materialized (native table) snapshot of the
-- weather_daily_nyc view, for fast and low-cost queries over Central Park
-- daily weather. Rebuild this whenever weather_daily / weather_daily_nyc change.
--
-- Run order: deploy weather_daily.sql and weather_daily_nyc.sql first, then run
-- this file (it is a multi-statement script: CTAS to refresh the data, then
-- ALTER TABLE to (re)apply the table and column descriptions, which a CTAS does
-- not carry over from the source view).

CREATE OR REPLACE TABLE `nyu-datasets.weather.m_weather_daily_nyc` AS
SELECT * FROM `nyu-datasets.weather.weather_daily_nyc`;

ALTER TABLE `nyu-datasets.weather.m_weather_daily_nyc`
  SET OPTIONS(description="Materialized (native table) snapshot of nyu-datasets.weather.weather_daily_nyc for fast, low-cost queries over Central Park (NY CITY CNTRL PARK) daily weather. Rebuild by running sql/m_weather_daily_nyc.sql whenever the views change. Humidity, dew point, wet-bulb, and pressure cover 2016-2024 only.");

ALTER TABLE `nyu-datasets.weather.m_weather_daily_nyc`
  ALTER COLUMN date SET OPTIONS(description="Calendar date of the daily summary; one row per day."),
  ALTER COLUMN year SET OPTIONS(description="Year component of date."),
  ALTER COLUMN month SET OPTIONS(description="Month component of date (1-12)."),
  ALTER COLUMN day SET OPTIONS(description="Day-of-month component of date (1-31)."),
  ALTER COLUMN day_of_week SET OPTIONS(description="Day of week, BigQuery convention: 1=Sunday ... 7=Saturday."),
  ALTER COLUMN is_weekend SET OPTIONS(description="1 if date is Saturday or Sunday, else 0."),
  ALTER COLUMN season SET OPTIONS(description="Northern-Hemisphere meteorological season: Winter (Dec-Feb), Spring (Mar-May), Summer (Jun-Aug), Fall (Sep-Nov)."),
  ALTER COLUMN tmin_f SET OPTIONS(description="Daily minimum air temperature in degrees Fahrenheit (GHCN-D TMIN)."),
  ALTER COLUMN tmax_f SET OPTIONS(description="Daily maximum air temperature in degrees Fahrenheit (GHCN-D TMAX)."),
  ALTER COLUMN tavg_f SET OPTIONS(description="Daily mean air temperature in degrees Fahrenheit (GHCN-D TAVG, or the average of TMIN and TMAX when TAVG is absent)."),
  ALTER COLUMN prcp_inches SET OPTIONS(description="Total daily precipitation (rain plus melted snow) in inches (GHCN-D PRCP); 0 when none reported."),
  ALTER COLUMN snow_inches SET OPTIONS(description="Daily new snowfall in inches (GHCN-D SNOW); 0 when none reported. New snowfall, not depth on the ground."),
  ALTER COLUMN is_rainy SET OPTIONS(description="1 if any measurable precipitation fell, else 0."),
  ALTER COLUMN is_snowy SET OPTIONS(description="1 if any measurable snow fell, else 0."),
  ALTER COLUMN is_hot_day SET OPTIONS(description="1 if the daily high exceeded 90 degrees F, else 0."),
  ALTER COLUMN is_freezing SET OPTIONS(description="1 if the daily low was below freezing (32 degrees F), else 0."),
  ALTER COLUMN snow_depth_inches SET OPTIONS(description="Depth of snow lying on the ground in inches (GHCN-D SNWD); NULL when not reported. Distinct from snow_inches (new snowfall)."),
  ALTER COLUMN rh_avg SET OPTIONS(description="Daily mean relative humidity, percent (GHCN-D RHAV). Central Park coverage 2016-2024; NULL outside that range."),
  ALTER COLUMN rh_min SET OPTIONS(description="Daily minimum relative humidity, percent (GHCN-D RHMN). Central Park coverage 2016-2024; NULL outside that range."),
  ALTER COLUMN rh_max SET OPTIONS(description="Daily maximum relative humidity, percent (GHCN-D RHMX). Central Park coverage 2016-2024; NULL outside that range."),
  ALTER COLUMN is_humid SET OPTIONS(description="1 if mean relative humidity was 70 percent or higher, 0 if lower, NULL when humidity is unavailable."),
  ALTER COLUMN dewpoint_f SET OPTIONS(description="Daily mean dew-point temperature in degrees Fahrenheit (GHCN-D ADPT). Central Park coverage 2016-2024; NULL outside that range."),
  ALTER COLUMN wetbulb_f SET OPTIONS(description="Daily mean wet-bulb temperature in degrees Fahrenheit (GHCN-D AWBT). Central Park coverage 2016-2024; NULL outside that range."),
  ALTER COLUMN sea_level_pressure_hpa SET OPTIONS(description="Daily mean sea-level air pressure in hectopascals (millibars) (GHCN-D ASLP). Central Park coverage 2016-2024; NULL outside that range."),
  ALTER COLUMN wind_avg_mph SET OPTIONS(description="Daily average wind speed in miles per hour (GHCN-D AWND); NULL when not reported. Central Park is sheltered and reads low; best used as a relative signal."),
  ALTER COLUMN wind_gust_mph SET OPTIONS(description="Fastest 2-minute wind speed of the day in miles per hour (GHCN-D WSF2); NULL when not reported."),
  ALTER COLUMN wind_dir_deg SET OPTIONS(description="Direction of the fastest 2-minute wind, degrees clockwise from true north 0-360 (GHCN-D WDF2); NULL when not reported."),
  ALTER COLUMN is_foggy SET OPTIONS(description="1 if fog, ice fog, or freezing fog was observed (GHCN-D WT01), else 0."),
  ALTER COLUMN is_thunder SET OPTIONS(description="1 if thunder was observed (GHCN-D WT03), else 0."),
  ALTER COLUMN is_hazy SET OPTIONS(description="1 if smoke or haze was observed (GHCN-D WT08), else 0.");
