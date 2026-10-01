// AGENT MAP: the whole observatory in one page. Library (left) · stage (3D, centre) · context panel (Run / New / Nodes, right).
// Physics never runs here. The stage shows saved frames of the selected run, or an 8,000-particle initial-conditions preview
// while composing. viewer.js (Three.js) is imported lazily and can be switched off to free the GPU context and frame cache.
// Polls summary JSON only; full job JSON (times, bodies) is fetched once per selected run. Server SCHEMA is the authority.
import {REALISTIC_SUPERSEDED,slidersFor,defaultsFor,toConfig,fromConfig,maxDuration,durationCap,engineRamGb,fmt,fmtHours,fmtSeconds,fmtNum,percent,api,phaseLabel,WALL_CAP_HOURS,MYR_PER_TIME,nodeEstimate,nodeColor,nodeThreads,fmtAgo} from './shared.js';
const $=id=>document.getElementById(id);
const DRAFT_KEY='orbital-draft-v3',ACTIVE=['running','initializing','pausing'],MOVING=['pausing','copying','starting'];
let mode='galaxy',panel='run',jobs=[],queue={enabled:false,ids:[]},system={},nodes=[],selectedId=null,full=null;
let values={galaxy:defaultsFor('galaxy'),planets:defaultsFor('planets')},placement={node:'local',split:false,legs:[],standby:'auto',returnOnWake:true,twin:''};
let realisticInfo=null,realisticKey='',realisticTimer=null;
let rows={},viewer=null,viewerLoading=null,renderOn=true,toastTimer,saveTimer,pollTimer,previewTimer,previewSeq=0,logOpen=false,pauseEta=null,historyKey='',polling=false;

// ---------- helpers ----------
function toast(message){$('toast').textContent=message;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),6500)}
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
function dd(parent,label,value,title){const d=el('div'),t=el('dt',null,label),v=el('dd',null,value);if(title)v.title=title;d.append(t,v);parent.append(d)}
const nodeById=id=>nodes.find(n=>n.id===id)||{id,label:id};
const label=id=>nodeById(id).label||id;
const selected=()=>jobs.find(j=>j.id===selectedId)||null;
const locOf=j=>j?.location||{node:'local',history:[]};
const moving=j=>MOVING.includes(locOf(j).transfer?.state);
function runTitle(j){const c=j.config,m=j.meta||{};if(c.mode==='planets')return `${m.title||'Solar System'} · ${c.duration} yr`;const ng=c.n_galaxies||m.n_galaxies||1;return `${ng>1?`${ng} galaxies · `:''}${fmt(c.n)} particles · ${Math.round(c.duration*MYR_PER_TIME)} Myr`}
function nodeDot(id){const s=el('i','ndot');s.style.setProperty('--c',nodeColor(nodes,id));s.title=label(id);return s}

// ---------- viewer (lazy) ----------
async function ensureViewer(){
  if(viewer||!renderOn)return viewer;
  if(!viewerLoading)viewerLoading=import('./viewer.js').then(m=>{viewer=m.createViewer($('space'),$('planet-labels'),{
    onTime:t=>{$('time-value').textContent=t.time.toFixed(stageMode()==='galaxy'?1:2);$('timeline').value=t.position;$('empty').classList.add('hidden');renderLive()},
    onFps:fps=>{$('render-state').textContent=viewer?.previewing?`${fps} FPS · initial-conditions preview, nothing integrated`:viewer?.job?`${fps} FPS playback · ${stageMode()==='galaxy'?'3 kpc per model unit':'linear orbital distances'}${viewer.sampling?` · drawing 1 in ${viewer.sampling.k} (${fmt(viewer.sampling.m)} of ${fmt(viewer.sampling.n)} particles; Layers → Full detail)`:''}`:'Waiting for simulation frames'},
    onReady:()=>$('empty').classList.add('hidden'),onError:m=>{$('render-state').textContent=m},onPick:i=>i==null?closeInspector(true):openInspector(i)});if($('full-detail').checked)viewer.setFullDetail(true);
    syncLayers();return viewer}).finally(()=>viewerLoading=null);
  return viewerLoading}
function stageMode(){return viewer?.job?.config.mode||(panel==='new'?mode:selected()?.config.mode)||mode}
function setRender(on){renderOn=on;$('render-on').checked=on;if(!on&&viewer){viewer.dispose();viewer=null;$('render-state').textContent='3D rendering off — GPU context and frame cache released';showEmpty('3D rendering is off','Turn it back on under Layers. Computation is unaffected.')}else if(on)refreshStage(true)}
function showEmpty(h,p){$('empty').classList.remove('hidden');$('empty').querySelector('h2').textContent=h;$('empty').querySelector('p').textContent=p}

async function loadFull(j){
  // Full JSON carries meta.times and planet bodies, which the summary view strips.
  const id=j.id;try{const f=await api(`/api/jobs/${id}`);if(selectedId===id)full=f}catch(e){toast(e.message)}}
async function refreshStage(force){
  applyStageText();
  if(panel==='new'){schedulePreview(force);return}
  const j=selected();
  if(!j){viewer?.clear();showEmpty(jobs.length?'Pick an experiment':'A new experiment awaits',jobs.length?'Choose a run on the left to watch it.':'Press New experiment to compose one.');return}
  if(!full||full.id!==j.id||(!full.meta?.n&&j.meta?.n))await loadFull(j);
  if(!full||full.id!==selectedId)return;
  const merged={...full,status:j.status,location:j.location};
  const v=await ensureViewer();if(!v)return;
  if(v.job?.id!==j.id||v.previewing||force){showEmpty('Preparing your universe',j.status.frames?'Loading computed simulation frames…':'Waiting for the first computed frame…');v.load(merged);$('time-value').textContent='0'}
  else v.update(merged)}
function applyStageText(){
  const j=panel==='new'?null:selected(),m=panel==='new'?mode:(j?.config.mode||mode),g=m==='galaxy';
  document.querySelectorAll('.galaxy-only').forEach(e=>e.classList.toggle('hidden',!g));document.querySelectorAll('.planets-only').forEach(e=>e.classList.toggle('hidden',g));
  $('eyebrow').textContent=panel==='new'?'PREVIEW / INITIAL CONDITIONS':g?'EXPERIMENT / GALACTIC DYNAMICS':'EXPERIMENT / PLANETARY DYNAMICS';
  $('view-title').textContent=panel==='new'?(g?'Your galaxy, before the first step.':'Your worlds, at J2000.'):j?(j.meta?.title||runTitle(j)):(g?'A galaxy, in motion.':'Worlds around a star.');
  $('time-label').textContent=g?'MILLION YEARS':'SIMULATED YEARS';$('body-label').textContent=g?'GRAVITATING PARTICLES':'GRAVITATING BODIES';
  $('view-caption').textContent=panel==='new'?(g?'8,000-PARTICLE SAMPLE OF THE INITIAL CONDITIONS · NOTHING IS INTEGRATED UNTIL YOU PRESS START':'J2000 INITIAL CONDITIONS / ENLARGED PLANET SIZES'):g?'STELLAR DISK / LIVE DARK-MATTER HALO':'J2000 INITIAL CONDITIONS / ENLARGED PLANET SIZES';
  const s=j?.status;$('stage-phase').textContent=panel==='new'?'Preview':j?phaseLabel(s):'No experiment';$('stage-phase').dataset.phase=panel==='new'?'preview':s?.phase||'idle';
  const nb=$('stage-node');if(j&&panel!=='new'){nb.classList.remove('hidden');nb.textContent=moving(j)?`${label(locOf(j).transfer.source)} → ${label(locOf(j).transfer.to)}`:label(locOf(j).node);nb.style.setProperty('--c',nodeColor(nodes,locOf(j).node))}else nb.classList.add('hidden');
  $('body-count').textContent=panel==='new'?fmt(m==='galaxy'?values.galaxy.n:(values.planets.perturber_mass>0?10:9)):j?fmt(j.meta?.n||j.config.n):'—';$('frame-value').textContent=panel==='new'?'0':j?fmt(j.status.frames||0):'—';
  renderTimeline(j);syncLegend()}
function schedulePreview(now){clearTimeout(previewTimer);previewTimer=setTimeout(runPreview,now?0:350)}
async function runPreview(){
  if(panel!=='new')return;const seq=++previewSeq;const cfg=toConfig(mode,values[mode]);
  try{const r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});if(!r.ok)throw Error((await r.json()).error||'Preview failed');const buf=await r.arrayBuffer();if(seq!==previewSeq||panel!=='new')return;
    const v=await ensureViewer();if(!v)return;v.preview(buf,mode);$('empty').classList.add('hidden');$('time-value').textContent='0';$('time-range').textContent='initial conditions only'}
  catch(e){if(seq===previewSeq)$('render-state').textContent=e.message}}

// ---------- timeline with node segments ----------
function renderTimeline(j){
  const bar=$('segments');bar.replaceChildren();
  if(!j||panel==='new'){$('timeline').max=1;$('time-range').textContent=panel==='new'?'initial conditions only':'—';return}
  const total=Math.max(1,(j.meta?.total_frames||j.status.frames||1)-1),frames=j.status.frames||0,hist=locOf(j).history||[];
  $('timeline').max=Math.max(0,frames-1);const m=j.meta||{};
  $('time-range').textContent=`0 — ${((j.status.computed_time||0)*(m.time_scale||1)).toFixed(j.config.mode==='galaxy'?0:1)} ${m.time_unit||''} computed`;
  const segs=hist.length?hist:[{node:'local',start_frame:0}];
  segs.forEach((s,i)=>{const a=s.start_frame||0,b=i+1<segs.length?segs[i+1].start_frame:Math.max(a,frames-1);if(b<=a&&i+1<segs.length)return;
    const d=el('span','seg');d.style.left=`${a/total*100}%`;d.style.width=`${Math.max(.4,(b-a)/total*100)}%`;d.style.setProperty('--c',nodeColor(nodes,s.node));d.title=`${label(s.node)} · frames ${a}–${b}`;bar.append(d)});
  const plan=locOf(j).plan;if(plan)plan.legs.slice(plan.leg,-1).forEach((l,k)=>{const mk=el('span','seg-plan');mk.style.left=`${l.until*100}%`;mk.title=`Planned hand-off to ${label(plan.legs[plan.leg+k+1].node)}`;bar.append(mk)});
  if(frames-1<total){const rest=el('span','seg-rest');rest.style.left=`${Math.max(0,frames-1)/total*100}%`;rest.style.width=`${(total-Math.max(0,frames-1))/total*100}%`;rest.title='Not computed yet';bar.append(rest)}}

// ---------- library ----------
function renderRuns(){
  const box=$('run-list');box.replaceChildren();const cap=system.max_runs||24;$('run-count').textContent=`${jobs.length}/${cap}`;
  const live=jobs.filter(j=>ACTIVE.includes(j.status.phase)||moving(j)),rest=jobs.filter(j=>!live.includes(j)&&j.config.mode===mode);
  const group=(title,list)=>{if(!list.length)return;box.append(el('div','run-group',title));list.forEach(j=>box.append(runCard(j)))};
  group('COMPUTING NOW',live);group(mode==='galaxy'?'GALAXY RUNS':'PLANETARY RUNS',rest);
  if(!box.children.length)box.append(el('p','empty-runs','No saved experiments in this mode yet.'))}
