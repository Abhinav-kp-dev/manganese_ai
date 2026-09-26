-- Production deployment schema (PostgreSQL + PostGIS). The application creates the
-- same tables via SQLAlchemy; this file adds the spatial columns and indexes.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS mines (
  mine_id text PRIMARY KEY, mine_name text NOT NULL, district text, state text,
  latitude double precision, longitude double precision, mine_type text,
  rated_capacity_tpd double precision, cluster_id text, mn_grade_pct double precision,
  haul_distance_km double precision, depth_m double precision, workforce integer,
  geom geometry(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) STORED
);

CREATE TABLE IF NOT EXISTS boreholes (
  borehole_id text PRIMARY KEY, mine_id text, latitude double precision, longitude double precision,
  depth_m double precision, grade_mn_pct double precision, thickness_m double precision, source text,
  observation_date date, is_synthetic boolean NOT NULL DEFAULT true,
  geom geometry(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) STORED
);
CREATE INDEX IF NOT EXISTS boreholes_geom_idx ON boreholes USING gist (geom);

CREATE TABLE IF NOT EXISTS production_logs (
  mine_id text REFERENCES mines(mine_id), date date, production_tonnes double precision,
  production_target double precision, operating_days integer, downtime_hours double precision,
  equipment_availability_pct double precision, maintenance_hours double precision,
  blasting_tonnes_broken double precision, stockpile_tonnes double precision,
  workforce_headcount integer, is_synthetic boolean NOT NULL DEFAULT true,
  PRIMARY KEY (mine_id, date)
);

CREATE TABLE IF NOT EXISTS weather_features (
  mine_id text REFERENCES mines(mine_id), date date, rainfall_mm double precision, rainy_days integer,
  soil_moisture double precision, ndvi double precision, land_surface_temp_c double precision,
  is_monsoon boolean, is_synthetic boolean NOT NULL DEFAULT true, PRIMARY KEY (mine_id, date)
);

CREATE TABLE IF NOT EXISTS reserve_confidence_grid (
  cell_id integer PRIMARY KEY, latitude double precision, longitude double precision,
  geometry_wkt text, confidence_score double precision, uncertainty double precision, zone text,
  grid_resolution_m double precision, model_version text, last_updated timestamptz DEFAULT now(),
  geom geometry(Polygon, 4326) GENERATED ALWAYS AS (ST_GeomFromText(geometry_wkt, 4326)) STORED
);
CREATE INDEX IF NOT EXISTS rcg_geom_idx ON reserve_confidence_grid USING gist (geom);

-- Training queries for production models must exclude synthetic rows once real data exists:
--   SELECT * FROM production_logs WHERE is_synthetic = FALSE;
