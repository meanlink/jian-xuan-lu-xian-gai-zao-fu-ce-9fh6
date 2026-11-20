import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def calendar_dict(c):
    return {'id':c.id,'report_id':c.report_id,'version':c.version,'timezone':c.timezone,
            'weekdays':[int(w) for w in c.weekdays.split(',') if w!=''],'handover_time':c.handover_time,
            'shutdown_dates':json.loads(c.shutdown_dates or '[]'),'effective_at':c.effective_at,
            'created_at':c.created_at,'created_by':c.created_by}
def report_dict(r, calendar=None):
    d={k:getattr(r,k) for k in ['id','name','job_id','destination','schedule_type','interval_seconds','next_run','enabled']}
    d['calendar']=calendar_dict(calendar) if calendar else None
    return d
def shift_dict(s):
    return {k:getattr(s,k) for k in ['id','report_id','calendar_version','timezone','local_date','local_time','due_at','status','delivery_id','claimed_at','delivered_at','created_at']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination','shift_id','planned_at','calendar_version','backfill']}