function runCard(j){
  const b=el('button','run'+(j.id===selectedId&&panel!=='new'?' active':''));b.dataset.phase=j.status.phase;
  const top=el('span','run-top');const segs=el('span','run-nodes');const hist=locOf(j).history||[];(hist.length?[...new Set(hist.map(h=>h.node))]:['local']).forEach(n=>segs.append(nodeDot(n)));
  top.append(segs,el('span','run-name',runTitle(j)));
  const small=el('small',null,`${phaseLabel(j.status)} · ${label(locOf(j).node)} · ${new Date(j.config.created*1000).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}`);
  const prog=el('span','run-progress');const f=el('i');f.style.width=`${(j.status.progress||0)*100}%`;f.style.background=nodeColor(nodes,locOf(j).node);prog.append(f);
  if(locOf(j).twin){const t=el('span','twin-mark','⧉');t.title='Has a twin run on another machine';top.append(t)}
  b.append(top,small,prog);if(j.protected)b.append(el('span','protected','Preserved'));
  b.onclick=()=>select(j.id);return b}
function select(id){selectedId=id;full=null;historyKey='';pauseEta=null;const j=selected();if(j&&j.config.mode!==mode){mode=j.config.mode;syncModeTabs()}setPanel('run');renderRuns();refreshStage(true)}

// ---------- run panel ----------
const speedSamples={};
function renderSpeed(j){
  const card=$('speed-card'),s=j?.status;
  if(!j||!ACTIVE.includes(s.phase)){card.classList.add('hidden');return}
  const m=j.meta||{},c=j.config,ts=m.time_scale||1,u=m.time_unit||'',n=m.n||c.n||0,arr=speedSamples[j.id]||=[];
  const last=arr[arr.length-1];
  if(s.wall_seconds!=null&&s.computed_time!=null&&(!last||s.wall_seconds>last.w)){arr.push({w:s.wall_seconds,t:s.computed_time,k:s.steps??null});if(arr.length>6)arr.shift()}
  card.classList.remove('hidden');
  const rate=(a,b)=>b.w>a.w?(b.t-a.t)*ts/(b.w-a.w):null,txt=r=>r==null?'—':`${fmtNum(r)} ${u}/s`;
  const first=arr[0],cur=arr[arr.length-1],recent=arr.length>1?rate(first,cur):null;
  const avg=s.wall_seconds>0&&s.computed_time!=null?s.computed_time*ts/s.wall_seconds:null;
  const sps=arr.length>1&&first.k!=null&&cur.k!=null&&cur.w>first.w?(cur.k-first.k)/(cur.w-first.w):(s.steps!=null&&s.wall_seconds>0?s.steps/s.wall_seconds:null);
  $('speed-big').textContent=recent!=null?txt(recent):s.phase==='running'?'measuring…':'starting…';
  const best=recent??avg;$('speed-kind').textContent=best?`≈ ${fmtNum(best*3600)} ${u} of simulated time per hour of compute`:'waiting for the first saved frames';
  $('speed-recent').textContent=txt(recent);$('speed-avg').textContent=txt(avg);
  $('speed-steps').textContent=sps!=null?fmtNum(sps):'—';$('speed-ps').textContent=sps!=null&&n?fmtNum(sps*n):'—';
}

function renderRun(){
  const j=selected();renderHealth(j);if(!j)$('speed-card').classList.add('hidden');
  if(!j){$('status-heading').textContent='Nothing selected';$('status-sub').textContent='Pick an experiment on the left or start a new one.';$('phase').textContent='Idle';$('phase').dataset.phase='idle';$('progress-bar').style.width='0%';['progress-label','frame-label','eta-kind'].forEach(i=>$(i).textContent='');$('eta-big').textContent='—';$('stop-compute').disabled=true;$('remove-run').disabled=true;$('where-body').replaceChildren();$('diagnostics').replaceChildren();$('event-log').replaceChildren();$('move-run').disabled=true;return}
  const s=j.status,m=j.meta||{},c=j.config,d=s.diagnostics||{},lc=d.lifecycle,loc=locOf(j),total=m.total_frames||0,frames=s.frames||0,remaining=Math.max(0,total-frames);
  armPauseEta(s);
  $('status-heading').textContent=m.title||runTitle(j);
  $('status-sub').textContent=`${c.mode==='galaxy'?`${fmt(c.n)} particles · ${s.openmp_threads??c.threads} threads`:`${m.n||c.n} bodies`} · span ${c.mode==='galaxy'?`${Math.round(c.duration*MYR_PER_TIME)} Myr`:`${c.duration} yr`}${c.realistic?' · Real World Physics':''}${c.notes?` · ${c.notes}`:''}`;
  $('phase').textContent=moving(j)?`Hand-off: ${loc.transfer.state}`:phaseLabel(s);$('phase').dataset.phase=moving(j)?'pausing':s.pause_pending&&s.phase==='running'?'pausing':s.phase;
  $('progress-bar').style.width=`${(s.progress||0)*100}%`;$('progress-bar').style.background=nodeColor(nodes,loc.node);$('progress-label').textContent=`${Math.round((s.progress||0)*100)}% computed`;$('frame-label').textContent=total?`frame ${fmt(frames)} / ${fmt(total)}${s.frames_behind?` · ${fmt(s.frames_behind)} syncing`:''}`:`${fmt(frames)} frames`;
  if(ACTIVE.includes(s.phase)&&s.last_frame_compute_seconds!=null){$('eta-big').textContent=`${fmtSeconds(s.last_frame_compute_seconds*remaining)} remaining`;$('eta-kind').textContent=`from the last chunk on ${label(loc.node)}`}
  else if(s.phase==='complete'){$('eta-big').textContent='done';$('eta-kind').textContent=`${fmtSeconds(s.wall_seconds)} of compute`}
  else{$('eta-big').textContent=c.placement?.estimated_seconds?`${fmtSeconds(c.placement.estimated_seconds)} estimated`:'—';$('eta-kind').textContent='estimate before start (prediction)'}
  renderStopButton(j);renderPauseEta();$('remove-run').disabled=j.protected||ACTIVE.includes(s.phase)||moving(j);$('remove-run').title=j.protected?'Preserved comparison run':'Delete this run (and its node copy) from disk';
  renderWhere(j);renderTwin(j);renderSpeed(j);
  $('wall-time').textContent=fmtSeconds(s.wall_seconds);$('computed-time').textContent=s.computed_time==null?'—':`${(s.computed_time*(m.time_scale||1)).toFixed(c.mode==='galaxy'?1:2)} ${m.time_unit||''}`;$('last-chunk').textContent=fmtSeconds(s.last_frame_compute_seconds);
  $('threads-val').textContent=s.openmp_threads!=null&&c.threads!=null&&s.openmp_threads!==c.threads?`${s.openmp_threads} of ${c.threads}`:(s.openmp_threads??c.threads??'—');$('particles-val').textContent=fmt(m.n||c.n||0);$('revision-val').textContent=m.model_revision??'—';$('job-id').textContent=j.id;$('steps-val').textContent=s.steps!=null?fmt(s.steps):'—';
  const dl=$('diagnostics');dl.replaceChildren();
  if(d.energy!=null){dd(dl,m.lifecycle_enabled?'Energy change (lifecycle on; not an error bound)':d.energy_sampled?'Sampled energy change (Monte Carlo)':'Energy change',percent(d.energy_change)+(d.energy_sampled&&d.energy_change_uncertainty!=null?` ± ${percent(d.energy_change_uncertainty)}`:''));dd(dl,'Angular momentum change',percent(d.angular_change));if(c.mode==='galaxy'){dd(dl,'Disk half-radius',`${fmtNum(d.disk_half_radius*3)} kpc (${d.disk_radius_change==null?'—':(d.disk_radius_change*100).toFixed(1)+'%'})`);if(d.halo_half_radius!=null)dd(dl,'Halo half-radius',`${fmtNum(d.halo_half_radius*3)} kpc`)}}
  const enc=d.encounter;if(enc){if(enc.separation_12!=null)dd(dl,'Galaxy 1–2 separation',`${fmtNum(enc.separation_12*3)} kpc · vrel ${fmtNum(enc.vrel_12*119.7)} km/s`);if(enc.min_separation!=null)dd(dl,'Closest approach so far',`${fmtNum(enc.min_separation*3)} kpc`)}
  const rp=s.realistic;
  if(rp)dd(dl,'Timestep now (Real World Physics)',`${fmtNum(rp.dt_myr)} Myr · limited by ${rp.limiter}${rp.dt_min_myr!=null&&rp.dt_min_myr<rp.dt_myr*.99?` · smallest this frame ${fmtNum(rp.dt_min_myr)} Myr`:''}`,'Largest step keeping dt ≤ √(2ηε/|a|) for every particle and the gas Courant condition.');
  if(lc?.ssp){dd(dl,'Gas / stars (stellar populations)',`${fmtNum(lc.gas_mass)} / ${fmtNum(lc.stellar_mass)} ×10¹⁰ M☉ · ${fmt(lc.counts?.gas||0)} gas particles`);dd(dl,'Star-formation rate',`${fmtNum(lc.sfr*1e4)} M☉ / yr`);
    dd(dl,'Star particles formed / supernovae',`${fmt(lc.births_cumulative||0)} / ${fmt(lc.supernovae_cumulative||0)}`);dd(dl,'Mass returned by stars',`${fmtNum(lc.returned_mass*1e4)} ×10⁶ M☉`);
    dd(dl,'Supernova momentum to gas',`${fmtNum(lc.feedback_momentum*1e10*119.7)} M☉ km/s${lc.feedback_momentum_unused>0?` (${fmtNum(lc.feedback_momentum_unused*1e10*119.7)} with no gas nearby)`:''}`)}
  else if(lc){const cnt=lc.counts||{};dd(dl,'Gas / stellar / remnant mass',`${fmtNum(lc.gas_mass)} / ${fmtNum(lc.stellar_mass)} / ${fmtNum(lc.remnant_mass)} ×10¹⁰ M☉`);dd(dl,'Star-formation rate',`${fmtNum(lc.sfr*1e4)} ×10⁶ M☉ / Myr`);dd(dl,'Births / deaths / supernovae',`${fmt(lc.births_cumulative||0)} / ${fmt(lc.deaths_cumulative||0)} / ${fmt(lc.supernovae_cumulative||0)}`);dd(dl,'Population',`gas ${fmt(cnt.gas||0)} · proto ${fmt(cnt.protostar||0)} · MS ${fmt(cnt.main_sequence||0)} · giant ${fmt(cnt.giant||0)} · WD ${fmt(cnt.white_dwarf||0)} · NS ${fmt(cnt.neutron_star||0)} · BH ${fmt(cnt.black_hole||0)}`)}
  if(!dl.children.length)dd(dl,'Diagnostics','Waiting for the first computed state.');
  const log=$('event-log');log.replaceChildren();const lines=[...(s.events||[])].slice(-20);if(loc.transfer?.note)lines.push(loc.transfer.note);if(loc.transfer?.error)lines.push(`Hand-off: ${loc.transfer.error}`);if(s.error)lines.push(`Error: ${s.error}`);if(!lines.length)lines.push('No events yet.');lines.reverse().forEach(t=>log.append(el('li',null,t)));
  const md=full?.id===j.id?full.meta:{};$('model-description').textContent=md?.description||'Open the run to load its model description.';$('source-link').href=md?.sources?.[0]||'https://rebound.hanno-rein.de/'}
