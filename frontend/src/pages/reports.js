import {jobs,reports} from '../api/entities.js';
import {download} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
const ZONES=['Asia/Shanghai','Asia/Singapore','Asia/Tokyo','Asia/Dubai','Europe/London','Europe/Berlin','Europe/Moscow','America/New_York','America/Chicago','America/Denver','America/Los_Angeles','America/Sao_Paulo','Australia/Sydney','Pacific/Auckland','UTC'];
const WEEKDAYS=['一','二','三','四','五','六','日'];
const STATUS={pending:'待发',delivering:'派送中',delivered:'已归档'};
let selected=null; // 当前核对/改班的班历计划 id
const isAdmin=()=>session.user.role==='admin';
function zoneOptions(current){return ZONES.map(z=>'<option value="'+z+'"'+(z===current?' selected':'')+'>'+z+'</option>').join('');}
function weekdayBoxes(checked){checked=checked||[0,1,2,3,4];return WEEKDAYS.map((w,i)=>'<label class="weekday"><input type="checkbox" name="weekdays" value="'+i+'"'+(checked.includes(i)?' checked':'')+'>周'+w+'</label>').join('');}
function calendarFields(cal){
 cal=cal||{timezone:'America/New_York',weekdays:[0,1,2,3,4],handover_time:'07:30',shutdown_dates:[]};
 return '<div class="calendar-fields"><label>收件地时区<select name="timezone">'+zoneOptions(cal.timezone)+'</select></label>'
 +'<fieldset class="weekday-row"><legend>交班星期</legend>'+weekdayBoxes(cal.weekdays)+'</fieldset>'
 +'<div class="parameter-grid"><label>交班时刻（当地）<input name="handover_time" type="time" value="'+esc(cal.handover_time)+'" required></label>'
 +'<label>生效时刻（留空立即生效）<input name="effective_at" type="datetime-local" step="60"></label></div>'
 +'<label>停工日（YYYY-MM-DD，逗号或换行分隔，当日跳过）<textarea name="shutdown_dates" rows="2" placeholder="2026-12-25, 2027-01-01">'+esc((cal.shutdown_dates||[]).join(', '))+'</textarea></label></div>';
}
function parseCalendar(f){
 const eff=f.get('effective_at');
 return {timezone:f.get('timezone'),weekdays:f.getAll('weekdays').map(Number),handover_time:f.get('handover_time'),
 shutdown_dates:(f.get('shutdown_dates')||'').split(/[\s,，、]+/).map(s=>s.trim()).filter(Boolean),
 effective_at:eff?Math.round(new Date(eff).getTime()/1000):null};
}
function calendarSummary(r){
 const c=r.calendar;if(!c)return '';
 return 'v'+c.version+' · '+esc(c.timezone)+' · 周'+c.weekdays.map(w=>WEEKDAYS[w]).join('、')+' '+esc(c.handover_time);
}
function planRow(r){
 const shift=r.schedule_type==='shift';
 return '<article><div><strong>'+esc(r.name)+' <span class="badge">'+(shift?'班历':'秒间隔')+'</span></strong><p>'+esc(r.destination)+'</p><small>'
 +(shift?calendarSummary(r)+' · 下次班次 ':'周期 '+r.interval_seconds+' 秒 · 下次 ')+date(r.next_run)+'</small></div>'
 +'<div class="row-actions">'+(shift?'<button class="button small" data-inspect="'+r.id+'">班次与改班</button>':'')
 +'<button class="button small" data-toggle="'+r.id+'"'+(isAdmin()?'':' disabled')+'>'+(r.enabled?'暂停':'启用')+'</button></div></article>';
}
function previewTable(preview){
 const rows=preview.occurrences.map(o=>'<tr><td>'+o.local_date+'</td><td>'+o.local_time+'</td><td>'+date(o.due_at)+'</td><td>v'+o.version+'</td></tr>').join('');
 const skipped=preview.skipped.map(s=>'<span class="badge warn">'+s.date+' '+(s.reason==='shutdown'?'停工':'夏令时缺失')+'跳过</span>').join(' ');
 return '<table><thead><tr><th>当地日期</th><th>交班时刻</th><th>UTC 时刻</th><th>班历版本</th></tr></thead><tbody>'+rows+'</tbody></table>'
 +(skipped?'<p class="hint">已跳过：'+skipped+'</p>':'')+(!rows?'<p class="empty">窗口内无班次，请调整星期或生效时刻。</p>':'');
}
function shiftTable(shifts){
 const rows=shifts.map(s=>'<tr><td>'+s.local_date+' '+s.local_time+'</td><td>'+esc(s.timezone)+'</td><td>'+date(s.due_at)+'</td><td>v'+s.calendar_version+'</td>'
 +'<td><span class="status'+(s.status==='delivered'?'':' failed')+'">'+STATUS[s.status]+'</span></td><td>'+(s.delivery_id?'归档 #'+s.delivery_id+(s.delivered_at&&s.delivered_at-s.due_at>300?' <span class="badge warn">补发</span>':''):'—')+'</td></tr>').join('');
 return '<table><thead><tr><th>原定当地时刻</th><th>时区</th><th>UTC 时刻</th><th>版本</th><th>状态</th><th>去向</th></tr></thead><tbody>'+rows+'</tbody></table>';
}
async function detailPanel(id){
 const [preview,shifts,cals]=await Promise.all([reports.preview(id,14),reports.shifts(id),reports.calendars(id)]);
 const latest=cals[0];
 return '<section class="panel" id="detail-panel"><div class="section-title"><h2>班次核对与改班</h2><span>'+cals.length+' 个班历版本</span></div>'
 +'<h3>未来 14 天班次预览</h3><div class="table-wrap">'+previewTable(preview)+'</div>'
 +'<h3>已排班次核对</h3><div class="table-wrap">'+shiftTable(shifts)+'</div>'
 +(isAdmin()?'<h3>改班（新班历版本）</h3><form id="revise-form">'+calendarFields(latest)+'<button type="submit" class="primary">按生效时刻启用新版班历</button></form>'
 +'<p class="hint">生效时刻前已到期的欠发仍按旧班历补齐；生效时刻起按新版产生班次。派送中的班次不受改版影响。</p>':'')
 +'<h3>版本沿革</h3><ul class="timeline">'+cals.map(c=>'<li><strong>v'+c.version+' · '+esc(c.timezone)+' '+esc(c.handover_time)+'</strong><span>生效 '+date(c.effective_at)+' · '+esc(c.created_by)+'</span></li>').join('')+'</ul></section>';
}
export async function reportPage(){
 const [list,deliveries,allJobs]=await Promise.all([reports.list(),reports.deliveries(),jobs.list()]);workspace.reports=list;
 const approved=allJobs.filter(j=>j.approved&&j.status==='completed');
 const detail=selected&&list.some(r=>r.id===selected&&r.schedule_type==='shift')?await detailPanel(selected):'';
 return heading('05 / DISTRIBUTION','定时分发与归档','把批准后的结果交付到本地业务收件箱。班历计划按收件地时区、星期与交班时刻产生班次，停工日与夏令时缺失时刻自动跳过。','<button class="button" id="refresh-reports">刷新收件箱 ↻</button>')
 +'<div class="report-grid"><section class="panel"><div class="section-title"><h2>创建分发计划</h2></div><form id="report-form"><label>简报名称<input name="name" required minlength="2" value="海外班组交班简报"></label><label>已批准分析<select name="job_id" required>'+approved.map(j=>'<option value="'+j.id+'">'+esc(j.name)+'</option>').join('')+'</select></label><label>业务接收组<input name="destination" value="海外班组 · 本地收件箱" required></label>'
 +'<label>排班方式<select name="schedule_type" id="schedule-type"><option value="shift">班历交班时刻（按时区/星期）</option><option value="interval">秒间隔周期（原有方式）</option></select></label>'
 +'<div id="interval-fields" hidden><div class="parameter-grid"><label>分发周期<select name="interval_seconds"><option value="86400">每日</option><option value="604800">每周</option><option value="60">每分钟（验收）</option></select></label><label>首次执行<select name="delay_seconds"><option value="0">立即</option><option value="60">1 分钟后</option><option value="3600">1 小时后</option></select></label></div></div>'
 +'<div id="shift-fields">'+calendarFields(null)+'</div>'
 +'<button type="submit" class="primary" '+(isAdmin()&&approved.length?'':'disabled')+'>保存分发计划</button></form><p class="hint">由后台 worker 按到期时间生成文件。仅负责人可创建、改班或暂停；接收组为本地标签。</p></section>'
 +'<section><div class="section-title"><h2>运行中的计划</h2><span>'+list.filter(r=>r.enabled).length+' 条已启用</span></div><div class="schedule-list">'+list.map(planRow).join('')+'</div>'
 +'<section class="panel inbox"><div class="section-title"><h2>本地收件箱</h2><span>'+deliveries.length+' 份归档</span></div>'
 +deliveries.map(d=>'<div class="delivery"><div><strong>'+esc(d.filename)+(d.backfill?' <span class="badge warn">补发</span>':'')+'</strong><p>'+esc(d.destination)+' · 归档 '+date(d.created_at)+'</p><small>'
 +(d.planned_at?'原定 '+date(d.planned_at)+' · 班历 v'+d.calendar_version+' · ':'')+'SHA256 '+esc(d.checksum.slice(0,24))+'…</small></div><div><button class="text-button" data-download="'+d.id+'" data-format="csv">CSV ↓</button><button class="text-button" data-download="'+d.id+'" data-format="json">JSON ↓</button></div></div>').join('')
 +(!deliveries.length?'<p class="empty">计划执行后，文件会出现在此处。等待片刻后刷新。</p>':'')+'</section></section></div>'+detail;
}
export function bindReports(refresh){
 const typeSelect=document.querySelector('#schedule-type');
 const toggleFields=()=>{const shift=typeSelect.value==='shift';document.querySelector('#shift-fields').hidden=!shift;document.querySelector('#interval-fields').hidden=shift;};
 if(typeSelect){typeSelect.onchange=toggleFields;toggleFields();}
 document.querySelector('#refresh-reports').onclick=refresh;
 submit(document.querySelector('#report-form'),async f=>{
  const shift=f.get('schedule_type')==='shift';
  await reports.create({name:f.get('name'),job_id:Number(f.get('job_id')),destination:f.get('destination'),schedule_type:f.get('schedule_type'),
   interval_seconds:Number(f.get('interval_seconds')||86400),delay_seconds:Number(f.get('delay_seconds')||0),...(shift?{calendar:parseCalendar(f)}:{})});
  notify('计划已保存，后台将按班历产生班次');await refresh();});
 document.querySelectorAll('[data-toggle]').forEach(b=>b.onclick=async()=>{try{await reports.toggle(b.dataset.toggle);await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-inspect]').forEach(b=>b.onclick=async()=>{selected=Number(b.dataset.inspect);await refresh();document.querySelector('#detail-panel')?.scrollIntoView({behavior:'smooth'});});
 const reviseForm=document.querySelector('#revise-form');
 if(reviseForm)submit(reviseForm,async f=>{await reports.revise(selected,parseCalendar(f));notify('新版班历已按生效时刻启用');await refresh();});
 document.querySelectorAll('[data-download]').forEach(b=>b.onclick=()=>download(b.dataset.download,b.dataset.format).catch(e=>notify(e.message,true)));
}
