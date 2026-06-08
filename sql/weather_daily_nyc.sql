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

CREATE OR REPLACE VIEW `nyu-datasets.weather.weather_daily_nyc`
(
  date OPTIONS(description="Calendar date of the daily summary; one row per day, newest first."),
  year OPTIONS(description="Year component of date."),
  month OPTIONS(description="Month component of date (1-12)."),
  day OPTIONS(description="Day-of-month component of date (1-31)."),
  day_of_week OPTIONS(description="Day of week, BigQuery convention: 1=Sunday ... 7=Saturday."),
  is_weekend OPTIONS(description="1 if date is Saturday or Sunday, else 0."),
  season OPTIONS(description="Northern-Hemisphere meteorological season: Winter (Dec-Feb), Spring (Mar-May), Summer (Jun-Aug), Fall (Sep-Nov)."),
  tmin_f OPTIONS(description="Daily minimum air temperature in degrees Fahrenheit (GHCN-D TMIN)."),
  tmax_f OPTIONS(description="Daily maximum air temperature in degrees Fahrenheit (GHCN-D TMAX)."),
  tavg_f OPTIONS(description="Daily mean air temperature in degrees Fahrenheit (GHCN-D TAVG, or the average of TMIN and TMAX when TAVG is absent)."),
  prcp_inches OPTIONS(description="Total daily precipitation (rain plus melted snow) in inches (GHCN-D PRCP); 0 when none reported."),
  snow_inches OPTIONS(description="Daily new snowfall in inches (GHCN-D SNOW); 0 when none reported. New snowfall, not depth on the ground."),
  is_rainy OPTIONS(description="1 if any measurable precipitation fell, else 0."),
  is_snowy OPTIONS(description="1 if any measurable snow fell, else 0."),
  is_hot_day OPTIONS(description="1 if the daily high exceeded 90 degrees F, else 0."),
  is_freezing OPTIONS(description="1 if the daily low was below freezing (32 degrees F), else 0."),
  snow_depth_inches OPTIONS(description="Depth of snow lying on the ground in inches (GHCN-D SNWD); NULL when not reported. Distinct from snow_inches (new snowfall)."),
  rh_avg OPTIONS(description="Daily mean relative humidity, percent (GHCN-D RHAV). Central Park coverage 2016-2024; NULL outside that range."),
  rh_min OPTIONS(description="Daily minimum relative humidity, percent (GHCN-D RHMN). Central Park coverage 2016-2024; NULL outside that range."),
  rh_max OPTIONS(description="Daily maximum relative humidity, percent (GHCN-D RHMX). Central Park coverage 2016-2024; NULL outside that range."),
  is_humid OPTIONS(description="1 if mean relative humidity was 70 percent or higher, 0 if lower, NULL when humidity is unavailable."),
  dewpoint_f OPTIONS(description="Daily mean dew-point temperature in degrees Fahrenheit (GHCN-D ADPT). Central Park coverage 2016-2024; NULL outside that range."),
  wetbulb_f OPTIONS(description="Daily mean wet-bulb temperature in degrees Fahrenheit (GHCN-D AWBT). Central Park coverage 2016-2024; NULL outside that range."),
  sea_level_pressure_hpa OPTIONS(description="Daily mean sea-level air pressure in hectopascals (millibars) (GHCN-D ASLP). Central Park coverage 2016-2024; NULL outside that range."),
  wind_avg_mph OPTIONS(description="Daily average wind speed in miles per hour (GHCN-D AWND); NULL when not reported. Central Park is sheltered and reads low; best used as a relative signal."),
  wind_gust_mph OPTIONS(description="Fastest 2-minute wind speed of the day in miles per hour (GHCN-D WSF2); NULL when not reported."),
  wind_dir_deg OPTIONS(description="Direction of the fastest 2-minute wind, degrees clockwise from true north 0-360 (GHCN-D WDF2); NULL when not reported."),
  is_foggy OPTIONS(description="1 if fog, ice fog, or freezing fog was observed (GHCN-D WT01), else 0."),
  is_thunder OPTIONS(description="1 if thunder was observed (GHCN-D WT03), else 0."),
  is_hazy OPTIONS(description="1 if smoke or haze was observed (GHCN-D WT08), else 0.")
)
OPTIONS(description="Central Park (NY CITY CNTRL PARK) daily weather: the NYC slice of nyu-datasets.weather.weather_daily, ordered newest first. Humidity, dew point, wet-bulb, and pressure are available only for 2016-2024; temperature, precipitation, snow, snow depth, and wind span the full record.")
AS
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