function renderWhere(j){
  const loc=locOf(j),box=$('where-body');box.replaceChildren();const t=loc.transfer,sync=loc.sync;
  const now=el('div','where-now');now.append(nodeDot(loc.node),el('b',null,label(loc.node)));
  if(loc.node!=='local')now.append(el('span','micro',loc.synced_complete?' · finished; every frame is on this Mac':sync?.reachable===false?` · unreachable: ${sync.error||''}`:sync?.age!=null?` · synced ${fmtAgo(sync.age)}`:' · waiting for first sync'));
  box.append(now);
  const hist=loc.history||[];if(hist.length>1){const ol=el('ol','where-hist');hist.forEach((h,i)=>{const next=hist[i+1];const li=el('li');li.append(nodeDot(h.node),document.createTextNode(` ${label(h.node)} · frames ${h.start_frame}–${next?next.start_frame:(j.status.frames||1)-1}`));ol.append(li)});box.append(ol)}
  if(loc.plan){const line=el('div','plan-line');line.append(el('span',null,'Plan:'));loc.plan.legs.forEach((l,i)=>{const c=el('span','leg-chip'+(i===loc.plan.leg?' now':''),label(l.node));c.style.setProperty('--c',nodeColor(nodes,l.node));line.append(c);if(i<loc.plan.legs.length-1)line.append(el('span',null,`→ ${Math.round(l.until*100)}% →`))});box.append(line);if(loc.plan.waiting)box.append(el('p','micro warn',loc.plan.waiting))}
  const sb=loc.standby;
  if(sb?.note)box.append(el('p','micro',sb.note));
  else if(sb?.node&&loc.node==='local'){const armed=sb.armed_on===sb.node;box.append(el('p','micro'+(sb.error?' warn':''),sb.error?`Standby copy to ${label(sb.node)} failed: ${sb.error}`:armed?`Standby: ${label(sb.node)} holds a checkpoint from frame ${sb.index} (copied ${fmtAgo(Date.now()/1000-sb.pushed_at)}). If this Mac goes quiet for 90 s it resumes from there${sb.return_on_wake?' and hands back when the Mac wakes':''}.`:`Standby on ${label(sb.node)}: armed once the run is computing and has a checkpoint.`))}
  const row=$('standby-row');const showSb=loc.node==='local'&&!['complete','error'].includes(j.status.phase)&&!j.protected;row.classList.toggle('hidden',!showSb);
  if(showSb){const ss=$('run-standby');const keep=document.activeElement===ss;if(!keep){ss.replaceChildren();const off=el('option',null,'nobody (pause with the Mac)');off.value='';ss.append(off);nodes.filter(n=>n.id!=='local').forEach(n=>{const o=el('option',null,`continue on ${n.label}`);o.value=n.id;o.disabled=n.health?.ready===false;ss.append(o)});ss.value=sb?.node||'';$('run-return').checked=sb?.return_on_wake!==false}}
  if(t&&MOVING.includes(t.state))box.append(el('p','micro warn',`Hand-off in progress: ${t.state} (${label(t.source)} → ${label(t.to)}).`));
  else if(t?.state==='failed')box.append(el('p','micro warn',`Last hand-off failed: ${t.error}`));
  const sel=$('move-target');const cur=sel.value;sel.replaceChildren();nodes.filter(n=>n.id!==loc.node).forEach(n=>{const o=el('option',null,`${n.label}${n.health?.ready===false?' (not ready)':n.busy?' (busy)':''}`);o.value=n.id;o.disabled=n.health?.ready===false||n.busy;sel.append(o)});if(cur&&[...sel.options].some(o=>o.value===cur&&!o.disabled))sel.value=cur;
  const phase=j.status.phase;$('move-run').disabled=!sel.options.length||[...sel.options].every(o=>o.disabled)||['complete','error','queued'].includes(phase)||moving(j)||j.protected;
  $('move-run').title=['complete','error'].includes(phase)?'Finished runs stay where their frames are.':''}
let twinKey='',twinData=null;
async function renderTwin(j){
  const card=$('twin-card'),other=locOf(j).twin;card.classList.toggle('hidden',!other);if(!other)return;
  const o=jobs.find(x=>x.id===other);$('open-twin').onclick=()=>select(other);$('open-twin').disabled=!o;
  const key=`${j.id}:${j.status.frames}:${o?.status.frames}`;
  if(key!==twinKey){twinKey=key;try{twinData=await api(`/api/jobs/${j.id}/twin`)}catch(e){twinData=null}}
  const d=twinData;if(!d||selectedId!==j.id)return;const pts=d.points||[],kpc=d.length_scale_kpc||3;
  const me=d.a.id===j.id?d.a:d.b,them=d.a.id===j.id?d.b:d.a,last=pts.at(-1);
  $('twin-summary').textContent=!pts.length?`Twin on ${label(them.node)}. Waiting for both runs to share computed frames.`:
    `This run on ${label(me.node)} vs its twin on ${label(them.node)} over ${pts.length} shared frames (${fmt(d.sample)} sampled particles). Latest median separation ${fmtNum(last.median*kpc)} kpc, 90th percentile ${fmtNum(last.p90*kpc)} kpc${last.max===0?' — bit-identical so far (same CPU type and thread count)':''}. Divergence here is floating-point rounding amplified by chaos, not a bug; compare it with the disk half-radius below to judge what is robust.`;
  drawSparkMulti('chart-twin',[pts.map(p=>p.median),pts.map(p=>p.p90)],['#b2dfc6','#e0b07a']);
  const dl=$('twin-table');dl.replaceChildren();const pair=(k,f)=>`${f(me[k])} here · ${f(them[k])} twin`;const kp=v=>v==null?'—':`${fmtNum(v*kpc)} kpc`;
  dd(dl,'Disk half-radius',pair('disk_half_radius',kp));dd(dl,'Energy change',pair('energy_change',percent));
  if(me.min_separation!=null||them.min_separation!=null)dd(dl,'Closest approach (galaxies 1–2)',pair('min_separation',kp));
  if(me.births!=null||them.births!=null)dd(dl,'Star births',pair('births',v=>v==null?'—':fmt(v)))}
