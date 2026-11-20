from sqlalchemy import String, Double, ForeignKey, Boolean, Integer, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Report(Base):
    __tablename__ = 'reports'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    destination: Mapped[str] = mapped_column(String(120))
    schedule_type: Mapped[str] = mapped_column(String(16), default='interval', server_default='interval')
    interval_seconds: Mapped[int]
    next_run: Mapped[float] = mapped_column(Double)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
class ReportCalendar(Base):
    __tablename__ = 'report_calendars'
    __table_args__ = (UniqueConstraint('report_id', 'version', name='uq_calendar_version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    weekdays: Mapped[str] = mapped_column(String(24))
    handover_time: Mapped[str] = mapped_column(String(5))
    shutdown_dates: Mapped[str] = mapped_column(Text, default='[]')
    effective_at: Mapped[float] = mapped_column(Double)
    created_at: Mapped[float] = mapped_column(Double)
    created_by: Mapped[str] = mapped_column(String(160), default='')
class Shift(Base):
    __tablename__ = 'shifts'
    __table_args__ = (UniqueConstraint('report_id', 'due_at', name='uq_shift_due'), Index('ix_shift_status_due', 'status', 'due_at'))
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    calendar_id: Mapped[int] = mapped_column(ForeignKey('report_calendars.id'))
    calendar_version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    local_date: Mapped[str] = mapped_column(String(10))
    local_time: Mapped[str] = mapped_column(String(5))
    due_at: Mapped[float] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    delivery_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 归档 id，见 deliveries.shift_id
    claimed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    delivered_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey('reports.id'))
    created_at: Mapped[float] = mapped_column(Double)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(120))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey('shifts.id'), nullable=True, unique=True)
    planned_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    calendar_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backfill: Mapped[bool] = mapped_column(Boolean, default=False, server_default='0')
