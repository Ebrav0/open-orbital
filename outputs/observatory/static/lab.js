// AGENT MAP: Compute page. Sliders -> draft config -> POST /api/jobs. Polls the summary API only.
// Never imports three, never fetches frames.bin, never allocates particle arrays. Tab budget: 300 MB.
import {slidersFor,defaultsFor,toConfig,fromConfig,estimateSeconds,maxDuration,durationCap,engineRamGb,fmt,fmtHours,fmtSeconds,fmtNum,percent,api,phaseLabel,WALL_CAP_HOURS,MYR_PER_TIME} from './shared.js';
const $=id=>document.getElementById(id);
const DRAFT_KEY='orbital-lab-draft-v2',ACTIVE=['running','initializing','pausing'];
let queue={enabled:false,ids:[]},system={};
let mode='galaxy',values={galaxy:defaultsFor('galaxy'),planets:defaultsFor('planets')},jobs=[],selectedId=null,pollTimer=null,saveTimer=null,toastTimer=null,etaTimer=null,polling=false,eventLines=20,rows={},logOpen=false,pauseEta=null;
let historyJob=null,historyFrames=-1,historyPoints=[];
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),6500)}
function loadDraft(){try{const d=JSON.parse(localStorage.getItem(DRAFT_KEY)||'null');if(!d)return;if(d.mode==='galaxy'||d.mode==='planets')mode=d.mode;for(const m of['galaxy','planets']){if(d[m]&&typeof d[m]==='object'){const base=defaultsFor(m);for(const s of slidersFor(m))if(d[m][s.id]!=null)base[s.id]=d[m][s.id];values[m]=base}}}catch(e){localStorage.removeItem(DRAFT_KEY)}}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>{const text=JSON.stringify({mode,galaxy:values.galaxy,planets:values.planets});if(text.length<8192)localStorage.setItem(DRAFT_KEY,text)},200)}
function readout(s,v){if(s.kind==='bool')return v?'on':'off';return s.kind==='choice'||s.kind==='number'||Number.isInteger(s.step)?fmt(v):Number(v).toLocaleString('en-US',{maximumFractionDigits:4})}
function unitLine(s,v){if(s.kind==='bool')return '';if(s.physical){const p=s.physical(Number(v));if(p)return p}return s.unit||''}
function tickLabel(s,st){if(s.id==='n'&&st>=1000)return st>=1e6?`${st/1e6}M`:`${st/1000}k`;return fmt(st)}
function renderSliders(){const list=slidersFor(mode);rows={};$('sliders').replaceChildren();$('slider-count').textContent=`${list.length} controls`;const groups=[...new Set(list.map(s=>s.group))];
for(const g of groups){const box=document.createElement('div');box.className='slider-group';const h=document.createElement('h3');h.textContent=g;box.append(h);
for(const s of list.filter(x=>x.group===g)){const row=document.createElement('div');row.className=`slider-row kind-${s.kind||'range'}`;const label=document.createElement('label');label.htmlFor=`k-${s.id}`;label.textContent=s.label;let hint=null;if(s.hint){hint=document.createElement('small');hint.className='slider-hint';hint.textContent=s.hint;row.append(hint)}
const out=document.createElement('output');out.className='readout';out.htmlFor=`k-${s.id}`;let input;const v=values[mode][s.id];
if(s.kind==='bool'){input=document.createElement('input');input.type='checkbox';input.checked=Boolean(v)}
else if(s.kind==='number'){input=document.createElement('input');input.type='number';input.min=s.min;input.max=s.max;input.step=s.step;input.value=v}
else if(s.kind==='choice'){input=document.createElement('input');input.type='range';input.min=0;input.max=s.stops.length-1;input.step=1;input.value=Math.max(0,s.stops.indexOf(Number(v)));const ticks=document.createElement('div');ticks.className='ticks';s.stops.forEach((st,i)=>{const t=document.createElement('span');t.textContent=(s.labels&&s.labels[i])||tickLabel(s,st);ticks.append(t)});row.append(ticks)}
else{input=document.createElement('input');input.type='range';input.min=s.min;input.max=s.max;input.step=s.step;input.value=v}
input.id=`k-${s.id}`;input.setAttribute('aria-label',s.label);if(s.hint)input.title=s.hint;const unit=document.createElement('span');unit.className='unit';
input.addEventListener('input',()=>{let val;if(s.kind==='bool')val=input.checked;else if(s.kind==='choice')val=s.stops[Number(input.value)];else if(s.kind==='number'){val=Math.min(s.max,Math.max(s.min,Math.round(Number(input.value)||0)))}else val=Number(input.value);values[mode][s.id]=val;out.textContent=readout(s,val);unit.textContent=unitLine(s,val);updateEstimate();scheduleSave()});
out.textContent=readout(s,v);unit.textContent=unitLine(s,v);row.prepend(label);row.append(input,out,unit);rows[s.id]={input,out,unit,slider:s,row,hint};box.append(row)}
$('sliders').append(box)}updateEstimate()}
function markUnused(){if(mode!=='galaxy')return;const G=Number(values.galaxy.n_galaxies||1);
for(const id in rows){const {out,slider:s,row}=rows[id];if(!s.galaxy||!row)continue;const unused=G<s.galaxy;row.classList.toggle('unused',unused);out.textContent=unused?`not used unless galaxy count ≥ ${s.galaxy}`:readout(s,values.galaxy[s.id])}}
function syncInputs(){for(const id in rows){const {input,out,unit,slider:s}=rows[id],v=values[mode][id];if(s.kind==='bool')input.checked=Boolean(v);else if(s.kind==='choice')input.value=Math.max(0,s.stops.indexOf(Number(v)));else input.value=v;out.textContent=readout(s,v);if(unit)unit.textContent=unitLine(s,v)}updateEstimate()}
function applyDurationCap(cfg){if(!rows.duration)return;const cap=durationCap(cfg);const s=rows.duration.slider;if(s.kind==='choice')return;rows.duration.input.max=cap;if(Number(values[mode].duration)>cap){values[mode].duration=cap;rows.duration.input.value=cap;rows.duration.out.textContent=readout(s,cap);if(rows.duration.unit)rows.duration.unit.textContent=unitLine(s,cap);scheduleSave()}if(mode==='galaxy'&&rows.duration.hint)rows.duration.hint.textContent=`Live max ${fmt(cap)} model units (${Math.round(cap*MYR_PER_TIME).toLocaleString('en-US')} Myr) from the 120 h wall-time estimate.`}
function renderHero(cfg){const draft=estimateSeconds(cfg);const j=target();const s=j?.status;const remaining=j?Math.max(0,(j.meta?.total_frames||0)-(s.frames||0)):0;
if(j&&ACTIVE.includes(s.phase)&&s.last_frame_compute_seconds!=null){$('estimate-time').textContent=`${fmtSeconds(s.last_frame_compute_seconds*remaining)} remaining`;$('estimate-kind').textContent='from last chunk'}
else if(j&&s.phase==='complete'){$('estimate-time').textContent='done';$('estimate-kind').textContent=`this experiment is complete · estimate before start for a new run: ${fmtHours(draft/3600)}`}
else{$('estimate-time').textContent=`${fmtHours(draft/3600)} estimated wall`;$('estimate-kind').textContent='estimate before start'}}
function updateEstimate(){const cfg=toConfig(mode,values[mode]);applyDurationCap(cfg);const hours=estimateSeconds(cfg)/3600,cap=hours<=WALL_CAP_HOURS;const span=mode==='galaxy'?`${Math.round(cfg.duration*MYR_PER_TIME).toLocaleString('en-US')} Myr`:`${cfg.duration} yr`;const size=mode==='galaxy'?`${fmt(cfg.n)} particles · ${cfg.threads} threads`:`${cfg.perturber_mass>0?10:9} bodies`;const steps=mode==='galaxy'?Math.round(cfg.duration/cfg.dt):null;const maxSpan=mode==='galaxy'?Math.floor(maxDuration(cfg)):maxDuration(cfg);
renderHero(cfg);
const ng=mode==='galaxy'?Number(cfg.n_galaxies||1):1;
const galaxies=mode==='galaxy'?(ng>1?`${fmt(cfg.n)} particles in ${ng} galaxies · ${cfg.threads} threads`:`${fmt(cfg.n)} particles · ${cfg.threads} threads`):size;
const passage=mode==='galaxy'&&ng>1&&cfg.g2_vrel?` · first passage ~${Math.round(cfg.g2_sep/cfg.g2_vrel*MYR_PER_TIME)} Myr`:'';
$('estimate-detail').textContent=cap?`${span} · ${galaxies}${steps!=null?` · ${fmt(steps)} leapfrog steps`:''}${passage} · fits the ${WALL_CAP_HOURS} h cap (max span ${mode==='galaxy'?`${fmt(maxSpan)} model units / ${Math.round(maxSpan*MYR_PER_TIME).toLocaleString('en-US')} Myr`:`${maxSpan.toFixed(1)} yr`}) · engine ~${engineRamGb(cfg).toFixed(2)} GB RAM (separate from this dashboard). θ and softening are not in this timing model.`:`${span} · ${galaxies} · exceeds the ${WALL_CAP_HOURS} h cap — lower N, raise threads, coarsen dt, or shorten the span (max ≈ ${mode==='galaxy'?`${fmt(Math.floor(maxSpan))} model units`:`${maxSpan.toFixed(1)} yr`}).`;
$('estimate').classList.toggle('over',!cap);markUnused();
const busy=$('start-compute').dataset.busy==='1';
const blocked=queue.enabled||jobs.some(j=>ACTIVE.includes(j.status.phase));
const capRuns=system.max_runs||24;
const slotsFull=jobs.length>=capRuns;
$('add-queue').disabled=!cap||slotsFull||$('add-queue').dataset.busy==='1';
$('start-compute').disabled=!cap||busy||blocked||slotsFull;
$('start-compute').textContent=slotsFull?`Remove a run first (${jobs.length}/${capRuns} saved)`:busy?'Starting…':'Start computation';
$('start-compute').title=busy?'Starting…':slotsFull?`${capRuns} experiments are saved. Remove one from the list below before starting another.`:blocked?'Pause or finish the running experiment before starting another.':cap?'Start a new experiment from the sliders on the left.':'This draft exceeds the 120-hour compute cap.';}
function remainingPauseSeconds(){if(!pauseEta)return null;if(pauseEta.unbounded)return null;return Math.max(0,pauseEta.seconds-(Date.now()/1000-pauseEta.at))}
function armPauseEta(status){if(!status){pauseEta=null;return}if(status.phase==='pausing'){pauseEta={seconds:0,at:Date.now()/1000,unbounded:false};return}
if(['paused','interrupted','complete','error'].includes(status.phase)||!status.pause_pending){if(!status.pause_pending)pauseEta=null;return}
if(!pauseEta)pauseEta={seconds:status.pause_eta_seconds==null?0:Number(status.pause_eta_seconds),at:Date.now()/1000,unbounded:status.pause_eta_seconds==null}}
function pauseEtaCopy(){const j=target();if(!j)return '';const s=j.status;
if(s.phase==='pausing')return 'Integrator reached a pause point. Writing a checkpoint now — this can take tens of seconds at 1,000,000 particles.';
if(s.pause_pending&&s.phase==='initializing')return 'Pause queued. It applies after initial conditions are built, then a checkpoint is written.';
if(s.pause_pending||(pauseEta&&!['paused','interrupted','complete','error'].includes(s.phase))){
  const left=remainingPauseSeconds();
  if(left==null)return 'Stop requested. Waiting for the current leapfrog step (checked about four times a second), then a checkpoint.';
  if(left<1)return 'Stop requested. Checkpoint should begin any moment.';
  return `Stop requested. Up to ${fmtSeconds(left)} for the current leapfrog step to finish, then a checkpoint.`;
}
return ''}
function renderPauseEta(){const text=pauseEtaCopy();const el=$('pause-eta');if(!el)return;if(!text){el.classList.add('hidden');el.textContent='';return}el.classList.remove('hidden');el.textContent=text}
function target(){const active=jobs.find(j=>ACTIVE.includes(j.status.phase)||j.status.pause_pending);if(selectedId){const j=jobs.find(j=>j.id===selectedId);if(j)return j;selectedId=null}return active||jobs.find(j=>j.config.mode===mode)||null}
function dd(parent,label,value,title){const div=document.createElement('div'),dt=document.createElement('dt'),d=document.createElement('dd');dt.textContent=label;d.textContent=value;if(title)d.title=title;div.append(dt,d);parent.append(div)}
function renderStopButton(j){const btn=$('stop-compute');if(!j){btn.disabled=true;btn.textContent='Stop computation';return}
const s=j.status,pending=!!s.pause_pending&&!['paused','interrupted'].includes(s.phase);
if(s.phase==='pausing'){btn.disabled=true;btn.textContent='Writing checkpoint…';return}
if(pending){btn.disabled=false;btn.textContent='Cancel pause';return}
if(['paused','interrupted'].includes(s.phase)){btn.disabled=false;btn.textContent='Resume computation';return}
if(['complete','error'].includes(s.phase)){btn.disabled=true;btn.textContent='Stop computation';return}
btn.disabled=s.phase==='queued';btn.textContent='Stop computation'}
function sparkPath(values,w=320,h=64,pad=6){const nums=values.filter(v=>v!=null&&isFinite(v));if(nums.length<2)return '';const lo=Math.min(...nums),hi=Math.max(...nums),span=hi-lo||1;
return nums.map((v,i)=>{const x=pad+i*(w-2*pad)/Math.max(nums.length-1,1);const y=h-pad-((v-lo)/span)*(h-2*pad);return `${i?'L':'M'}${x.toFixed(1)} ${y.toFixed(1)}`}).join(' ')}
function drawSpark(id,values,color){const svg=$(id);if(!svg)return;svg.replaceChildren();const d=sparkPath(values);if(!d){const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x','12');t.setAttribute('y','36');t.setAttribute('fill','#6d7c8a');t.setAttribute('font-size','11');t.textContent='No history yet';svg.append(t);return}
const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);path.setAttribute('fill','none');path.setAttribute('stroke',color);path.setAttribute('stroke-width','1.6');path.setAttribute('stroke-linejoin','round');path.setAttribute('stroke-linecap','round');svg.append(path)}
function drawCharts(points){drawSpark('chart-radius',points.map(p=>p.disk_half_radius),'#9fc6b1');drawSpark('chart-sfr',points.map(p=>p.sfr!=null?p.sfr:p.births),'#e0b07a');drawSpark('chart-energy',points.map(p=>p.energy_change),'#8bb4d9')}
async function refreshHistory(){const j=target();if(!j){historyJob=null;historyFrames=-1;historyPoints=[];drawCharts([]);return}if(j.id===historyJob&&(j.status.frames||0)===historyFrames)return;historyJob=j.id;historyFrames=j.status.frames||0;try{historyPoints=(await api(`/api/jobs/${j.id}/history`)).points||[]}catch(e){historyPoints=[]}drawCharts(historyPoints)}
function renderHealth(){const j=target();const s=j?.status||{};const daemon=system.daemon===true;$('health-daemon').textContent=daemon?'up (LaunchAgent)':'foreground / unknown';
const sleep=system.sleep_prevention==='idle'||system.sleep_prevention==='on'?'on while integrating':'off';
$('health-sleep').textContent=sleep;$('health-lid').textContent=system.lid_close_sleeps===false?'may stay awake':'still sleeps the Mac';
const capAt=s.wall_cap_at||WALL_CAP_HOURS*3600;const left=Math.max(0,capAt-(s.wall_seconds||0));
$('health-cap').textContent=j?fmtSeconds(left):`${WALL_CAP_HOURS} h`;
$('health-checkpoint').textContent=s.checkpoint_age_seconds==null?'—':s.checkpoint_age_seconds<90?`${Math.round(s.checkpoint_age_seconds)} s ago`:fmtSeconds(s.checkpoint_age_seconds)+' ago';
$('health-pid').textContent=system.worker_pid||'none'}
function renderStatus(){const j=target();renderHealth();if(!j){$('status-heading').textContent='Nothing selected';$('status-sub').textContent='Start a computation or pick a saved experiment.';$('phase').textContent='Idle';$('phase').dataset.phase='idle';$('progress-bar').style.width='0%';renderStopButton(null);pauseEta=null;renderPauseEta();$('diagnostics').replaceChildren();updateEstimate();return}
const s=j.status,m=j.meta||{},c=j.config,d=s.diagnostics||{},lc=d.lifecycle;const total=m.total_frames||0,frames=s.frames||0,remaining=Math.max(0,total-frames);
armPauseEta(s);
$('status-heading').textContent=m.title||(c.mode==='galaxy'?'Building galaxy initial conditions':'Building planetary system');$('status-sub').textContent=`${c.mode==='galaxy'?`${(c.n_galaxies||m.n_galaxies||1)>1?`${c.n_galaxies||m.n_galaxies} galaxies · `:''}${fmt(c.n)} particles · ${c.threads} threads`:`${m.n||c.n} bodies`} · span ${c.mode==='galaxy'?`${Math.round(c.duration*MYR_PER_TIME)} Myr`:`${c.duration} yr`}${c.notes?` · ${c.notes}`:''}`;
$('phase').textContent=phaseLabel(s);$('phase').dataset.phase=s.pause_pending&&s.phase==='running'?'pausing':s.phase;$('progress-bar').style.width=`${(s.progress||0)*100}%`;$('progress-label').textContent=`${Math.round((s.progress||0)*100)}%`;$('frame-label').textContent=total?`frame ${fmt(frames)} / ${fmt(total)}`:`${fmt(frames)} frames`;
$('wall-time').textContent=fmtSeconds(s.wall_seconds);$('computed-time').textContent=s.computed_time==null?'—':`${(s.computed_time*(m.time_scale||1)).toFixed(c.mode==='galaxy'?1:2)} ${m.time_unit||''}`;$('last-chunk').textContent=fmtSeconds(s.last_frame_compute_seconds);
$('eta').textContent=ACTIVE.includes(s.phase)&&s.last_frame_compute_seconds!=null?fmtSeconds(s.last_frame_compute_seconds*remaining):s.phase==='complete'?'done':'—';$('threads-val').textContent=c.threads??'—';$('particles-val').textContent=fmt(m.n||c.n||0);$('revision-val').textContent=m.model_revision??'—';$('job-id').textContent=j.id;$('steps-val').textContent=s.steps!=null?fmt(s.steps):'—';$('engine-ram').textContent=`~${engineRamGb(c).toFixed(2)} GB · separate from this dashboard`;
renderStopButton(j);renderPauseEta();updateEstimate();
const dl=$('diagnostics');dl.replaceChildren();
if(d.energy!=null){dd(dl,m.lifecycle_enabled?'Energy change (lifecycle on: mass return and kicks change E on purpose; not an error bound)':d.energy_sampled?'Sampled energy change (Monte Carlo, not an error bound)':'Energy change',percent(d.energy_change)+(d.energy_sampled&&d.energy_change_uncertainty!=null?` ± ${percent(d.energy_change_uncertainty)}`:''));dd(dl,'Angular momentum change',percent(d.angular_change));if(c.mode==='galaxy'){dd(dl,'Disk half-radius',`${fmtNum(d.disk_half_radius*3)} kpc (${d.disk_radius_change==null?'—':(d.disk_radius_change*100).toFixed(1)+'%'})`);if(d.halo_half_radius!=null)dd(dl,'Halo half-radius',`${fmtNum(d.halo_half_radius*3)} kpc`)}}
const enc=d.encounter;
if(enc){if(enc.separation_12!=null)dd(dl,'Galaxy 1–2 separation',`${fmtNum(enc.separation_12*3)} kpc · vrel ${fmtNum(enc.vrel_12*119.7)} km/s`);if(enc.min_separation!=null)dd(dl,'Closest approach so far',`${fmtNum(enc.min_separation*3)} kpc`);(enc.galaxies||[]).forEach(g=>{const com=(g.com||[]).map(x=>fmtNum(x*3));dd(dl,`Galaxy ${g.id} COM`,`${com.join(', ')} kpc · disk ${g.disk_half_radius_kpc==null?'—':fmtNum(g.disk_half_radius_kpc)+' kpc'}`)});if((c.n_galaxies||m.n_galaxies||1)>1)dd(dl,'Birth-galaxy colors','Galaxy COMs are birth-tagged; streams keep their original color.')}
if(lc){const cnt=lc.counts||{};dd(dl,'Gas / stellar / remnant mass',`${fmtNum(lc.gas_mass)} / ${fmtNum(lc.stellar_mass)} / ${fmtNum(lc.remnant_mass)} ×10¹⁰ M☉`);dd(dl,'Star-formation rate',`${fmtNum(lc.sfr*1e4)} ×10⁶ M☉ / Myr`);dd(dl,'Mean stellar age',`${fmt(Math.round(lc.mean_stellar_age||0))} Myr`);dd(dl,'Births / deaths / supernovae',`${fmt(lc.births_cumulative||0)} / ${fmt(lc.deaths_cumulative||0)} / ${fmt(lc.supernovae_cumulative||0)}`);dd(dl,'Population',`gas ${fmt(cnt.gas||0)} · proto ${fmt(cnt.protostar||0)} · MS ${fmt(cnt.main_sequence||0)} · giant ${fmt(cnt.giant||0)} · WD ${fmt(cnt.white_dwarf||0)} · NS ${fmt(cnt.neutron_star||0)} · BH ${fmt(cnt.black_hole||0)}${cnt.smbh?' · SMBH 1':''}`);if(lc.mass_return_failed>0)dd(dl,'Mass return kept on remnants (no gas nearby)',`${fmtNum(lc.mass_return_failed)} ×10¹⁰ M☉`)}
if(!dl.children.length)dd(dl,'Diagnostics','Waiting for the first computed state.');
const log=$('event-log');log.replaceChildren();const lines=[...(s.events||[])].slice(-eventLines);if(s.error)lines.push(`Error: ${s.error}`);if(!lines.length)lines.push('No events yet.');lines.reverse().forEach(t=>{const li=document.createElement('li');li.textContent=t;log.append(li)})}
function renderRuns(){const list=jobs.filter(j=>j.config.mode===mode);const capRuns=system.max_runs||24;$('run-count').textContent=`${jobs.length}/${capRuns}`;const box=$('run-list');box.replaceChildren();const t=target();
if(!list.length){const empty=document.createElement('p');empty.className='empty-runs';empty.textContent='No saved experiments in this mode.';box.append(empty);return}
for(const j of list){const card=document.createElement('div');card.className='run lab-run'+(j.id===t?.id?' active':'');const pick=document.createElement('button');pick.className='run-pick';const ng=j.config.n_galaxies||j.meta?.n_galaxies||1;const name=document.createElement('span');name.textContent=j.config.mode==='galaxy'?`${ng>1?`${ng} galaxies · `:''}${fmt(j.config.n)} particles · ${j.config.threads} threads · ${Math.round(j.config.duration*MYR_PER_TIME)} Myr${j.meta?.lifecycle_enabled?' · lifecycle':''}`:`${j.meta?.title||'Solar System'} · ${j.config.duration} yr`;const small=document.createElement('small');small.textContent=`${phaseLabel(j.status)} · rev ${j.meta?.model_revision??'?'} · ${new Date(j.config.created*1000).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})} · ${j.id}${j.config.notes?` · ${j.config.notes.slice(0,60)}`:''}`;pick.append(name,small);pick.title='Load these settings as a draft and show this run\'s status';
pick.onclick=()=>{selectedId=j.id;values[mode]=fromConfig(mode,j.config);syncInputs();scheduleSave();renderStatus();renderRuns();refreshHistory();toast(`Loaded settings from ${j.id} as a draft. Press Start computation to run a new experiment.`)};card.append(pick);
if(j.protected){const tag=document.createElement('span');tag.className='protected';tag.textContent='Preserved';tag.title='Preserved comparison experiment.';card.append(tag)}
else{const rm=document.createElement('button');rm.className='remove';rm.textContent='Remove';const live=ACTIVE.includes(j.status.phase);rm.disabled=live;rm.title=live?'Pause or finish this experiment before removing it.':'Delete this run from disk';rm.onclick=()=>removeRun(j);card.append(rm)}
box.append(card)}}
async function removeRun(j){const lines=[`Remove experiment ${j.id}?`,`${j.config.mode} · ${fmt(j.meta?.n||j.config.n)} particles · ${phaseLabel(j.status)}`,'This deletes frames and checkpoints on disk.'];if(j.status.phase==='paused')lines.push('This will stop the paused worker, then delete.');if(!confirm(lines.join('\n')))return;try{await api(`/api/jobs/${j.id}`,undefined,'DELETE');if(selectedId===j.id)selectedId=null;toast(`Removed ${j.id}.`);await poll()}catch(e){toast(e.message)}}
function heap(){const mem=performance.memory;if(!mem){$('heap').textContent='JS heap n/a (Chrome only) · tab budget 300 MB';return}const mb=mem.usedJSHeapSize/1048576;$('heap').textContent=`JS heap ${mb.toFixed(0)} MB · tab budget 300 MB`;if(mb>220){eventLines=5;$('heap').classList.add('warn')}else if(mb>150){console.warn(`Compute page heap ${mb.toFixed(0)} MB`);$('heap').classList.add('warn')}else{$('heap').classList.remove('warn');eventLines=20}}
function pollDelay(){const j=target();if(!j)return 2000;if(j.status.pause_pending||j.status.phase==='pausing')return 400;if(ACTIVE.includes(j.status.phase))return 1000;return 2000}
async function poll(){if(polling||document.hidden)return;polling=true;try{const pack=await Promise.all([api('/api/jobs?view=summary'),api('/api/queue'),api('/api/system')]);jobs=pack[0];queue=pack[1];system=pack[2]||{};renderQueue();renderStatus();renderRuns();await refreshHistory();if(logOpen)await refreshLog()}catch(e){$('phase').textContent='Server unavailable';$('status-sub').textContent='Restart the local app (Start Open Orbital.command or start-openorbital).'}finally{polling=false;heap()}}
function schedule(){clearTimeout(pollTimer);pollTimer=setTimeout(async()=>{await poll();if(!document.hidden)schedule()},pollDelay())}
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(pollTimer);else{schedule();poll()}});
async function refreshLog(){const j=target();if(!j)return;try{const {lines}=await api(`/api/jobs/${j.id}/log?tail=40`);$('worker-log').textContent=lines.length?lines.join('\n'):'(worker log is empty)'}catch(e){$('worker-log').textContent=e.message}}
$('show-log').onclick=async()=>{logOpen=!logOpen;$('worker-log').classList.toggle('hidden',!logOpen);$('show-log').textContent=logOpen?'Hide worker log':'Show worker log';if(logOpen)await refreshLog()};
function setMode(next){mode=next;$('galaxy-tab').classList.toggle('active',mode==='galaxy');$('planets-tab').classList.toggle('active',mode==='planets');$('setup-desc').innerHTML=mode==='galaxy'?'Small changes to the initial conditions become real gravitational differences at every computed step. Sliders never retune a running integrator: <b>Start computation</b> always creates a new experiment. Estimated wall time lives on the right and updates as you drag.':'Scale planetary masses or add a perturber, then integrate with IAS15. <b>Start computation</b> always creates a new experiment. Estimated wall time lives on the right and updates as you drag.';renderSliders();renderRuns();renderStatus();scheduleSave()}
$('galaxy-tab').onclick=()=>{selectedId=null;setMode('galaxy')};$('planets-tab').onclick=()=>{selectedId=null;setMode('planets')};
$('reset-defaults').onclick=()=>{values[mode]=defaultsFor(mode);syncInputs();scheduleSave();toast('Sliders reset to defaults.')};
$('start-compute').onclick=async()=>{const button=$('start-compute');button.dataset.busy='1';button.disabled=true;try{const cfg=toConfig(mode,values[mode]);cfg.notes=$('notes').value.trim();const j=await api('/api/jobs',cfg);selectedId=j.id;clearTimeout(saveTimer);localStorage.removeItem(DRAFT_KEY);toast('Computation started. Frames will appear on the Observe page.');await poll()}catch(e){toast(e.message);await poll()}finally{button.dataset.busy='0';updateEstimate()}};
$('stop-compute').onclick=async()=>{const j=target();if(!j)return;const s=j.status;const cancel=s.pause_pending&&!['paused','interrupted'].includes(s.phase);const resume=['paused','interrupted'].includes(s.phase);try{const res=await api(`/api/jobs/${j.id}/control`,{action:resume||cancel?'run':'pause'});if(res.status){const idx=jobs.findIndex(x=>x.id===j.id);if(idx>=0)jobs[idx]={...jobs[idx],status:{...jobs[idx].status,...res.status}};armPauseEta(res.status);renderStatus();renderRuns()}toast(resume?'Computation resume sent.':cancel?'Pause cancelled. The integrator will keep this chunk.':'Stop requested. The integrator checks about four times a second, then writes a checkpoint.');await poll()}catch(e){toast(e.message)}};
loadDraft();$('notes').value='From Cursor, Grok 4.6: galaxy encounter lab (revision 4)';setMode(mode);schedule();poll();
clearInterval(etaTimer);etaTimer=setInterval(renderPauseEta,250);