function drawSparkMulti(id,series,colors){const svg=$(id);svg.replaceChildren();const all=series.flat().filter(v=>v!=null&&isFinite(v));if(all.length<2){drawSpark(id,[],colors[0]);return}const lo=0,hi=Math.max(...all)||1,w=320,h=90,pad=6;
  series.forEach((vs,k)=>{const d=vs.map((v,i)=>`${i?'L':'M'}${(pad+i*(w-2*pad)/Math.max(vs.length-1,1)).toFixed(1)} ${(h-pad-((v-lo)/(hi-lo))*(h-2*pad)).toFixed(1)}`).join(' ');const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',d);p.setAttribute('fill','none');p.setAttribute('stroke',colors[k]);p.setAttribute('stroke-width','1.6');svg.append(p)})}
function renderHealth(j){
  const s=j?.status||{},loc=locOf(j);$('health-daemon').textContent=system.daemon?'up (LaunchAgent)':'foreground / unknown';
  $('health-sleep').textContent=system.sleep_prevention==='idle'?'on while integrating here':'off';
  $('health-worker').textContent=!j?'—':loc.node==='local'?(system.worker_pid?`pid ${system.worker_pid}`:'none on this Mac'):`${label(loc.node)} · ${loc.sync?.alive?'alive':'not running'}`;
  $('health-checkpoint').textContent=s.checkpoint_age_seconds==null?'—':fmtAgo(s.checkpoint_age_seconds);
  const capAt=s.wall_cap_at||WALL_CAP_HOURS*3600;$('health-cap').textContent=j?fmtSeconds(Math.max(0,capAt-(s.wall_seconds||0))):`${WALL_CAP_HOURS} h`}
function renderStopButton(j){const b=$('stop-compute'),s=j.status,pending=!!s.pause_pending&&!['paused','interrupted'].includes(s.phase);
  if(moving(j)){b.disabled=true;b.textContent='Handing off…';return}
  if(s.phase==='pausing'){b.disabled=true;b.textContent='Writing checkpoint…';return}
  if(pending){b.disabled=false;b.textContent='Cancel pause';return}
  if(['paused','interrupted'].includes(s.phase)){b.disabled=false;b.textContent=`Resume on ${label(locOf(j).node)}`;return}
  b.disabled=['complete','error','queued'].includes(s.phase);b.textContent='Stop computation'}
function armPauseEta(s){if(s.phase==='pausing'){pauseEta={seconds:0,at:Date.now()/1000};return}if(!s.pause_pending||['paused','interrupted','complete','error'].includes(s.phase)){pauseEta=null;return}if(!pauseEta)pauseEta={seconds:s.pause_eta_seconds,at:Date.now()/1000}}
function renderPauseEta(){const j=selected(),e=$('pause-eta');let text='';if(j){const s=j.status;if(s.phase==='pausing')text='Integrator reached a pause point. Writing a checkpoint now — tens of seconds at 1,000,000 particles.';else if(s.pause_pending&&s.phase==='initializing')text='Pause queued. It applies after initial conditions are built.';else if(pauseEta){const left=pauseEta.seconds==null?null:Math.max(0,pauseEta.seconds-(Date.now()/1000-pauseEta.at));text=left==null?'Stop requested. Waiting for the current leapfrog step, then a checkpoint.':left<1?'Stop requested. Checkpoint should begin any moment.':`Stop requested. Up to ${fmtSeconds(left)} for the current leapfrog step, then a checkpoint.`}}e.classList.toggle('hidden',!text);e.textContent=text}

// ---------- history sparklines ----------
function sparkPath(vs,w=320,h=64,pad=6){const nums=vs.filter(v=>v!=null&&isFinite(v));if(nums.length<2)return '';const lo=Math.min(...nums),hi=Math.max(...nums),span=hi-lo||1;return nums.map((v,i)=>`${i?'L':'M'}${(pad+i*(w-2*pad)/Math.max(nums.length-1,1)).toFixed(1)} ${(h-pad-((v-lo)/span)*(h-2*pad)).toFixed(1)}`).join(' ')}
function drawSpark(id,vs,color){const svg=$(id);svg.replaceChildren();const d=sparkPath(vs);if(!d){const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x','12');t.setAttribute('y','36');t.setAttribute('class','spark-empty');t.textContent='No history yet';svg.append(t);return}const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',d);p.setAttribute('fill','none');p.setAttribute('stroke',color);p.setAttribute('stroke-width','1.6');p.setAttribute('stroke-linejoin','round');svg.append(p)}
async function refreshHistory(){const j=selected();const key=j?`${j.id}:${j.status.frames}`:'';if(key===historyKey)return;historyKey=key;let pts=[];if(j){try{pts=(await api(`/api/jobs/${j.id}/history`)).points||[]}catch(e){}}drawSpark('chart-radius',pts.map(p=>p.disk_half_radius),'#9fc6b1');drawSpark('chart-sfr',pts.map(p=>p.sfr!=null?p.sfr:p.births),'#e0b07a');drawSpark('chart-energy',pts.map(p=>p.energy_change),'#8bb4d9')}
async function refreshLog(){const j=selected();if(!j)return;try{const {lines}=await api(`/api/jobs/${j.id}/log?tail=40`);$('worker-log').textContent=lines.length?lines.join('\n'):'(worker log is empty)'}catch(e){$('worker-log').textContent=e.message}}

// ---------- compose ----------
function loadDraft(){try{const d=JSON.parse(localStorage.getItem(DRAFT_KEY)||'null');if(!d)return;for(const m of['galaxy','planets'])if(d[m]){const base=defaultsFor(m);for(const s of slidersFor(m))if(d[m][s.id]!=null)base[s.id]=d[m][s.id];values[m]=base}if(d.placement){placement={...placement,...d.placement};if(!Array.isArray(placement.legs))placement.legs=[]}}catch(e){try{localStorage.removeItem(DRAFT_KEY)}catch(_){}}}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>{try{localStorage.setItem(DRAFT_KEY,JSON.stringify({galaxy:values.galaxy,planets:values.planets,placement}))}catch(e){}},200)}
function readout(s,v){if(s.kind==='bool')return v?'on':'off';return s.kind==='choice'||s.kind==='number'||Number.isInteger(s.step)?fmt(v):Number(v).toLocaleString('en-US',{maximumFractionDigits:4})}
function unitLine(s,v){if(s.kind==='bool')return '';if(s.physical){const p=s.physical(Number(v));if(p)return p}return s.unit||''}
function tickLabel(s,st){if(s.id==='n'&&st>=1000)return st>=1e6?`${st/1e6}M`:`${st/1000}k`;return fmt(st)}
function renderSliders(){
  const list=slidersFor(mode).filter(s=>s.group!=='Physics');rows={};$('sliders').replaceChildren();$('slider-count').textContent=`${list.length} controls`;
  for(const g of [...new Set(list.map(s=>s.group))]){
    const box=el('details','slider-group');box.open=['Compute','Encounter','Planet masses','Galaxy shape'].includes(g);box.append(el('summary',null,g));
    for(const s of list.filter(x=>x.group===g)){
      const row=el('div',`slider-row kind-${s.kind||'range'}`),lab=el('label',null,s.label);lab.htmlFor=`k-${s.id}`;const out=el('output','readout'),unit=el('span','unit');let input;const v=values[mode][s.id];
      if(s.kind==='bool'){input=el('input');input.type='checkbox';input.checked=Boolean(v)}
      else if(s.kind==='number'){input=el('input');input.type='number';input.min=s.min;input.max=s.max;input.step=s.step;input.value=v}
      else if(s.kind==='choice'){input=el('input');input.type='range';input.min=0;input.max=s.stops.length-1;input.step=1;input.value=Math.max(0,s.stops.indexOf(Number(v)))}
      else{input=el('input');input.type='range';input.min=s.min;input.max=s.max;input.step=s.step;input.value=v}
      input.id=`k-${s.id}`;if(s.hint)input.title=s.hint;
      input.addEventListener('input',()=>{let val;if(s.kind==='bool')val=input.checked;else if(s.kind==='choice')val=s.stops[Number(input.value)];else if(s.kind==='number')val=Math.min(s.max,Math.max(s.min,Math.round(Number(input.value)||0)));else val=Number(input.value);values[mode][s.id]=val;out.textContent=readout(s,val);unit.textContent=unitLine(s,val);updateEstimate();scheduleSave();if(mode==='galaxy')scheduleRealistic();if(!['threads','duration','dt','seed','notes','t_sf','lifecycle_speed','theta','softening'].includes(s.id)||s.id==='seed')schedulePreview()});
      out.textContent=readout(s,v);unit.textContent=unitLine(s,v);row.append(lab,input,out,unit);
      if(s.kind==='choice'){const ticks=el('div','ticks');s.stops.forEach((st,i)=>ticks.append(el('span',null,(s.labels&&s.labels[i])||tickLabel(s,st))));row.append(ticks)}
      let hint=null;if(s.hint){hint=el('small','slider-hint',s.hint);row.append(hint)}
      rows[s.id]={input,out,unit,slider:s,row,hint};box.append(row)}
    $('sliders').append(box)}
  applyRealisticLocks();updateEstimate()}
function syncInputs(){for(const id in rows){const {input,out,unit,slider:s}=rows[id],v=values[mode][id];if(s.kind==='bool')input.checked=Boolean(v);else if(s.kind==='choice')input.value=Math.max(0,s.stops.indexOf(Number(v)));else input.value=v;out.textContent=readout(s,v);unit.textContent=unitLine(s,v)}applyRealisticLocks();updateEstimate()}
function markUnused(){if(mode!=='galaxy')return;const G=Number(values.galaxy.n_galaxies||1);for(const id in rows){const {out,slider:s,row}=rows[id];if(!s.galaxy)continue;const unused=G<s.galaxy;row.classList.toggle('unused',unused);out.textContent=unused?`unused below ${s.galaxy} galaxies`:readout(s,values.galaxy[s.id])}}
// ---------- Real World Physics (model revision 6) ----------
// The server chooses its numbers (softening from particle spacing, starting step from the peak acceleration) and measures
// its per-step SPH cost; /api/realistic returns them. The page only displays them and folds them into the estimate.
function draftCfg(){const c=toConfig(mode,values[mode]);if(mode==='galaxy'&&c.realistic&&realisticInfo&&!realisticInfo.error)c.realistic_info=realisticInfo;return c}
function lockText(id){const i=realisticInfo&&!realisticInfo.error?realisticInfo:null;
  return {dt:i?`adaptive, starts at ${(i.dt_initial*MYR_PER_TIME).toPrecision(2)} Myr`:'adaptive',softening:i?`${Math.round(i.softening*3000)} pc, from particle spacing`:'from particle spacing',
    t_sf:'1% of dense gas per free-fall time',lifecycle_speed:'1× (physical lifetimes)',sf_density_bias:'gas above 0.1 H/cm³',grow_rate:'not used (stellar populations)',sn_kick_kms:'supernova momentum to gas instead'}[id]||''}
function applyRealisticLocks(){
  if(mode!=='galaxy'){$('realistic-banner').classList.add('hidden');return}
  const on=!!values.galaxy.realistic;$('realistic-banner').classList.toggle('hidden',!on);
  for(const id of REALISTIC_SUPERSEDED){const r=rows[id];if(!r)continue;r.input.disabled=on;r.row.classList.toggle('locked',on);
    if(r.slider.kind==='bool')r.input.checked=on||Boolean(values.galaxy[id]);
    if(on){r.out.textContent='auto';r.unit.textContent=lockText(id)}else{r.out.textContent=readout(r.slider,values.galaxy[id]);r.unit.textContent=unitLine(r.slider,values.galaxy[id])}}}
function realisticKeyOf(c){return JSON.stringify({...c,threads:0,seed:0,duration:0,dt:0,theta:0,realistic:0})}
function scheduleRealistic(){clearTimeout(realisticTimer);if(realisticKeyOf(toConfig('galaxy',values.galaxy))===realisticKey)return;realisticTimer=setTimeout(fetchRealistic,300)}
async function fetchRealistic(){
  const c=toConfig('galaxy',values.galaxy),key=realisticKeyOf(c);
  try{const r=await api('/api/realistic',{...c,duration:1});realisticInfo=r}catch(e){realisticInfo={error:e.message}}
  realisticKey=key;if(panel==='physics')renderPhysics();if(panel==='new'){applyRealisticLocks();updateEstimate()}}
function setRealistic(on){values.galaxy.realistic=on;scheduleSave();renderPhysics();if(panel==='new'&&mode==='galaxy'){applyRealisticLocks();updateEstimate();schedulePreview()}scheduleRealistic()}
function renderPhysics(){
  const on=!!values.galaxy.realistic,i=realisticInfo&&!realisticInfo.error?realisticInfo:null;$('realistic-on').checked=on;
  $('realistic-state').textContent=on?'On: model revision 6. New galaxy runs use everything listed below.':'Off: the standard collisionless model (revision 5).';
  const box=$('physics-body');box.replaceChildren();
  if(!i&&!realisticInfo)scheduleRealistic();
  const card=(title,...kids)=>{const c=el('div','card');c.append(el('div','section-label',title),...kids);box.append(c);return c};
  const myr=v=>v==null?'—':v<1?`${v.toPrecision(2)} Myr`:v<1000?`${Math.round(v)} Myr`:`${(v/1000).toFixed(1)} Gyr`;
  const items=[
    ['Gas is a fluid that can lose energy.','Isothermal SPH at 10⁴ K (10 km/s sound speed), 32 neighbours, shock viscosity with a Balsara switch. Colliding gas shocks and radiates, so it can settle into a new disk or fall to the centre after a merger.','Standard: gas parcels pass through each other like stars, so a merger can only leave a puffed-up spheroid.'],
    ['Stars form where gas is dense.','Gas above 0.1 H/cm³ turns into stars at 1% per free-fall time, the efficiency measured in real galaxies.','Standard: one global rate set by the star-formation timescale slider.'],
    ['Each star particle is a stellar population.','It returns about 42% of its mass to gas over 10 Gyr and makes one core-collapse supernova per ~92 M☉ formed, from the same Kroupa IMF and lifetimes.','Standard: each superparticle lives and dies as a single star.'],
    ['Supernovae push gas.','Each supernova gives neighbouring gas 2.8×10⁵ M☉ km/s of outward momentum (from resolved supernova simulations). Momentum is conserved exactly.','Standard: no feedback.'],
    ['Dark-matter halos start in equilibrium.','Hernquist profile (the shape cosmological halos have), with velocities from Eddington\'s formula in the full disk + halo + black-hole potential.','Standard: Plummer halo with approximate velocities, which rings at the start.'],
    ['The timestep follows the physics.',i?`Every step keeps dt ≤ √(2ηε/|a|) (η = 0.025) for every particle and obeys the gas Courant condition, so it shrinks during close passages. This setup starts at ${myr(i.dt_initial*MYR_PER_TIME)}.`:'Every step keeps dt ≤ √(2ηε/|a|) (η = 0.025) for every particle and obeys the gas Courant condition, so it shrinks during close passages.','Standard: fixed 0.49 Myr step.'],
    ['Softening is set by particle count.',i?`${Math.round(i.softening*3000)} pc here: the mean particle spacing in the densest disk. It shrinks as you add particles.`:'The mean particle spacing in the densest disk. It shrinks as you add particles.','Standard: the softening slider (180 pc). Measured here: at 22,500 particles a disk heated faster with smaller softening, because particles scatter each other harder.']];
  const ul=el('ul','physics-list');items.forEach(([t,d,was])=>{const li=el('li');li.append(el('b',null,t+' '),document.createTextNode(d),el('span','was',was));ul.append(li)});
  card(on?'WHAT IS ON':'WHAT TURNING IT ON CHANGES',ul);
  const noise=card('PARTICLE NOISE · HOW LONG A DISK STAYS TRUSTWORTHY');
  if(realisticInfo?.error)noise.append(el('p',null,realisticInfo.error));
  else if(!i)noise.append(el('p',null,'Computing for the current settings…'));
  else{
    noise.append(el('p',null,`Every dot is a superparticle, so particles scatter off each other far more than real stars do. That noise alone thickens disks. Below is roughly how long it takes to double a disk's vertical motion (${fmt(values.galaxy.n)} particles, current settings). Results much older than this reflect particle noise more than physics. About 4× the particles gives about 4× longer, and this is measured, not assumed.`));
    const t=el('table','noise-table'),head=el('tr');['Galaxy','Disk stars','Gas','Halo','Halo particle','Real World','Standard'].forEach(h=>head.append(el('th',null,h)));t.append(head);
    i.galaxies.forEach(g=>{const r=el('tr');[`${g.id}`,fmt(g.disk),fmt(g.gas),fmt(g.halo),`${(g.halo_particle_msun/1e6).toPrecision(2)}×10⁶ M☉`,myr(g.heating_myr),myr(g.heating_standard_myr)].forEach(v=>r.append(el('td',null,v)));t.append(r)});
    noise.append(t);
    const span=Number(values.galaxy.duration)*MYR_PER_TIME;
    if(span>3*i.heating_myr)noise.append(el('p',null,`Your span is ${myr(span)}, about ${Math.round(span/i.heating_myr)}× that time. Expect disks to thicken from particle noise whatever the physics setting. For long runs, raise the particle count before anything else.`))}
  const cost=card('COST');
  cost.append(el('p',null,i?`About ${fmt(i.n_gas)} gas particles get SPH forces every step (≈${(ms=>ms<10?ms.toFixed(1):Math.round(ms))(i.hydro_seconds_per_step*1000)} ms per step on this Mac, on top of gravity). The estimate on the New tab includes this, but it is a prediction from the starting step. Close passages shorten the step, so real runs can take longer.`:'The New tab estimate includes the extra SPH and lifecycle work.'));
  card('STILL NOT INCLUDED',el('p',null,'Cooling below 10⁴ K and a multiphase ISM, magnetic fields, cosmic rays, black-hole accretion and AGN feedback, metal enrichment, cosmological gas infall. Gravity is Newtonian. The planetary mode is unchanged: it already integrates Newtonian gravity to machine precision (IAS15), without relativity.'))}

function draftConfig(){
  const cfg=toConfig(mode,values[mode]);cfg.notes=$('notes').value.trim();cfg.node=placement.node;
  if(placement.split&&placement.legs.length>1)cfg.legs=placement.legs.map((l,i)=>i<placement.legs.length-1?{node:l.node,until:l.until/100}:{node:l.node});
  else if(placement.twin&&placement.twin!==placement.node)cfg.twin=placement.twin;
  if(placement.node==='local'){cfg.standby=placement.standby||'off';cfg.return_on_wake=placement.returnOnWake!==false}
  return cfg}
const readyNodes=(except=[])=>nodes.filter(n=>n.health?.ready!==false&&!except.includes(n.id));
function fixLegs(){
  // Leg 0 is always the starting machine; consecutive legs differ; boundaries increase by at least 5%.
  let legs=placement.legs.length>1?placement.legs:[{node:placement.node,until:50},{node:readyNodes([placement.node])[0]?.id,until:100}];
  legs[0]={...legs[0],node:placement.node};
  legs=legs.filter(l=>nodes.some(n=>n.id===l.node));
  for(let i=1;i<legs.length;i++)if(legs[i].node===legs[i-1].node)legs[i].node=readyNodes([legs[i-1].node])[0]?.id;
  legs=legs.filter(l=>l.node);let prev=0;legs.forEach((l,i)=>{if(i===legs.length-1){l.until=100;return}l.until=Math.min(95-5*(legs.length-2-i),Math.max(prev+5,Number(l.until)||prev+5));prev=l.until});
  placement.legs=legs.length>1?legs:[]}
function renderPlacement(){
  const pick=$('node-picker');pick.replaceChildren();if(!nodes.some(n=>n.id===placement.node))placement.node='local';
  nodes.forEach(n=>{const b=el('button','node-choice'+(n.id===placement.node?' on':''));b.setAttribute('role','radio');b.setAttribute('aria-checked',n.id===placement.node);b.style.setProperty('--c',nodeColor(nodes,n.id));
    const ready=n.health?.ready!==false;b.disabled=!ready;b.title=!ready?(n.health?.error||n.health?.python_error||'Not ready'):n.busy?'Busy now — queue instead, or start when it frees up.':'';
    b.append(el('b',null,n.label),el('small',null,!ready?'unreachable':n.busy?'busy':n.id==='local'?`${n.cores} cores · here`:`${n.health?.cores??'?'} cores${n.speed?` · ×${Number(n.speed).toFixed(1)}`:' · unmeasured'}${n.always_on?' · always on':''}`));
    b.onclick=()=>{placement.node=n.id;scheduleSave();renderPlacement();updateEstimate()};pick.append(b)});
  $('split-on').checked=placement.split;$('split-on').disabled=nodes.length<2;
  if(placement.split)fixLegs();
  const box=$('legs');box.replaceChildren();box.classList.toggle('hidden',!placement.split);
  if(placement.split){
    placement.legs.forEach((l,i)=>{const row=el('div','leg');row.style.setProperty('--c',nodeColor(nodes,l.node));row.append(el('b',null,String(i+1)));
      const sel=el('select');nodes.forEach(n=>{const o=el('option',null,n.label);o.value=n.id;o.disabled=n.health?.ready===false||(i>0&&placement.legs[i-1].node===n.id)||(i+1<placement.legs.length&&placement.legs[i+1].node===n.id);sel.append(o)});
      sel.value=l.node;sel.disabled=i===0;sel.title=i===0?'The first leg is the machine picked above':'';sel.onchange=()=>{l.node=sel.value;scheduleSave();renderPlacement();updateEstimate()};row.append(sel);
      const until=el('label','until');if(i<placement.legs.length-1){const out=el('span',null,`until ${l.until}%`),r=el('input');r.type='range';r.min=5;r.max=95;r.step=5;r.value=l.until;r.setAttribute('aria-label',`Leg ${i+1} ends at percent of the span`);
        r.oninput=()=>{l.until=Number(r.value);fixLegs();out.textContent=`until ${l.until}%`;r.value=l.until;updateEstimate();scheduleSave()};r.onchange=()=>renderPlacement();until.append(out,r)}else until.append(el('span',null,'to the end'));row.append(until);
      const rm=el('button','secondary','✕');rm.setAttribute('aria-label',`Remove leg ${i+1}`);rm.disabled=i===0||placement.legs.length<=2;rm.onclick=()=>{placement.legs.splice(i,1);scheduleSave();renderPlacement();updateEstimate()};row.append(rm);box.append(row)});
    const add=el('button','secondary small add-leg','＋ Add machine');add.disabled=placement.legs.length>=5||readyNodes([placement.legs.at(-1).node]).length===0;
    add.onclick=()=>{const last=placement.legs.at(-1),prev=placement.legs.at(-2)?.until||0;const cut=Math.min(95,Math.round((prev+100)/2/5)*5);last.until=Math.max(prev+5,cut);placement.legs.push({node:(readyNodes(placement.legs.map(l=>l.node))[0]||readyNodes([last.node])[0])?.id,until:100});fixLegs();scheduleSave();renderPlacement();updateEstimate()};box.append(add)}
  // Standby only applies when the run starts on this Mac.
  const sf=$('standby-field');sf.classList.toggle('hidden',placement.node!=='local');
  const sbSel=$('standby-node');sbSel.replaceChildren();const auto=el('option',null,'Fastest always-on machine (auto)');auto.value='auto';sbSel.append(auto);
  nodes.filter(n=>n.id!=='local').forEach(n=>{const o=el('option',null,n.label+(n.health?.ready===false?' (unreachable)':''));o.value=n.id;o.disabled=n.health?.ready===false;sbSel.append(o)});const off=el('option',null,'Nobody — pause with the Mac');off.value='off';sbSel.append(off);
  sbSel.value=placement.standby||'auto';$('return-on-wake').checked=placement.returnOnWake!==false;
  const tw=$('twin-node');tw.replaceChildren();const none=el('option',null,'No twin');none.value='';tw.append(none);
  nodes.filter(n=>n.id!==placement.node).forEach(n=>{const o=el('option',null,n.label+(n.health?.ready===false?' (unreachable)':n.busy?' (busy)':''));o.value=n.id;o.disabled=n.health?.ready===false||n.busy;tw.append(o)});
  tw.value=placement.twin&&placement.twin!==placement.node?placement.twin:'';tw.disabled=placement.split;tw.title=placement.split?'Twin runs use one machine each; turn off the split.':''}
function updateEstimate(){
  if(!rows.duration)return;const cfg=draftCfg(),first=nodeById(placement.node);
  const cap=durationCap({...cfg,threads:nodeThreads(cfg,first)});
  if(rows.duration.slider.kind!=='choice'){const capAdj=Math.max(1,Math.floor(cap/(first.speed||1)));rows.duration.input.max=mode==='galaxy'?Math.min(1200,capAdj):50;if(Number(values[mode].duration)>rows.duration.input.max){values[mode].duration=Number(rows.duration.input.max);rows.duration.input.value=values[mode].duration;rows.duration.out.textContent=readout(rows.duration.slider,values[mode].duration);rows.duration.unit.textContent=unitLine(rows.duration.slider,values[mode].duration)}
    if(rows.duration.hint&&mode==='galaxy')rows.duration.hint.textContent=`Live max ${fmt(rows.duration.input.max)} model units (${Math.round(rows.duration.input.max*MYR_PER_TIME).toLocaleString('en-US')} Myr) on ${first.label} from the 120 h estimate.`}
  const c2=draftCfg(),split=placement.split&&placement.legs.length>1;
  const legs=split?placement.legs.map((l,i)=>({n:nodeById(l.node),f:(l.until-(i?placement.legs[i-1].until:0))/100})):[{n:first,f:1}];
  legs.forEach(l=>l.s=l.f*nodeEstimate(c2,l.n));const total=legs.reduce((x,l)=>x+l.s,0);
  const twin=!split&&placement.twin?nodeById(placement.twin):null,twinS=twin?nodeEstimate(c2,twin):0,over=total>WALL_CAP_HOURS*3600||twinS>WALL_CAP_HOURS*3600;
  $('estimate-time').textContent=`${fmtHours(total/3600)} estimated wall`;
  $('estimate-kind').textContent=(split?legs.map(l=>`${l.n.label} ${fmtHours(l.s/3600)}`).join(' → '):`on ${first.label}`)+(twin?` · twin on ${twin.label} ${fmtHours(twinS/3600)}`:'')+' · prediction'+(legs.some(l=>l.n.id!=='local'&&!l.n.speed)?' (a machine is unmeasured — Benchmark it)':'');
  const span=mode==='galaxy'?`${Math.round(c2.duration*MYR_PER_TIME).toLocaleString('en-US')} Myr`:`${c2.duration} yr`,ng=mode==='galaxy'?Number(c2.n_galaxies||1):1;
  const passage=mode==='galaxy'&&ng>1&&c2.g2_vrel?` · first passage ~${Math.round(c2.g2_sep/c2.g2_vrel*MYR_PER_TIME)} Myr`:'';
  $('estimate-detail').textContent=over?`Exceeds the ${WALL_CAP_HOURS} h cap on these machines. Lower N, shorten the span, or pick faster machines.`:`${span} · ${mode==='galaxy'?`${fmt(c2.n)} particles${ng>1?` in ${ng} galaxies`:''} · ${legs.map(l=>nodeThreads(c2,l.n)).join(' → ')} threads · ${c2.realistic_info?`~${fmt(Math.round(c2.duration/c2.realistic_info.dt_initial))} adaptive steps or more (Real World Physics)`:c2.realistic?'Real World Physics (measuring…)':`${fmt(Math.round(c2.duration/c2.dt))} leapfrog steps`}${passage}`:`${c2.perturber_mass>0?10:9} bodies`} · engine ~${engineRamGb(c2).toFixed(2)} GB RAM. θ and softening are not in the timing model.`;
  $('estimate').classList.toggle('over',over);
  const bar=$('split-bar');bar.replaceChildren();
  legs.forEach(l=>{const d=el('span',null);d.style.flex=`${l.f} 1 0`;d.style.setProperty('--c',nodeColor(nodes,l.n.id));d.title=`${l.n.label}: ${fmtHours(l.s/3600)}`;d.append(el('b',null,l.n.label),el('small',null,fmtHours(l.s/3600)));bar.append(d)});
  markUnused();
  const firstBusy=first.busy||twin?.busy,full=jobs.length+(twin?2:1)>(system.max_runs||24),blocked=queue.enabled&&queueNodes().has(first.id),busyStart=$('start-compute').dataset.busy==='1';
  $('start-compute').disabled=over||firstBusy||full||blocked||busyStart||first.health?.ready===false;
  $('start-compute').textContent=full?`Remove a run first (${jobs.length}/${system.max_runs||24})`:busyStart?'Starting…':first.busy?`${first.label} is busy`:twin?.busy?`${twin.label} is busy`:split?`Start: ${legs.map(l=>l.n.label).join(' → ')}`:twin?`Start twins: ${first.label} + ${twin.label}`:`Start on ${first.label}`;
  $('add-queue').disabled=over||full||!!twin||$('add-queue').dataset.busy==='1';$('add-queue').title=twin?'Twin runs start directly.':''}
function queueNodes(){return new Set([queue.current,...(queue.ids||[])].filter(Boolean).map(id=>locOf(jobs.find(j=>j.id===id)).node))}

// ---------- nodes ----------
function renderNodeStrip(){
  const strip=$('node-strip');strip.replaceChildren();
  nodes.forEach(n=>{const run=jobs.find(j=>locOf(j).node===n.id&&ACTIVE.includes(j.status.phase));const b=el('button','node-chip');b.style.setProperty('--c',nodeColor(nodes,n.id));
    const state=n.health?.reachable===false?'down':run?'busy':'idle';b.dataset.state=state;b.append(el('i'),el('span',null,n.label),el('small',null,state==='down'?'unreachable':run?`${Math.round((run.status.progress||0)*100)}%`:'idle'));
    b.title=run?`${runTitle(run)} — click to open`:n.health?.error||'Open compute nodes';b.onclick=()=>run?select(run.id):setPanel('nodes');strip.append(b)})}
function renderNodes(){
  const box=$('node-cards');box.replaceChildren();
  nodes.forEach(n=>{const h=n.health||{},card=el('div','card node-card');card.style.setProperty('--c',nodeColor(nodes,n.id));
    const head=el('div','node-head');head.append(el('i','ndot'),el('b',null,n.label),el('span','status-pill',n.id==='local'?'hub':h.reachable===false?'unreachable':h.ready?'ready':h.checked_at?'not ready':'checking…'));head.querySelector('.ndot').style.setProperty('--c',nodeColor(nodes,n.id));card.append(head);
    const dl=el('dl','node-facts');
    if(n.id==='local'){dd(dl,'Cores',`${n.cores} (${n.performance_cores} performance)`);dd(dl,'Role','Hub: library, frames, viewer; computes when awake');dd(dl,'Speed','reference estimator')}
    else{dd(dl,'SSH',n.host);dd(dl,'Cores / arch',`${h.cores??'—'} · ${h.arch||'—'}`);dd(dl,'Load / free RAM',`${h.load??'—'} · ${h.mem_mb!=null?(h.mem_mb/1024).toFixed(1)+' GB':'—'}`);dd(dl,'Free disk',h.disk_kb!=null?`${(h.disk_kb/1048576).toFixed(0)} GB`:'—');dd(dl,'Python / REBOUND',`${h.python||'—'} · ${h.rebound||'—'}`);
      dd(dl,'Speed vs Mac estimator',n.speed?`×${Number(n.speed).toFixed(2)} (slower is larger)`:'unmeasured',n.speed_source||'Run Benchmark to measure');dd(dl,'Checked',h.checked_at?fmtAgo(Date.now()/1000-h.checked_at):'—')}
    card.append(dl);
    if(h.error||h.python_error||h.warning)card.append(el('p','micro warn',h.error||h.python_error||h.warning));
    if(n.benchmark)card.append(el('p','micro',`Benchmark: ${n.benchmark}`));
    if(n.id!=='local'&&h.reachable===false){const f=el('form','node-pw');
      const pw=el('input');pw.type='password';pw.autocomplete='current-password';pw.placeholder=`Password for ${n.host}`;pw.setAttribute('aria-label',`SSH password for ${n.host}`);
      const go=el('button','small','Connect');go.type='submit';
      f.title='Used once to install this Mac\'s SSH key on the node, then discarded. It is never saved.';
      f.onsubmit=async e=>{e.preventDefault();if(!pw.value)return pw.focus();go.disabled=true;go.textContent='Connecting…';
        try{const r=await api(`/api/nodes/${n.id}/install-key`,{password:pw.value});pw.value='';toast(r.reachable?`Key installed on ${n.label}; connected.`:`Key installed, but probe failed: ${r.error||''}`);await pollNodes()}
        catch(err){pw.value='';toast(err.message);go.disabled=false;go.textContent='Connect'}};
      f.append(pw,go);card.append(f,el('p','micro','Password is used once to install this Mac\'s key, then discarded — never saved.'))}
    if(n.id!=='local'){const act=el('div','row-actions');
      const probe=el('button','secondary small','Probe');probe.onclick=async()=>{probe.disabled=true;try{await api(`/api/nodes/${n.id}/probe`,{});await pollNodes()}catch(e){toast(e.message)}finally{probe.disabled=false}};
      const bench=el('button','secondary small',n.benchmark==='running'?'Benchmarking…':'Benchmark');bench.disabled=n.benchmark==='running'||n.busy||!h.ready;bench.title='~1 min: 100,000 particles, 2 galaxies, 3 steps on all node cores. Updates the speed factor.';bench.onclick=async()=>{try{await api(`/api/nodes/${n.id}/benchmark`,{});toast(`Benchmarking ${n.label}…`);await pollNodes()}catch(e){toast(e.message)}};
      const edit=el('button','secondary small','Edit');edit.onclick=()=>fillNodeForm(n);
      const rm=el('button','secondary small','Remove');rm.onclick=async()=>{if(!confirm(`Remove node ${n.label} from this Mac's list? Nothing on the node is deleted.`))return;try{await api(`/api/nodes/${n.id}`,undefined,'DELETE');await pollNodes()}catch(e){toast(e.message)}};
      act.append(probe,bench,edit,rm);card.append(act)}
    box.append(card)})}
function fillNodeForm(n){$('node-form-card').open=true;$('node-form-title').textContent=n?`EDIT ${n.label.toUpperCase()}`:'ADD A NODE';$('nf-id').value=n?.id||'';$('nf-id').readOnly=!!n;$('nf-label').value=n?.label||'';$('nf-host').value=n?.host||'';$('nf-root').value=n?.root||'~/open-orbital';$('nf-python').value=n?.python||'work/venv/bin/python';$('nf-pythonpath').value=n?.pythonpath||'work/openmp';$('nf-always').checked=n?.always_on!==false;$('nf-host').focus()}

// ---------- panel + mode ----------
function setPanel(next){
  if(panel!==next)document.querySelector('.panel').scrollTop=0;
  panel=next;['run','new','physics','nodes'].forEach(p=>{$(`view-${p}`).classList.toggle('hidden',p!==panel);$(`tab-${p}`).setAttribute('aria-selected',p===panel)});
  document.body.dataset.panel=panel;
  if(panel==='new'){renderSliders();renderPlacement();refreshStage(true)}
  else if(panel==='run'){renderRun();refreshStage()}
  else if(panel==='physics'){renderPhysics();refreshStage()}
  else{renderNodes();pollNodes()}
  renderRuns()}
function syncModeTabs(){$('galaxy-tab').classList.toggle('active',mode==='galaxy');$('planets-tab').classList.toggle('active',mode==='planets')}
function setMode(next){mode=next;syncModeTabs();if(panel==='new'){renderSliders();refreshStage(true)}else{const j=selected();if(!j||j.config.mode!==mode){const pick=jobs.find(x=>x.config.mode===mode);selectedId=pick?.id||null;full=null;renderRun();refreshStage(true)}}renderRuns()}
function syncLayers(){viewer?.setLayers({disk:$('show-disk').checked,halo:$('show-halo').checked,orbits:$('show-orbits').checked,labels:$('show-labels').checked,colorMode:$('color-mode').value});syncLegend()}
function syncLegend(){const j=panel==='new'?null:(full?.id===selectedId?full:selected());const g=stageMode()==='galaxy',cm=$('color-mode').value;const real=panel==='new'?!!values.galaxy.realistic:!!(j?.meta?.realistic||j?.config?.realistic);const lg=$('stage-legend').children;
  if(lg.length>=8){lg[1].textContent=real?'Young stars (<10 Myr)':'Protostar';lg[2].textContent=real?'Stellar population':'Main sequence';for(const k of [3,4,5,6])lg[k].classList.toggle('hidden',real)}
  $('stage-legend').classList.toggle('hidden',!(g&&(panel==='new'?values.galaxy.lifecycle_enabled:j?.meta?.lifecycle_enabled)&&cm==='component'));$('galaxy-legend').classList.toggle('hidden',!(g&&cm==='galaxy'))}

// ---------- star inspector ----------
// Click a body on the stage → its row from every saved frame (GET /api/jobs/:id/track), appended as new frames are computed.
// Live values are the saved frame under the playhead, never the display interpolation. Preview picks have no track.
const STAGES_REAL=['Gas','Young stellar population (<10 Myr)','Stellar population'];
const STAGES=['Gas','Protostar','Main sequence','Giant','White dwarf','Neutron star','Black hole','Dark-matter halo','Central black hole'];
const BODY_NAMES=['Sun','Mercury','Venus','Earth–Moon','Mars','Jupiter','Saturn','Uranus','Neptune','Perturber'];
let insp={idx:null,data:null,runId:null,loading:false,liveKey:''};
function openInspector(i){
  insp={idx:i,data:null,runId:viewer?.previewing?null:viewer?.job?.id||null,loading:false,liveKey:''};
  viewer?.select(i);viewer?.setFollow($('insp-follow').checked);$('inspector').classList.remove('hidden');renderInspector();
  if(insp.runId)fetchTrack()}
function closeInspector(fromViewer){
  insp={idx:null,data:null,runId:null,loading:false,liveKey:''};if(!fromViewer)viewer?.select(null);$('insp-follow').checked=false;$('inspector').classList.add('hidden')}
async function fetchTrack(){
  const {idx,runId}=insp;if(idx==null||!runId||insp.loading)return;const have=insp.data?.points.length||0;insp.loading=true;
  try{const d=await api(`/api/jobs/${runId}/track?index=${idx}&start=${have}`);if(insp.idx!==idx||insp.runId!==runId)return;
    if(d.frames<have){insp.data=null;insp.loading=false;return fetchTrack()}   // a resume rewound uncommitted frames: reload the track
    insp.data=have&&insp.data?{...d,points:insp.data.points.concat(d.points)}:d;viewer?.setTrack(insp.data.points);renderInspector()}
  catch(e){if(insp.idx===idx)$('insp-note').textContent=e.message}
  finally{if(insp.idx===idx)insp.loading=false}}
function refreshInspector(){const j=selected();if(insp.idx==null||!insp.runId||!j||j.id!==insp.runId)return;if((j.status.frames||0)!==(insp.data?.points.length??-1))fetchTrack()}
function inspU(){
  const u=insp.data?.units||{},m=viewer?.job?.meta||{};
  if(stageMode()==='planets')return {pl:true,L:1,lu:'AU',V:4.7406,T:1,tu:'yr',M:1};
  return {pl:false,L:u.length_scale??m.length_scale??3,lu:'kpc',V:u.velocity_kms??m.velocity_unit_kms??119.7,T:u.time_scale??m.time_scale??MYR_PER_TIME,tu:'Myr',M:u.mass_solar??m.mass_unit_solar??1e10}}
const timeTxt=(t,U)=>{const v=t*U.T;return U.pl?v.toFixed(2):v<100?v.toFixed(1):fmt(Math.round(v))};
const speedTxt=(v,U)=>v==null?'—':`${U.pl?fmtNum(v*U.V):fmt(Math.round(v*U.V))} km/s`;
const lenTxt=(v,U)=>v==null?'—':`${fmtNum(v*U.L)} ${U.lu}`;
function sci(v){if(!v)return '0';const e=Math.floor(Math.log10(Math.abs(v))),sup=String(e).replace(/./g,c=>c==='-'?'⁻':'⁰¹²³⁴⁵⁶⁷⁸⁹'[c]);return `${(v/10**e).toFixed(2)}×10${sup}`}
const massTxt=(v,U)=>v==null?'—':U.pl?`${fmtNum(v*332946)} M⊕`:`${sci(v*U.M)} M☉`;
function drawInsp(id,vals,at,color,marks=[]){
  const svg=$(id);svg.replaceChildren();const nums=vals.filter(v=>v!=null&&isFinite(v));if(nums.length<2){drawSpark(id,[],color);return}
  const w=320,h=64,pad=5,lo=Math.min(...nums),hi=Math.max(...nums),span=hi-lo||1,X=i=>pad+i*(w-2*pad)/Math.max(vals.length-1,1),Y=v=>h-pad-(v-lo)/span*(h-2*pad);
  const mk=(tag,attrs)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const k in attrs)e.setAttribute(k,attrs[k]);svg.append(e)};
  let d='',pen=false;vals.forEach((v,i)=>{if(v==null||!isFinite(v)){pen=false;return}d+=`${pen?'L':'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`;pen=true});
  mk('path',{d,fill:'none',stroke:color,'stroke-width':1.5,'stroke-linejoin':'round'});
  marks.forEach(i=>mk('line',{x1:X(i),x2:X(i),y1:pad,y2:h-pad,stroke:'#e0b07a','stroke-width':1,'stroke-dasharray':'2 3'}));   // stage changes
  if(at!=null&&at<vals.length)mk('line',{x1:X(at),x2:X(at),y1:0,y2:h,stroke:'#e2e8ed','stroke-width':1,opacity:.55})}   // playhead
