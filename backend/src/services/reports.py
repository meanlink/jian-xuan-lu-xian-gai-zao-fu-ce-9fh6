import time, os, csv, io, hashlib, json, re
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import select, delete, func
from src.models import Job, Report, ReportCalendar, Shift, Delivery
from src.config.settings import ARTIFACT_DIR
from src.services import schedule

BACKFILL_LATE_SECONDS = 300  # 晚于原定时刻 5 分钟以上的投递标记为补发


def _validate_calendar(data):
    if schedule.load_tz(data.timezone) is None:
        raise HTTPException(422, '收件地时区无效，请使用 IANA 时区名（如 America/New_York）')
    weekdays = sorted(set(data.weekdays))
    if not weekdays or any(w < 0 or w > 6 for w in weekdays):
        raise HTTPException(422, '星期取值须在 0（周一）至 6（周日）之间且至少选择一天')
    if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', data.handover_time or ''):
        raise HTTPException(422, '交班时刻须为 24 小时制 HH:MM')
    shutdown = []
    for raw in data.shutdown_dates:
        try:
            shutdown.append(datetime.strptime(raw, '%Y-%m-%d').date().isoformat())
        except (ValueError, TypeError):
            raise HTTPException(422, f'停工日 {raw} 无效，须为 YYYY-MM-DD')
    if len(shutdown) > 400:
        raise HTTPException(422, '停工日最多 400 条')
    now = time.time()
    effective = data.effective_at if data.effective_at is not None else now
    if not (0 < effective <= now + 370 * 86400):
        raise HTTPException(422, '生效时刻超出可支持范围')
    return weekdays, sorted(set(shutdown)), effective


def _add_calendar(db, report, data, actor):
    weekdays, shutdown, effective = _validate_calendar(data)
    version = db.scalar(select(func.max(ReportCalendar.version)).where(ReportCalendar.report_id == report.id)) or 0
    cal = ReportCalendar(report_id=report.id, version=version + 1, timezone=data.timezone,
                         weekdays=','.join(str(w) for w in weekdays), handover_time=data.handover_time,
                         shutdown_dates=json.dumps(shutdown), effective_at=effective,
                         created_at=time.time(), created_by=actor)
    db.add(cal)
    db.flush()
    return cal


def create(db, data, actor=''):
    j = db.get(Job, data.job_id)
    if not j or j.status != 'completed' or not j.approved:
        raise HTTPException(409, '请先选择已完成且获批准的分析结果')
    if data.schedule_type == 'shift':
        if data.calendar is None:
            raise HTTPException(422, '班历计划需要收件地时区、星期与交班时刻')
        r = Report(name=data.name, job_id=j.id, destination=data.destination, schedule_type='shift',
                   interval_seconds=0, next_run=time.time() + schedule.HORIZON_SECONDS, enabled=True)
        db.add(r)
        db.flush()
        _add_calendar(db, r, data.calendar, actor)
        schedule.materialize(db, r)
        return r
    r = Report(name=data.name, job_id=j.id, destination=data.destination, schedule_type='interval',
               interval_seconds=data.interval_seconds, next_run=time.time() + data.delay_seconds, enabled=True)
    db.add(r)
    db.flush()
    return r


def revise(db, report, data, actor):
    """班历改版：生效时刻起的待发班次改属新版本，之前已到期的欠发保留旧班历。"""
    if report.schedule_type != 'shift':
        raise HTTPException(409, '秒间隔计划无需改班，可直接调整周期重建')
    cal = _add_calendar(db, report, data, actor)
    # 生效时刻起尚未派发的班次由新版本重新产生；派送中与已归档的班次保持原版本归属
    db.execute(delete(Shift).where(Shift.report_id == report.id, Shift.status == 'pending',
                                   Shift.due_at >= cal.effective_at))
    schedule.materialize(db, report)
    return cal


def _render_csv(j):
    out = io.StringIO()
    out.write('\ufeff')
    table = j.result.get('table', {})
    cols = table.get('columns', [])
    writer = csv.writer(out)
    def safe(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        text = str(v)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows', []):
        writer.writerow([safe(row.get(c['key'], '')) for c in cols])
    return out.getvalue().encode('utf-8')


def _archive(db, report, j, filename, **extra):
    """写入归档行与文件。调用方需保证 filename 对本班次/本次投递确定，重试覆盖同名文件。"""
    data = _render_csv(j)
    delivery = Delivery(report_id=report.id, created_at=time.time(),
                        checksum=hashlib.sha256(data).hexdigest(), filename=filename,
                        destination=report.destination, **extra)
    db.add(delivery)
    db.flush()
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, filename), 'wb') as f:
        f.write(data)
    with open(os.path.join(ARTIFACT_DIR, filename + '.json'), 'w') as f:
        json.dump({'job': j.name, 'params': j.params, 'result': j.result, 'checksum': delivery.checksum},
                  f, ensure_ascii=False, allow_nan=False)
    return delivery


def deliver(db, report):
    j = db.get(Job, report.job_id)
    if not j or not j.approved:
        return
    delivery = _archive(db, report, j, f'report-{report.id}-delivery-pending.csv')
    final = f'report-{report.id}-delivery-{delivery.id}.csv'
    os.replace(os.path.join(ARTIFACT_DIR, delivery.filename), os.path.join(ARTIFACT_DIR, final))
    os.replace(os.path.join(ARTIFACT_DIR, delivery.filename + '.json'), os.path.join(ARTIFACT_DIR, final + '.json'))
    delivery.filename = final
    report.next_run = time.time() + report.interval_seconds
    return delivery


def deliver_shift(db, report, shift):
    """投递一个班次。幂等：同一班次重复执行复用已有归档，不重复生成文件。"""
    j = db.get(Job, report.job_id)
    if not j or not j.approved:
        return None
    existing = db.scalar(select(Delivery).where(Delivery.shift_id == shift.id))
    if existing is None:
        now = time.time()
        existing = _archive(db, report, j, f'report-{report.id}-shift-{shift.id}.csv',
                            shift_id=shift.id, planned_at=shift.due_at,
                            calendar_version=shift.calendar_version,
                            backfill=now - shift.due_at > BACKFILL_LATE_SECONDS)
    shift.status = 'delivered'
    shift.delivery_id = existing.id
    shift.delivered_at = time.time()
    schedule.refresh_next_run(db, report)
    return existing
