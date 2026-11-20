from pydantic import BaseModel, Field
class CalendarInput(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    handover_time: str = Field(min_length=5, max_length=5)
    shutdown_dates: list[str] = Field(default_factory=list, max_length=400)
    effective_at: float | None = None
class ReportInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    job_id: int
    destination: str = Field(default='业务复核组', min_length=2, max_length=120)
    schedule_type: str = Field(default='interval', pattern='^(interval|shift)$')
    interval_seconds: int = Field(default=86400, ge=60, le=2592000)
    delay_seconds: int = Field(default=0, ge=0, le=2592000)
    calendar: CalendarInput | None = None
RevisionInput = CalendarInput