function renderInspector(){
  if(insp.idx==null)return;const U=inspU(),d=insp.data,P=d?.points||[],pv=viewer?.previewing,lifecycle=!!viewer?.job?.meta?.lifecycle_enabled;
  if(U.pl){$('insp-kind').textContent=pv?'PREVIEW · J2000 INITIAL CONDITIONS':'PLANETARY BODY';$('insp-title').textContent=d?.name||BODY_NAMES[insp.idx]||`Body ${insp.idx}`}
  else{$('insp-title').textContent=`${pv?'Sample particle':'Particle'} #${fmt(insp.idx)}`;$('insp-kind').textContent=pv?'PREVIEW · INITIAL CONDITIONS':d?`${d.galaxies>1?`GALAXY ${d.galaxy} · `:''}${d.component.toUpperCase()}`:'LOADING TRACK…'}
  $('insp-r-label').textContent=U.pl?'Distance from the Sun':'Distance from its galaxy centre';
  $('insp-hist').classList.toggle('hidden',!!pv);
  const sum=$('insp-summary'),ev=$('insp-events');sum.replaceChildren();ev.replaceChildren();
  if(!pv){
    $('insp-count').textContent=d?`${fmt(P.length)} frame${P.length===1?'':'s'}`:'loading…';
    if(P.length){
      const rs=P.map(p=>p.r),vs=P.map(p=>p.speed),hs=P.map(p=>p.height).filter(v=>v!=null),tt=p=>p.t==null?'—':`${timeTxt(p.t,U)} ${U.tu}`;
      const argOf=(arr,f)=>arr.reduce((b,v,i)=>v!=null&&(b<0||f(v,arr[b]))?i:b,-1),iMin=argOf(rs,(a,b)=>a<b),iMax=argOf(rs,(a,b)=>a>b),iV=argOf(vs,(a,b)=>a>b);
      let path=0;for(let i=1;i<P.length;i++)path+=Math.hypot(P[i].x-P[i-1].x,P[i].y-P[i-1].y,P[i].z-P[i-1].z);
      dd(sum,U.pl?'Closest to the Sun':'Closest to centre',iMin<0?'—':`${lenTxt(rs[iMin],U)} · ${tt(P[iMin])}`);dd(sum,U.pl?'Farthest from the Sun':'Farthest from centre',iMax<0?'—':`${lenTxt(rs[iMax],U)} · ${tt(P[iMax])}`);
      dd(sum,'Top speed',iV<0?'—':`${speedTxt(vs[iV],U)} · ${tt(P[iV])}`);
      dd(sum,U.pl?'Max height off the ecliptic':'Max height off its disk',hs.length?lenTxt(Math.max(...hs.map(Math.abs)),U):U.pl?'—':'disk plane not defined');
      dd(sum,'Path through saved frames',`${lenTxt(path,U)} (lower bound)`);
      if(d.galaxies>1){const away=P.filter(p=>p.nearest!==d.galaxy).length;dd(sum,'Frames nearer another galaxy',`${fmt(away)} of ${fmt(P.length)}`)}
      const marks=[];
      for(let i=1;i<P.length;i++)if(P[i].type!=null&&P[i].type!==P[i-1].type){marks.push(i);ev.append(el('li',null,`${tt(P[i])} · ${STAGES[P[i-1].type]||P[i-1].type} → ${STAGES[P[i].type]||P[i].type}`))}
      if(d.galaxies>1){const k=P.findIndex(p=>p.nearest!==d.galaxy);if(k>=0)ev.append(el('li',null,`${tt(P[k])} · first nearer Galaxy ${P[k].nearest}'s centre than its own`));const last=P.at(-1);if(last.nearest!==d.galaxy)ev.append(el('li',null,`Latest frame · nearest Galaxy ${last.nearest} (${lenTxt(last.nearest_r,U)} from its centre)`))}
      if(!ev.children.length)ev.append(el('li',null,lifecycle||U.pl?'No stage changes in the saved frames.':'Lifecycle off: stage stays fixed.'));
      insp.marks=marks;
      const vmin=Math.min(...vs),vmax=Math.max(...vs);$('insp-r-range').textContent=iMin<0?'':`${fmtNum(rs[iMin]*U.L)}–${fmtNum(rs[iMax]*U.L)} ${U.lu}`;$('insp-v-range').textContent=`${fmt(Math.round(vmin*U.V))}–${fmt(Math.round(vmax*U.V))} km/s`}
    else{insp.marks=[];drawSpark('insp-chart-r',[],'#9fc6b1');drawSpark('insp-chart-v',[],'#8bb4d9');$('insp-r-range').textContent='';$('insp-v-range').textContent=''}}
  const method=d?.center_method==='black hole'?'its central black hole':'a density centre of 1,024 sampled disk particles (an estimate that loses meaning once galaxies merge)';
  $('insp-note').textContent=pv?(U.pl?'Initial conditions only. Nothing is integrated in the preview, so there is no track; start the run to record one.':'One of 8,000 sampled initial-condition particles. Nothing is integrated in the preview and it is not a particle of a saved run, so there is no track.')
    :U.pl?'Distances and heights are measured from the Sun, with heights relative to the J2000 ecliptic. The track has one point per saved frame.'
    :`Each dot is a superparticle standing for many stars, not a single star. Its stage is the lifecycle clock of that slot. Speed is in the simulation's centre-of-mass frame. The galaxy centre is ${method}. The disk plane is fitted to the same particles and shows as undefined once the disk stops being flat. The track has one point per saved frame; the motion between frames was not recorded.`;
  insp.liveKey='';renderLive()}
