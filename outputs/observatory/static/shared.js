// AGENT MAP: schema + helpers shared by the Compute page (lab.js) and the Observe page (app.js).
// Must never import three or touch WebGL. Bounds mirror SCHEMA in server.py; the server is the authority.
export const WALL_CAP_HOURS=120,REFERENCE_SECONDS=157.84,MYR_PER_TIME=24.5;
export const PROTECTED_IDS=['0e45a855ba11','44c528079f88','ff56d195ce89','58ab7c268cdd'];
const myr=v=>`${Math.round(v*MYR_PER_TIME).toLocaleString('en-US')} Myr`;
const kpc=v=>`${(v*3).toFixed(2)} kpc`;
const msun10=v=>`${(v*10).toFixed(2)}×10⁹ M☉`;
const kms=v=>`${(v*119.7).toFixed(0)} km/s`;
const CLONE_AZIMUTH={2:0,3:120,4:240,5:180};
function cloneSliders(i){return [
  {id:`g${i}_mass_ratio`,group:`Galaxy ${i}`,galaxy:i,label:'Mass vs Galaxy A',min:.1,max:3,step:.05,default:1,unit:'× A',hint:'Scales disk, halo and central black hole mass relative to Galaxy A.'},
  {id:`g${i}_size_ratio`,group:`Galaxy ${i}`,galaxy:i,label:'Size vs Galaxy A',min:.3,max:2,step:.05,default:1,unit:'× A',hint:'Scales disk scale length, thickness and halo Plummer radius.'},
  {id:`g${i}_sep`,group:`Galaxy ${i}`,galaxy:i,label:'Separation',min:8,max:80,step:.5,default:20,unit:'× 3 kpc',physical:kpc},
  {id:`g${i}_impact`,group:`Galaxy ${i}`,galaxy:i,label:'Impact parameter',min:0,max:20,step:.5,default:4,unit:'× 3 kpc',physical:kpc},
  {id:`g${i}_vrel`,group:`Galaxy ${i}`,galaxy:i,label:'Relative speed',min:.4,max:4,step:.05,default:2,unit:'× 119.7 km/s',physical:kms},
  {id:`g${i}_azimuth`,group:`Galaxy ${i}`,galaxy:i,label:'Approach azimuth',min:0,max:360,step:5,default:CLONE_AZIMUTH[i],unit:'deg'},
  {id:`g${i}_inclination`,group:`Galaxy ${i}`,galaxy:i,label:'Orbital inclination',min:0,max:180,step:5,default:0,unit:'deg',hint:'Orbital plane versus Galaxy A’s disk.'},
  {id:`g${i}_disk_tilt`,group:`Galaxy ${i}`,galaxy:i,label:'Disk tilt',min:0,max:180,step:5,default:0,unit:'deg',hint:'Extra galaxy’s own disk, after spin, before sky placement.'},
  {id:`g${i}_spin`,group:`Galaxy ${i}`,galaxy:i,label:'Disk spin',kind:'choice',stops:[1,-1],labels:['Prograde','Retrograde'],default:1,unit:'',hint:'+1 with Galaxy A; −1 flips in-plane rotation.'}
]}
export const GALAXY_SLIDERS=[
  {id:'n',group:'Compute',label:'Gravitating particles',kind:'choice',stops:[10000,30000,100000,200000,500000,1000000],default:100000,unit:'superparticles',hint:'1,000,000 is the ceiling. Each dot is a superparticle, not one star. 2–5 galaxies share this budget. One million is live CPU N-body; the 120 h cap still applies, and Observe uses more GPU memory.'},
  {id:'threads',group:'Compute',label:'CPU threads',kind:'choice',stops:[1,4,8,10,14],default:8,unit:'threads'},
  {id:'duration',group:'Compute',label:'Simulation span',min:1,max:1200,step:1,default:10,unit:'model time units',physical:myr,hint:'Maximum updates live from the 120 h wall-time estimate as N, threads, dt and lifecycle change.'},
  {id:'seed',group:'Compute',label:'Random seed',kind:'number',min:0,max:4294967295,step:1,default:731,unit:'integer'},
  {id:'n_galaxies',group:'Encounter',label:'Live galaxies',kind:'choice',stops:[1,2,3,4,5],default:2,unit:'galaxies',hint:'1 = isolated revision-3 lab. 2–5 share the particle budget. Not a calibrated Local Group.'},
  ...[2,3,4,5].flatMap(cloneSliders),
  {id:'disk_mass',group:'Galaxy shape',label:'Disk mass',min:.2,max:5,step:.05,default:1,unit:'×10¹⁰ M☉',physical:msun10},
  {id:'halo_mass',group:'Galaxy shape',label:'Dark halo mass',min:2,max:80,step:.5,default:20,unit:'×10¹⁰ M☉'},
  {id:'disk_fraction',group:'Galaxy shape',label:'Disk particle fraction',min:.15,max:.45,step:.01,default:.3,unit:'of N',hint:'Fraction of particles that are baryonic disk slots.'},
  {id:'disk_scale',group:'Galaxy shape',label:'Disk scale length',min:.5,max:3,step:.05,default:1.2,unit:'× 3 kpc',physical:kpc},
  {id:'disk_thickness',group:'Galaxy shape',label:'Disk scale height',min:.03,max:.25,step:.005,default:.08,unit:'× 3 kpc',physical:kpc},
  {id:'halo_scale',group:'Galaxy shape',label:'Halo Plummer radius',min:1.5,max:10,step:.1,default:4,unit:'× 3 kpc',physical:kpc},
  {id:'warmth',group:'Galaxy shape',label:'Disk warmth (Toomre-like Q)',min:.4,max:3,step:.05,default:1,unit:'× default dispersion',hint:'Below 1 the disk is colder and fragments faster; above 1 it is smoother.'},
  {id:'smbh_mass',group:'Galaxy shape',label:'Central black hole mass',min:0,max:.1,step:.001,default:0,unit:'×10¹⁰ M☉',physical:v=>v>0?`${(v*1e4).toFixed(0)}×10⁶ M☉`:'off',hint:'0 = none. Replaces one halo particle so N is unchanged.'},
  {id:'lifecycle_enabled',group:'Stellar lifecycle',label:'Stellar lifecycle',kind:'bool',default:true,hint:'Gas → protostar → main sequence → giant → white dwarf / neutron star / black hole. Masses feed gravity.'},
  {id:'gas_fraction',group:'Stellar lifecycle',label:'Initial gas fraction of disk',min:0,max:.8,step:.01,default:.2,unit:'of disk mass'},
  {id:'t_sf',group:'Stellar lifecycle',label:'Star-formation timescale',min:.1,max:20,step:.1,default:2,unit:'Gyr',hint:'Gas mass / this timescale = star-formation rate.'},
  {id:'lifecycle_speed',group:'Stellar lifecycle',label:'Lifecycle clock speed',min:1,max:80,step:1,default:1,unit:'×',hint:'1 = physical lifetimes; 40 ≈ 10 Gyr stellar life in a 250 Myr run. Not a calibration.'},
  {id:'sf_density_bias',group:'Stellar lifecycle',label:'Birth density bias',min:0,max:1,step:.05,default:.7,unit:'0 random · 1 densest gas'},
  {id:'imf_mmin',group:'Stellar lifecycle',label:'IMF minimum mass',min:.05,max:1,step:.01,default:.08,unit:'M☉'},
  {id:'imf_mmax',group:'Stellar lifecycle',label:'IMF maximum mass',min:20,max:150,step:1,default:100,unit:'M☉'},
  {id:'grow_rate',group:'Stellar lifecycle',label:'Protostar accretion rate',min:0,max:1,step:.05,default:.2,unit:'of slot mass per Myr'},
  {id:'sn_kick_kms',group:'Stellar lifecycle',label:'Supernova remnant kick',min:0,max:200,step:5,default:0,unit:'km/s'},
  {id:'theta',group:'Numerical',label:'Tree opening angle θ',min:.25,max:.7,step:.05,default:.4,unit:'rad-like',hint:'Smaller is more accurate and slower.'},
  {id:'softening',group:'Numerical',label:'Force softening',min:.03,max:.15,step:.005,default:.06,unit:'× 3 kpc',physical:v=>`${(v*3000).toFixed(0)} pc`},
  {id:'dt',group:'Numerical',label:'Leapfrog time step',min:.01,max:.04,step:.005,default:.02,unit:'model time',physical:v=>`${(v*MYR_PER_TIME).toFixed(2)} Myr`}];
