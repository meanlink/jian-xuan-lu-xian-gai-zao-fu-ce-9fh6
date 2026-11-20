/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,report_id:number,version:number,timezone:string,weekdays:number[],handover_time:string,shutdown_dates:string[],effective_at:number}} ReportCalendar */
/** @typedef {{id:number,name:string,job_id:number,destination:string,schedule_type:'interval'|'shift',interval_seconds:number,next_run:number,enabled:boolean,calendar:?ReportCalendar}} ReportSchedule */
/** @typedef {{id:number,report_id:number,calendar_version:number,timezone:string,local_date:string,local_time:string,due_at:number,status:'pending'|'delivering'|'delivered',delivery_id:?number}} Shift */
/** @typedef {{id:number,report_id:number,created_at:number,checksum:string,filename:string,destination:string,shift_id:?number,planned_at:?number,calendar_version:?number,backfill:boolean}} Delivery */
export {};