function renderLive(){
  if(insp.idx==null||!viewer)return;const f=viewer.playFrame,P=insp.data?.points||[],pv=viewer.previewing,key=`${insp.idx}:${pv?'p':f}:${P.length}`;if(key===insp.liveKey)return;insp.liveKey=key;
  const U=inspU(),pt=!pv&&P[f]?.frame===f?P[f]:null,s=pt||viewer.sample(insp.idx),dl=$('insp-now');dl.replaceChildren();
  const frames=viewer.job?.status?.frames||0,t=pt?.t;
  $('insp-when').textContent=pv?'Initial conditions':`Frame ${fmt(f)} of ${fmt(Math.max(0,frames-1))}${t!=null?` · ${timeTxt(t,U)} ${U.tu}`:''}. Values come from that saved frame; the ring glides between frames for display only.${f<frames-1?` Latest computed: frame ${fmt(frames-1)}.`:''}`;
  if(!s){dd(dl,'Waiting','Loading this frame…');return}
  const wide=(label,value)=>{dd(dl,label,value);dl.lastChild.className='wide'};
  if(U.pl){const r=pt?.r??(s.sun?Math.hypot(s.x-s.sun[0],s.y-s.sun[1],s.z-s.sun[2]):null),z=pt?.height??(s.sun?s.z-s.sun[2]:null);
    dd(dl,'Distance from Sun',insp.idx===0?'—':lenTxt(r,U));dd(dl,'Speed',speedTxt(s.speed,U));dd(dl,'Height off ecliptic',insp.idx===0?'—':lenTxt(z,U));dd(dl,'Mass',massTxt(s.mass,U))}
  else{const staged=pv||!!viewer.job?.meta?.lifecycle_enabled,real=pv?!!values.galaxy.realistic:!!viewer.job?.meta?.realistic,type=staged&&s.type!=null?(real&&s.type<3?STAGES_REAL[s.type]:STAGES[s.type])||`type ${s.type}`:(insp.data?.component||'—');   // lifecycle off: type column is only a disk/halo tag
    dd(dl,staged?'Stage':'Component',type);dd(dl,'Speed',speedTxt(s.speed,U));
    if(!pv){dd(dl,'From its centre',lenTxt(pt?.r,U));dd(dl,'Off its disk',pt?pt.height==null?'plane undefined':lenTxt(pt.height,U):'—');
      if(insp.data?.galaxies>1)dd(dl,'Nearest galaxy',pt?`Galaxy ${pt.nearest} · ${lenTxt(pt.nearest_r,U)}`:'—')}
    if(!pv)dd(dl,'Superparticle mass',massTxt(s.mass,U))}   // preview particles carry N/8,000 times the run's mass
  wide('Position (x, y, z)',`${[s.x,s.y,s.z].map(v=>fmtNum(v*U.L)).join(', ')} ${U.lu}`);
  if(P.length&&!pv){drawInsp('insp-chart-r',P.map(p=>p.r),f,'#9fc6b1',insp.marks);drawInsp('insp-chart-v',P.map(p=>p.speed),f,'#8bb4d9',insp.marks)}}