const PLANET_NAMES=['Mercury','Venus','Earth–Moon','Mars','Jupiter','Saturn','Uranus','Neptune'];
export const PLANET_SLIDERS=[
  {id:'duration',group:'Compute',label:'Simulation span',min:1,max:50,step:1,default:12,unit:'years'},
  {id:'seed',group:'Compute',label:'Random seed',kind:'number',min:0,max:4294967295,step:1,default:731,unit:'integer (unused by IAS15 ICs)'},
  {id:'jupiter_mass',group:'Planet masses',label:'Jupiter mass multiplier',kind:'choice',stops:[1,3,10],default:1,unit:'× Jupiter'},
  ...PLANET_NAMES.map((name,i)=>({id:`planet_mass_scale_${i}`,path:['planet_mass_scale',i],group:'Planet masses',label:`${name} mass scale`,min:.25,max:10,step:.05,default:1,unit:'× J2000 mass'})),
  {id:'perturber_mass',group:'Perturber',label:'Perturber mass',min:0,max:.01,step:.0005,default:0,unit:'M☉',physical:v=>v>0?`${(v*1047.6).toFixed(1)} M♃`:'off'},
  {id:'perturber_a',group:'Perturber',label:'Perturber semi-major axis',min:.5,max:40,step:.5,default:2.5,unit:'AU'}];
