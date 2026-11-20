"""班历排班：按收件地时区、星期与交班时刻产生班次。

规则：
- 停工日（按当地日期）跳过；
- 夏令时缺失的当地时刻跳过；重复时刻只取较早一次（fold=0）；
- 班历按版本生效时刻分段生效，due_at 落在哪一段就归属哪个版本；
- 物化窗口：欠发最多回补 BACKFILL_SECONDS，向前预排 HORIZON_SECONDS。
"""
import time, json
from datetime import datetime, date, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select, func
from src.models import ReportCalendar, Shift

HORIZON_SECONDS = 14 * 86400
BACKFILL_SECONDS = 45 * 86400
UTC = timezone.utc


def load_tz(name):
    if not isinstance(name, str) or len(name) > 64:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def resolve_local(tz, day: date, hhmm: str):
    """把当地日期+时刻解析成确定瞬间。返回 (aware_datetime, None) 或 (None, 'dst-gap')。"""
    naive = datetime.combine(day, dtime(int(hhmm[:2]), int(hhmm[3:5])))
    valid = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        back = aware.astimezone(UTC).astimezone(tz)
        if back.replace(tzinfo=None) == naive and back.fold == fold:
            valid.append(aware)
    if not valid:
        return None, 'dst-gap'
    # 重复时刻（秋令时回拨）只取较早的一次
    first = min(valid, key=lambda a: a.astimezone(UTC))
    return first, None


def calendar_view(cal):
    return {
        'timezone': cal.timezone,
        'weekdays': {int(w) for w in cal.weekdays.split(',') if w != ''},
        'handover_time': cal.handover_time,
        'shutdown_dates': set(json.loads(cal.shutdown_dates or '[]')),
    }


def occurrences(view, start_ts, end_ts):
    """生成 [start_ts, end_ts) 内的班次与跳过记录。view 为 _calendar_view 字典。"""
    tz = ZoneInfo(view['timezone'])
    found, skipped = [], []
    day = (datetime.fromtimestamp(start_ts, tz) - timedelta(days=1)).date()
    last = (datetime.fromtimestamp(end_ts, tz) + timedelta(days=1)).date()
    while day <= last:
        iso = day.isoformat()
        if day.weekday() in view['weekdays']:
            if iso in view['shutdown_dates']:
                skipped.append({'date': iso, 'reason': 'shutdown'})
            else:
                aware, reason = resolve_local(tz, day, view['handover_time'])
                if aware is None:
                    skipped.append({'date': iso, 'reason': reason})
                else:
                    due = aware.timestamp()
                    if start_ts <= due < end_ts:
                        found.append({'due_at': due, 'local_date': iso, 'local_time': view['handover_time']})
        day += timedelta(days=1)
    return found, skipped


def version_windows(calendars, now, backfill=BACKFILL_SECONDS, horizon=HORIZON_SECONDS):
    """每个版本实际管辖的 due_at 区间 [(cal, lo, hi)]，hi 不含。只保留与给定窗口相交的部分。"""
    floor = now - backfill
    ceiling = now + horizon
    ordered = sorted(calendars, key=lambda c: (c.effective_at, c.version))
    windows = []
    for i, cal in enumerate(ordered):
        upper = ordered[i + 1].effective_at if i + 1 < len(ordered) else float('inf')
        lo, hi = max(cal.effective_at, floor), min(ceiling, upper)
        if lo < hi:
            windows.append((cal, lo, hi))
    return windows


def materialize(db, report, now=None):
    """为班历计划补齐物化班次。幂等：唯一键 (report_id, due_at) 保证一个班次只归属一个版本。"""
    now = time.time() if now is None else now
    calendars = list(db.scalars(select(ReportCalendar).where(ReportCalendar.report_id == report.id)))
    if not calendars:
        return 0
    created = 0
    for cal, lo, hi in version_windows(calendars, now):
        existing = set(db.scalars(select(Shift.due_at).where(Shift.report_id == report.id, Shift.due_at >= lo, Shift.due_at < hi)))
        view = calendar_view(cal)
        for occ in occurrences(view, lo, hi)[0]:
            if occ['due_at'] in existing:
                continue
            db.add(Shift(report_id=report.id, calendar_id=cal.id, calendar_version=cal.version,
                         timezone=cal.timezone, local_date=occ['local_date'], local_time=occ['local_time'],
                         due_at=occ['due_at'], status='pending', created_at=now))
            existing.add(occ['due_at'])
            created += 1
    db.flush()
    refresh_next_run(db, report, now)
    return created


def refresh_next_run(db, report, now=None):
    """班历计划的 next_run 仅作展示：指向下一个待发班次。"""
    now = time.time() if now is None else now
    nxt = db.scalar(select(func.min(Shift.due_at)).where(Shift.report_id == report.id, Shift.status == 'pending'))
    report.next_run = nxt if nxt is not None else now + HORIZON_SECONDS