$('insp-close').onclick=()=>closeInspector(false);$('insp-follow').onchange=e=>viewer?.setFollow(e.target.checked);$('insp-focus').onclick=()=>viewer?.focusSelected();
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&insp.idx!=null&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName))closeInspector(false)});

// ---------- polling ----------
async function pollNodes(){try{nodes=(await api('/api/nodes')).nodes||[];renderNodeStrip();if(panel==='nodes'&&![...document.querySelectorAll('.node-pw input')].some(i=>i.value||i===document.activeElement))renderNodes();if(panel==='new'){renderPlacement();updateEstimate()}}catch(e){}}
async function poll(force){
  if(polling||(document.hidden&&!force))return;polling=true;
  try{const [js,q,sys]=await Promise.all([api('/api/jobs?view=summary'),api('/api/queue'),api('/api/system')]);jobs=js;queue=q;system=sys||{};
    if(selectedId&&!selected()){selectedId=null;full=null}
    if(!selectedId&&panel==='run'){const pick=jobs.find(j=>ACTIVE.includes(j.status.phase))||jobs.find(j=>j.config.mode===mode);if(pick){selectedId=pick.id;if(pick.config.mode!==mode){mode=pick.config.mode;syncModeTabs()}}}
    renderRuns();renderQueue();renderNodeStrip();
    if(panel==='run'){renderRun();await refreshStage();await refreshHistory();refreshInspector();if(logOpen)await refreshLog()}else if(panel==='new')updateEstimate();
  }catch(e){$('stage-phase').textContent='Server unavailable';$('render-state').textContent='Server unavailable — restart with Start Open Orbital.'}
  finally{polling=false}}