export function slidersFor(mode){return mode==='galaxy'?GALAXY_SLIDERS:PLANET_SLIDERS}
export function defaultsFor(mode){const out={};slidersFor(mode).forEach(s=>out[s.id]=s.default);return out}
export function toConfig(mode,values){const cfg={mode};const scale=[1,1,1,1,1,1,1,1];slidersFor(mode).forEach(s=>{const v=values[s.id]??s.default;if(s.path){scale[s.path[1]]=Number(v)}else cfg[s.id]=s.kind==='bool'?Boolean(v):Number(v)});if(mode==='planets')cfg.planet_mass_scale=scale;return cfg}
export function fromConfig(mode,cfg){const out=defaultsFor(mode);slidersFor(mode).forEach(s=>{if(s.path){const arr=cfg[s.path[0]];if(Array.isArray(arr)&&arr[s.path[1]]!=null)out[s.id]=arr[s.path[1]]}else if(cfg[s.id]!=null)out[s.id]=cfg[s.id]});if(mode==='galaxy'&&cfg.n_galaxies==null)out.n_galaxies=1;return out}
export function estimateSeconds(cfg){if(cfg.mode==='planets'){const bodies=cfg.perturber_mass>0?10:9;return .25*cfg.duration/12*(bodies/9)**2}const n=cfg.n,steps=cfg.duration/cfg.dt;return REFERENCE_SECONDS*(n/1e5)*Math.log(n)/Math.log(1e5)*(steps/500)*(10/cfg.threads)*(cfg.lifecycle_enabled?1.15:1)*((cfg.n_galaxies||1)>1?1.05:1)}
export function estimateWallHours(cfg){return estimateSeconds(cfg)/3600}
export function maxDuration(cfg){const per=estimateSeconds({...cfg,duration:1});return per>0?WALL_CAP_HOURS*3600/per:Infinity}
export function durationCap(cfg){if(cfg.mode==='planets')return 50;const m=maxDuration(cfg);return Math.max(1,Math.min(1200,Math.floor(m)))}
export function engineRamGb(cfg){return cfg.mode==='planets'?.12:.15+cfg.n*7e-7*(cfg.lifecycle_enabled?1.2:1)}
export const fmt=n=>Number(n).toLocaleString('en-US');
export function fmtHours(h){if(!isFinite(h))return '—';if(h<1/60)return `${Math.round(h*3600)} s`;if(h<1)return `${(h*60).toFixed(1)} min`;return `${h.toFixed(h<10?2:1)} h`}
export function fmtSeconds(s){if(s==null||!isFinite(s))return '—';if(s<90)return `${Math.round(s)} s`;if(s<3600)return `${(s/60).toFixed(1)} min`;return `${(s/3600).toFixed(2)} h`}
export function fmtNum(x,digits=3){return x==null||!isFinite(x)?'—':Number(x).toPrecision(digits)}
export function percent(x){return x==null||!isFinite(x)?'—':(x*100).toPrecision(3)+'%'}
export async function api(path,body,method){const init=body!==undefined||method?{method:method||'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}:{};const response=await fetch(path,init);const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data}
export const PHASE_LABEL={complete:'Complete',running:'Computing',paused:'Paused',queued:'Queued',initializing:'Initializing',interrupted:'Checkpoint saved',error:'Error',pausing:'Writing checkpoint'};
export function phaseLabel(status){if(status.wall_capped&&status.phase==='interrupted')return '120 h cap';if(status.phase==='pausing')return 'Writing checkpoint';if(status.pause_pending&&status.phase==='initializing')return 'Pause queued';if(status.pause_pending&&status.phase==='running')return 'Pausing';return PHASE_LABEL[status.phase]||status.phase}
