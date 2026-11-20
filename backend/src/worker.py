import time, json, logging
from pathlib import Path
from sqlalchemy import select, update
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, Shift
from src.services.business import analyze
from src.services.reports import deliver, deliver_shift
from src.services.schedule import materialize
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
CLAIM_STALE_SECONDS=600
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def run_shift_reports(now):
    # 物化班次（含停机期间欠下的班次），再逐个原子认领投递
    with Session() as db:
        ids=list(db.scalars(select(Report.id).where(Report.enabled==True,Report.schedule_type=='shift')))
        db.execute(update(Shift).where(Shift.status=='delivering',Shift.claimed_at<now-CLAIM_STALE_SECONDS).values(status='pending',claimed_at=None))
        db.commit()
    for rid in ids:
        try:
            with Session() as db:
                r=db.get(Report,rid)
                if r:materialize(db,r,now)
                db.commit()
        except Exception:
            logging.exception('Shift materialize failed for report %s',rid)
    with Session() as db:
        due=list(db.scalars(select(Shift.id).join(Report,Shift.report_id==Report.id).where(Report.enabled==True,Shift.status=='pending',Shift.due_at<=now).order_by(Shift.due_at).limit(25)))
    for sid in due:
        try:
            with Session() as db:
                claimed=db.execute(update(Shift).where(Shift.id==sid,Shift.status=='pending').values(status='delivering',claimed_at=now)).rowcount
                if not claimed:continue
                shift=db.get(Shift,sid)
                report=db.get(Report,shift.report_id)
                d=deliver_shift(db,report,shift)
                if d:record(db,'worker','shift.delivered',{'id':shift.report_id,'shift':sid,'delivery':d.id,'version':shift.calendar_version,'backfill':d.backfill})
                db.commit()
        except Exception:
            logging.exception('Shift delivery failed for shift %s',sid)
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    now=time.time()
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.schedule_type=='interval',Report.next_run<=now)):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
    run_shift_reports(now)
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs or shifts.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        recovered=db.execute(update(Shift).where(Shift.status=='delivering').values(status='pending',claimed_at=None)).rowcount
        if recovered:record(db,'worker','shift.recovered',{'count':recovered})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