function pollDelay(){const j=selected();if(j&&(j.status.pause_pending||j.status.phase==='pausing'||moving(j)))return 500;if(jobs.some(j=>ACTIVE.includes(j.status.phase)))return 1200;return 2500}
function schedule(){clearTimeout(pollTimer);pollTimer=setTimeout(async()=>{await poll();if(!document.hidden)schedule()},pollDelay())}
let nodeTimer=setInterval(()=>{if(!document.hidden)pollNodes()},6000);
document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(pollTimer);viewer?.setActive(false)}else{viewer?.setActive(true);schedule();poll();pollNodes()}});

// ---------- queue ----------
function renderQueue(){
  $('queue-message').textContent=(queue.enabled?'Enabled. ':'Held. ')+(queue.message||'');$('queue-badge').textContent=(queue.ids?.length||0)+(queue.current?1:0);
  $('start-queue').disabled=queue.enabled||(!queue.ids?.length&&!queue.current);$('hold-queue').disabled=!queue.enabled;
  const list=$('queue-list');list.replaceChildren();
  if(queue.current){const cur=jobs.find(x=>x.id===queue.current);list.append(el('li','queue-item current',cur?`Current: ${phaseLabel(cur.status)} · ${label(locOf(cur).node)}`:`Current: ${queue.current}`))}
  (queue.ids||[]).forEach((id,i)=>{const j=jobs.find(x=>x.id===id);if(!j)return;const li=el('li','queue-item');const t=el('span');t.append(nodeDot(locOf(j).node),document.createTextNode(` ${runTitle(j)}`));li.append(t);
    const act=el('div','row-actions');[['↑','up',i===0],['↓','down',i===queue.ids.length-1]].forEach(([txt,a,dis])=>{const b=el('button','secondary small',txt);b.disabled=dis;b.setAttribute('aria-label',a==='up'?'Move up':'Move down');b.onclick=()=>changeQueue(a,id);act.append(b)});
    const rm=el('button','secondary small','✕');rm.setAttribute('aria-label','Remove from queue');rm.onclick=()=>removeRun(j);act.append(rm);li.append(act);list.append(li)});
  if(!queue.ids?.length&&!queue.current)list.append(el('li','queue-item is-empty','No waiting experiments.'))}
async function changeQueue(action,id){try{await api('/api/queue',{action,id});await poll()}catch(e){toast(e.message)}}
async function removeRun(j){const lines=[`Remove experiment ${j.id}?`,`${runTitle(j)} · ${phaseLabel(j.status)} · ${label(locOf(j).node)}`,'This deletes frames and checkpoints on disk'+(locOf(j).node!=='local'?`, here and on ${label(locOf(j).node)}.`:'.')];if(!confirm(lines.join('\n')))return;try{await api(`/api/jobs/${j.id}`,undefined,'DELETE');if(selectedId===j.id){selectedId=null;full=null;viewer?.clear()}toast(`Removed ${j.id}.`);await poll(true)}catch(e){toast(e.message)}}

// ---------- wiring ----------
$('galaxy-tab').onclick=()=>setMode('galaxy');$('planets-tab').onclick=()=>setMode('planets');
$('tab-run').onclick=()=>setPanel('run');$('tab-new').onclick=()=>setPanel('new');$('tab-nodes').onclick=()=>setPanel('nodes');$('tab-physics').onclick=()=>setPanel('physics');$('realistic-on').onchange=e=>setRealistic(e.target.checked);$('open-physics').onclick=()=>setPanel('physics');$('new-run').onclick=()=>setPanel('new');
$('reset-defaults').onclick=()=>{values[mode]=defaultsFor(mode);syncInputs();scheduleSave();schedulePreview(true);toast('Sliders reset to defaults.')};
$('split-on').onchange=e=>{placement.split=e.target.checked;if(placement.split)placement.twin='';renderPlacement();updateEstimate();scheduleSave()};
$('standby-node').onchange=e=>{placement.standby=e.target.value;scheduleSave()};$('return-on-wake').onchange=e=>{placement.returnOnWake=e.target.checked;scheduleSave()};
$('twin-node').onchange=e=>{placement.twin=e.target.value;updateEstimate();scheduleSave()};
async function submit(button,path,okText){button.dataset.busy='1';button.disabled=true;try{const j=await api(path,draftConfig());toast(okText);if(!jobs.some(x=>x.id===j.id))jobs.unshift(j);if(path==='/api/jobs')select(j.id);await poll(true)}catch(e){toast(e.message)}finally{button.dataset.busy='0';updateEstimate()}}
$('start-compute').onclick=()=>submit($('start-compute'),'/api/jobs','Computation started. Frames appear on the stage as they are computed.');
$('add-queue').onclick=()=>submit($('add-queue'),'/api/queue/jobs','Experiment added to the queue.');
$('stop-compute').onclick=async()=>{const j=selected();if(!j)return;const s=j.status,cancel=s.pause_pending&&!['paused','interrupted'].includes(s.phase),resume=['paused','interrupted'].includes(s.phase);
  try{const r=await api(`/api/jobs/${j.id}/control`,{action:resume||cancel?'run':'pause'});if(r.status){j.status={...j.status,...r.status};armPauseEta(r.status);renderRun()}await poll(true);toast(resume?`Resume sent to ${label(locOf(j).node)}.`:cancel?'Pause cancelled.':'Stop requested. The integrator checks about four times a second, then writes a checkpoint.');await poll()}catch(e){toast(e.message)}};
async function saveRunStandby(){const j=selected();if(!j)return;try{await api(`/api/jobs/${j.id}/standby`,{node:$('run-standby').value||null,return_on_wake:$('run-return').checked});toast($('run-standby').value?`Standby set: ${label($('run-standby').value)} picks this run up if the Mac goes quiet.`:'Standby off: this run pauses when the Mac sleeps.');await poll(true)}catch(e){toast(e.message)}}
$('run-standby').onchange=saveRunStandby;$('run-return').onchange=saveRunStandby;
$('remove-run').onclick=()=>{const j=selected();if(j)removeRun(j)};
$('move-run').onclick=async()=>{const j=selected(),to=$('move-target').value;if(!j||!to)return;if(!confirm(`Hand off ${j.id} to ${label(to)}?\nIt pauses at the next leapfrog check, writes a checkpoint, moves it, then resumes there.`))return;try{await api(`/api/jobs/${j.id}/move`,{node:to});toast(`Handing off to ${label(to)}…`);await poll(true)}catch(e){toast(e.message)}};
$('show-log').onclick=async()=>{logOpen=!logOpen;$('worker-log').classList.toggle('hidden',!logOpen);$('show-log').textContent=logOpen?'Hide worker log':'Show worker log';if(logOpen)await refreshLog()};
$('node-form').onsubmit=async e=>{e.preventDefault();try{const n=await api('/api/nodes',{id:$('nf-id').value.trim(),label:$('nf-label').value.trim(),host:$('nf-host').value.trim(),root:$('nf-root').value.trim(),python:$('nf-python').value.trim(),pythonpath:$('nf-pythonpath').value.trim(),always_on:$('nf-always').checked});toast(`Saved ${n.label}. Probing…`);fillNodeForm(null);$('node-form-card').open=false;await api(`/api/nodes/${n.id}/probe`,{}).catch(err=>toast(err.message));await pollNodes()}catch(err){toast(err.message)}};
$('nf-cancel').onclick=()=>fillNodeForm(null);
$('play').onclick=()=>{if(!viewer)return;viewer.setPlaying(!viewer.playing);updatePlay()};function updatePlay(){const p=viewer?.playing??true;$('play').textContent=p?'Ⅱ':'▶';$('play').setAttribute('aria-label',p?'Pause playback':'Play playback');$('playback-label').textContent=p?'PLAYBACK':'PLAYBACK PAUSED'}
$('timeline').oninput=e=>{viewer?.seek(Number(e.target.value));updatePlay()};$('speed').onchange=e=>viewer?.setRate(Number(e.target.value));
$('reset-view').onclick=()=>viewer?.home();$('inner-view').onclick=()=>viewer?.home('inner');$('top-view').onclick=()=>viewer?.home('top');$('side-view').onclick=()=>viewer?.home('side');
['show-disk','show-halo','show-orbits','show-labels','color-mode'].forEach(id=>$(id).onchange=syncLayers);$('render-on').onchange=e=>setRender(e.target.checked);$('full-detail').onchange=e=>viewer?.setFullDetail(e.target.checked);
setInterval(renderPauseEta,250);

// Old bookmarks: /lab and /compute open the composer; /observe opens the run view.
loadDraft();$('notes').value='';
const start=location.pathname.replace(/\/$/,'');document.body.dataset.panel=panel;
await pollNodes();await poll(true);setPanel(['/lab','/compute'].includes(start)?'new':'run');schedule();
