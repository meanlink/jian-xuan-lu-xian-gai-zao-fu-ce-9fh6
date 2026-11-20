import os, time
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Report, ReportCalendar, Shift, Delivery
from src.schemas.report import ReportInput, RevisionInput
from src.middlewares.auth import current_user, admin_only
from src.services import reports, schedule
from src.services.audit import record
from src.utils.serialization import report_dict, calendar_dict, shift_dict, delivery_dict
router=APIRouter()
def _report(db,id):
    r=db.get(Report,id)
    if not r:raise HTTPException(404,'分发计划不存在')
    return r
def _active_calendar(db,report_id):
    return db.scalar(select(ReportCalendar).where(ReportCalendar.report_id==report_id,ReportCalendar.effective_at<=time.time()).order_by(ReportCalendar.effective_at.desc(),ReportCalendar.version.desc()).limit(1))
@router.get('/reports')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [report_dict(r,_active_calendar(db,r.id) if r.schedule_type=='shift' else None) for r in db.scalars(select(Report).order_by(Report.id.desc()))]
@router.post('/reports',status_code=201)
def create(data:ReportInput,db=Depends(get_db),u=Depends(admin_only)):
    r=reports.create(db,data,u.email); record(db,u.email,'report.schedule',{'id':r.id,'destination':r.destination,'type':r.schedule_type}); db.commit()
    return report_dict(r,_active_calendar(db,r.id) if r.schedule_type=='shift' else None)
@router.post('/reports/{id}/toggle')
def toggle(id:int,db=Depends(get_db),u=Depends(admin_only)):
    r=_report(db,id)
    r.enabled=not r.enabled;record(db,u.email,'report.toggle',{'id':id,'enabled':r.enabled});db.commit()
    return report_dict(r,_active_calendar(db,id) if r.schedule_type=='shift' else None)
@router.get('/reports/{id}/calendars')
def calendars(id:int,db=Depends(get_db),u=Depends(current_user)):
    _report(db,id)
    return [calendar_dict(c) for c in db.scalars(select(ReportCalendar).where(ReportCalendar.report_id==id).order_by(ReportCalendar.version.desc()))]
@router.post('/reports/{id}/calendar',status_code=201)
def revise(id:int,data:RevisionInput,db=Depends(get_db),u=Depends(admin_only)):
    r=_report(db,id)
    cal=reports.revise(db,r,data,u.email); record(db,u.email,'report.calendar.revise',{'id':id,'version':cal.version,'effective_at':cal.effective_at}); db.commit()
    return calendar_dict(cal)
@router.get('/reports/{id}/shifts')
def shifts(id:int,limit:int=100,db=Depends(get_db),u=Depends(current_user)):
    _report(db,id)
    return [shift_dict(s) for s in db.scalars(select(Shift).where(Shift.report_id==id).order_by(Shift.due_at.desc()).limit(min(limit,200)))]
@router.get('/reports/{id}/preview')
def preview(id:int,days:int=14,db=Depends(get_db),u=Depends(current_user)):
    r=_report(db,id)
    if r.schedule_type!='shift':raise HTTPException(409,'秒间隔计划按周期执行，无需预览班次')
    days=max(1,min(days,62)); now=time.time()
    cals=list(db.scalars(select(ReportCalendar).where(ReportCalendar.report_id==id)))
    entries,skipped=[],[]
    for cal,lo,hi in schedule.version_windows(cals,now,backfill=0,horizon=days*86400):
        lo=max(lo,now)
        if lo>=hi:continue
        occ,skip=schedule.occurrences(schedule.calendar_view(cal),lo,hi)
        entries+=[dict(o,version=cal.version,timezone=cal.timezone) for o in occ]
        skipped+=[dict(s,version=cal.version) for s in skip]
    entries.sort(key=lambda e:e['due_at'])
    return {'timezone_note':'时刻为收件地当地时间','occurrences':entries[:200],'skipped':skipped[:200]}
@router.get('/deliveries')
def deliveries(db=Depends(get_db),u=Depends(current_user)):
    return [delivery_dict(d) for d in db.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(100))]
@router.get('/deliveries/{id}/download')
def download(id:int,format:str='csv',db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Delivery,id)
    if not d:raise HTTPException(404,'归档不存在')
    if format not in ('csv','json'):raise HTTPException(422,'支持 CSV 或 JSON')
    filename=d.filename+('.json' if format=='json' else '')
    p=os.path.join(ARTIFACT_DIR,filename)
    if not os.path.exists(p):raise HTTPException(404,'归档文件不存在，请重新安排分发')
    return FileResponse(p,filename=filename,media_type='application/json' if format=='json' else 'text/csv; charset=utf-8')