// Waiting rows use ids persisted by the server, not creation timestamps or mode filters.
function renderQueue(){
  const blocked=queue.message||'';
  $('queue-message').textContent=(queue.enabled?'Enabled. ':'Held. ')+blocked;
  $('start-queue').disabled=queue.enabled||(!queue.ids.length&&!queue.current);
  $('hold-queue').disabled=!queue.enabled;
  const list=$('queue-list');list.replaceChildren();
  if(queue.current){const cur=jobs.find(x=>x.id===queue.current);const li=document.createElement('li');li.className='queue-item current';li.textContent=cur?`Current: ${phaseLabel(cur.status)} · ${cur.id}`:`Current: ${queue.current}`;list.append(li)}
  for(const [index,id] of queue.ids.entries()){
    const j=jobs.find(x=>x.id===id);if(!j)continue;
    const row=document.createElement('li');row.className='queue-item';const label=document.createElement('span');
    label.textContent=`${j.config.mode==='galaxy'?fmt(j.config.n)+' particles':'Planetary system'} · ${fmtSeconds(j.config.estimated_seconds)} estimated · ${j.config.notes||id}`;row.append(label);
    const actions=document.createElement('div');actions.className='queue-item-actions';
    for(const [text,action,disabled] of [['Move up','up',index===0],['Move down','down',index===queue.ids.length-1]]){
      const b=document.createElement('button');b.className='secondary small';b.textContent=text;b.disabled=disabled;b.onclick=()=>changeQueue(action,id);actions.append(b);
    }
    const rm=document.createElement('button');rm.className='secondary small';rm.textContent='Remove';rm.onclick=()=>removeRun(j);actions.append(rm);row.append(actions);list.append(row);
  }
  if(!queue.ids.length&&!queue.current){const li=document.createElement('li');li.className='queue-item is-empty';li.textContent='No waiting experiments.';list.append(li)}
}
async function changeQueue(action,id){try{await api('/api/queue',{action,id});await poll()}catch(e){toast(e.message)}}
$('start-queue').onclick=()=>changeQueue('start');$('hold-queue').onclick=()=>changeQueue('hold');
$('add-queue').onclick=async()=>{const b=$('add-queue');b.dataset.busy='1';b.disabled=true;try{const cfg=toConfig(mode,values[mode]);cfg.notes=$('notes').value.trim();await api('/api/queue/jobs',cfg);toast('Experiment added to the queue.');await poll()}catch(e){toast(e.message)}finally{b.dataset.busy='0';updateEstimate()}};
