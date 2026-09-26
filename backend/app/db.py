"""Database layer. SQLite by default; set DATABASE_URL for PostgreSQL/PostGIS in deployment."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA_DIR = Path(os.getenv("MH_DATA_DIR", Path(__file__).resolve().parents[1] / "var"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'manganese_horizon.db'}")

engine = create_engine(DATABASE_URL, future=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Mine(Base):
    __tablename__ = "mines"
    mine_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    mine_name: Mapped[str] = mapped_column(String(64))
    district: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    mine_type: Mapped[str] = mapped_column(String(32))
    rated_capacity_tpd: Mapped[float] = mapped_column(Float)
    cluster_id: Mapped[str] = mapped_column(String(8))
    mn_grade_pct: Mapped[float] = mapped_column(Float)
    haul_distance_km: Mapped[float] = mapped_column(Float)
    depth_m: Mapped[float] = mapped_column(Float)
    workforce: Mapped[int] = mapped_column(Integer)


class Borehole(Base):
    __tablename__ = "boreholes"
    borehole_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    mine_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    depth_m: Mapped[float] = mapped_column(Float)
    grade_mn_pct: Mapped[float] = mapped_column(Float)
    thickness_m: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64))
    observation_date: Mapped[datetime] = mapped_column(Date)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class Occurrence(Base):
    __tablename__ = "occurrences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductionLog(Base):
    __tablename__ = "production_logs"
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.mine_id"), primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    production_tonnes: Mapped[float] = mapped_column(Float)
    production_target: Mapped[float] = mapped_column(Float)
    operating_days: Mapped[int] = mapped_column(Integer)
    downtime_hours: Mapped[float] = mapped_column(Float)
    equipment_availability_pct: Mapped[float] = mapped_column(Float)
    maintenance_hours: Mapped[float] = mapped_column(Float)
    blasting_tonnes_broken: Mapped[float] = mapped_column(Float)
    stockpile_tonnes: Mapped[float] = mapped_column(Float)
    workforce_headcount: Mapped[int] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class WeatherFeature(Base):
    __tablename__ = "weather_features"
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.mine_id"), primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    rainfall_mm: Mapped[float] = mapped_column(Float)
    rainy_days: Mapped[int] = mapped_column(Integer)
    soil_moisture: Mapped[float] = mapped_column(Float)
    ndvi: Mapped[float] = mapped_column(Float)
    land_surface_temp_c: Mapped[float] = mapped_column(Float)
    is_monsoon: Mapped[bool] = mapped_column(Boolean)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class MinePlan(Base):
    """Ex-ante plan per mine-month: what is known before the month starts."""
    __tablename__ = "mine_plans"
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.mine_id"), primary_key=True)
    month: Mapped[datetime] = mapped_column(Date, primary_key=True)
    planned_operating_days: Mapped[int] = mapped_column(Integer)
    planned_maintenance_hours: Mapped[float] = mapped_column(Float)
    fleet_health_index: Mapped[float] = mapped_column(Float)
    blast_window_days: Mapped[int] = mapped_column(Integer)
    rainfall_forecast_mm: Mapped[float] = mapped_column(Float)
    rainy_days_forecast: Mapped[int] = mapped_column(Integer)
    lst_forecast_c: Mapped[float] = mapped_column(Float)
    production_target: Mapped[float] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class ReserveConfidenceCell(Base):
    __tablename__ = "reserve_confidence_grid"
    cell_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geometry_wkt: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float)
    uncertainty: Mapped[float] = mapped_column(Float)
    zone: Mapped[str] = mapped_column(String(16))
    grid_resolution_m: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(32))
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Forecast(Base):
    __tablename__ = "forecasts"
    forecast_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.mine_id"))
    forecast_date: Mapped[datetime] = mapped_column(Date)
    horizon: Mapped[int] = mapped_column(Integer)
    p10: Mapped[float] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float)
    p90: Mapped[float] = mapped_column(Float)
    target_achievement_prob: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16))
    model_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"
    recommendation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("forecasts.forecast_id"))
    priority: Mapped[str] = mapped_column(String(16))
    action_title: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    supporting_features: Mapped[dict] = mapped_column(JSON)
    assumptions: Mapped[list] = mapped_column(JSON)
    tonnes: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_key: Mapped[str] = mapped_column(String(128))
    action_title: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(16))
    decided_by: Mapped[str] = mapped_column(String(64))
    mine_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    client_timestamp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    synced_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalWeather(Base):
    """Real observations pulled by the pipeline (e.g. NASA POWER), kept apart from model features."""
    __tablename__ = "external_weather"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    mine_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    month: Mapped[datetime] = mapped_column(Date, primary_key=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    rainy_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    land_surface_temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | manual | cli | startup
    status: Mapped[str] = mapped_column(String(16))   # running | ok | skipped | failed
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def init_db():
    from . import auth  # noqa: F401  (registers the users table)
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns():
    """Minimal forward-only migration: add nullable columns introduced after a DB was created."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))
