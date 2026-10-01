// AGENT MAP: WebGL playback only; physics runs in the Python worker (on this Mac or a compute node).
// Frame layout is versioned by meta.bytes_per_particle: 16 = [x,y,z,speed]; 24 = [x,y,z,speed,mass,type] float32 per body.
// Position interpolation is visual. Playback speed is independent of computed simulation time and of compute pause.
// Frame cache is byte-bounded (~96 MB). Runs above 250k particles draw a strided sample unless Full detail is on.
// dispose() releases the GPU context.
// Click (not drag) picks the nearest visible body on screen → hooks.onPick(index); the app fetches its saved track from the server.
import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';

// ptype: 0 gas, 1 protostar, 2 main sequence, 3 giant, 4 white dwarf, 5 neutron star, 6 black hole, 7 halo, 8 central black hole.
const pointVertex=`attribute vec4 stateA; attribute vec4 stateB; attribute float ptype; attribute float sparkle; attribute float galaxyId; uniform float blend; uniform float pixelRatio; uniform float showDisk; uniform float showHalo; uniform float colorMode; uniform float boost; varying vec3 tint; varying float opacity; void main(){vec4 s=mix(stateA,stateB,blend);vec3 p=vec3(s.x,s.z,-s.y);float radius=length(s.xy);float t=floor(ptype+.5);float size=1.;bool halo=t>6.5&&t<7.5;if(colorMode>1.5){float gi=floor(galaxyId+.5);if(gi<.5)tint=vec3(.894,.796,.667);else if(gi<1.5)tint=vec3(.494,.722,1.);else if(gi<2.5)tint=vec3(.941,.639,.761);else if(gi<3.5)tint=vec3(.620,.878,.690);else tint=vec3(.878,.816,.478);}else if(colorMode>.5){float v=clamp(s.w/2.2,0.,1.);tint=mix(vec3(.27,.48,.70),vec3(1.,.68,.33),v);}else if(halo){tint=vec3(.31,.44,.70);}else if(t<.5){tint=vec3(.36,.58,.72);}else if(t<1.5){tint=vec3(1.,.45,.22);size=1.3;}else if(t<2.5){tint=mix(vec3(1.,.85,.63),vec3(.53,.76,.87),clamp(radius/5.,0.,1.));}else if(t<3.5){tint=vec3(1.,.55,.25);size=1.7;}else if(t<4.5){tint=vec3(.80,.90,1.);size=.8;}else if(t<5.5){tint=vec3(.72,.60,1.);size=1.1;}else if(t<6.5){tint=vec3(.95,.30,.80);size=1.9;}else{tint=vec3(1.,1.,.9);size=4.;}opacity=halo?showHalo*(colorMode>1.5?.45:.19):(t<.5?showDisk*.5:showDisk);vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;gl_PointSize=clamp((1.3+sparkle*1.4)*size*pixelRatio*22.*boost/max(-mv.z,1.),.7,9.*boost);}`;
const pointFragment=`varying vec3 tint;varying float opacity;void main(){float r=length(gl_PointCoord-.5)*2.;if(r>1.||opacity<.001)discard;float a=exp(-r*r*4.5)*opacity;gl_FragColor=vec4(tint,a);}`;
const PREVIEW_BODIES=[['Sun','#ffd27a'],['Mercury','#a9a39b'],['Venus','#e6c38f'],['Earth–Moon','#6fa8dc'],['Mars','#d0694a'],['Jupiter','#d9b38c'],['Saturn','#e3cf9b'],['Uranus','#9fd8e0'],['Neptune','#5f7fe0'],['Perturber','#f07fb5']];

export function createViewer(canvas,labelBox,hooks={}){
  const renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor('#070b10');renderer.outputColorSpace=THREE.SRGBColorSpace;
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(43,1,.01,8000);camera.position.set(12,8,14);
  const controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.07;controls.minDistance=.5;controls.maxDistance=800;
  scene.add(new THREE.AmbientLight(0xc4d3ea,1.7));const sunLight=new THREE.PointLight(0xffedcc,70,0,1);scene.add(sunLight);
  let content=new THREE.Group();scene.add(content);
  let job=null,mode='galaxy',points=null,buffers=null,planetMeshes=[],labels=[],guides=new THREE.Group();
  let cache=new Map(),inflight=new Set(),allPlanets=null,loadedKey='',position=0,playing=true,rate=1,active=true,raf=0,layers={disk:true,halo:false,orbits:true,labels:true,colorMode:'component'};
  let previewing=false,previewFrame=null,disposed=false,curStride=4,playFrame=0;
  // Huge runs draw a strided sample (every k-th particle plus each central black hole) so playback stays smooth:
  // ~4× less to download, copy and upload at 1M. Point size grows by √k to keep the same light. Indices crossing the
  // viewer's API (onPick, select, sample) are particle indices; display indices stay inside. server.py display_sample() matches.
  const SAMPLE_TARGET=250000;let sampling=null,fullDetail=false,loadGen=0,loadedA=-1,loadedB=-1;
  function sampleMap(meta){
    const n=meta.n,k=fullDetail?1:Math.ceil(n/SAMPLE_TARGET);if(k<=1)return null;const gals=meta.galaxies||[],c=meta.smbh_count||0;
    const extras=gals.length?gals.filter(g=>g.smbh_count).map(g=>(g.start||0)+g.n-1):Array.from({length:c},(_,i)=>n-c+i),base=Math.ceil(n/k);
    return {k,n,base,extras,m:base+extras.length}}
  const toOrig=d=>!sampling?d:d<sampling.base?d*sampling.k:sampling.extras[d-sampling.base];
  const toDisp=o=>{if(!sampling)return o;if(o%sampling.k===0&&o/sampling.k<sampling.base)return o/sampling.k;const e=sampling.extras.indexOf(o);return e<0?null:sampling.base+e};
  function thin(arr){
    // Fallback when the server predates ?every=: take the same sample from a full frame.
    const st=stride(),out=new Float32Array(sampling.m*st);for(let d=0;d<sampling.m;d++){const o=toOrig(d)*st;for(let c=0;c<st;c++)out[d*st+c]=arr[o+c]}return out}
  const stride=()=>((job?.meta.bytes_per_particle)||16)/4;
  // Star inspector: one selected body, a screen-sized ring on it and its saved track drawn up to the playhead.
  // The ring follows the interpolated (visual) position; the track vertices are saved frames only.
  let selectedIdx=null,track=[],trackLine=null,follow=false;
  const ringCanvas=document.createElement('canvas');ringCanvas.width=ringCanvas.height=64;{const c=ringCanvas.getContext('2d');c.strokeStyle='#b2dfc6';c.lineWidth=4;c.beginPath();c.arc(32,32,25,0,Math.PI*2);c.stroke()}
  const marker=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(ringCanvas),depthTest:false,depthWrite:false,sizeAttenuation:false,transparent:true}));
  marker.scale.set(.045,.045,1);marker.renderOrder=10;marker.visible=false;scene.add(marker);
  const resize=()=>{const r=canvas.parentElement.getBoundingClientRect();if(!r.width||!r.height)return;renderer.setSize(r.width,r.height,false);camera.aspect=r.width/r.height;camera.updateProjectionMatrix()};
  const ro=new ResizeObserver(resize);ro.observe(canvas.parentElement);resize();

  function clearScene(){const had=selectedIdx!=null;selectedIdx=null;follow=false;setTrack([]);marker.visible=false;if(had)hooks.onPick?.(null);content.traverse(o=>{o.geometry?.dispose();if(o.material){(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>{m.map?.dispose();m.dispose()})}});scene.remove(content);content=new THREE.Group();scene.add(content);points=null;buffers=null;planetMeshes=[];labels=[];labelBox.replaceChildren();guides=new THREE.Group();content.add(guides)}
  let fitDistance=0;
  function fitTo(arr,st){
    // 90th-percentile radius of a sample, so a multi-galaxy preview frames every galaxy.
    const n=arr.length/st,step=Math.max(1,Math.floor(n/2000)),r=[];for(let i=0;i<n;i+=step){const k=i*st;r.push(Math.hypot(arr[k],arr[k+1],arr[k+2]))}
    r.sort((a,b)=>a-b);fitDistance=Math.max(19,2.3*(r[Math.floor(r.length*.9)]||0))}
  function home(view){
    controls.target.set(0,0,0);const d=job?.meta?.camera_distance||(previewing?fitDistance:0);
    if(mode==='galaxy'){const v=new THREE.Vector3(11,8,13);if(d>0)v.normalize().multiplyScalar(d);camera.position.copy(v)}
    else if(view==='inner')camera.position.set(0,4.7,4.7);else camera.position.set(0,49,49);
    if(view==='top'){const r=camera.position.length();camera.position.set(.001,r,.001)}
    if(view==='side'){const r=camera.position.length();camera.position.set(r,.15,0)}
    controls.update()}
  function galaxyPoints(n,st,meta,single){
    curStride=st;const g=new THREE.BufferGeometry(),sparkles=new Float32Array(n);for(let i=0;i<n;i++)sparkles[i]=((i*16807)%2147483647)%101/100;
    const bufA=new THREE.InterleavedBuffer(new Float32Array(n*st),st),bufB=single?bufA:new THREE.InterleavedBuffer(new Float32Array(n*st),st);buffers={a:bufA,b:bufB};
    g.setAttribute('stateA',new THREE.InterleavedBufferAttribute(bufA,4,0));g.setAttribute('stateB',new THREE.InterleavedBufferAttribute(bufB,4,0));g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(n*3),3));
    if(st>=6)g.setAttribute('ptype',new THREE.InterleavedBufferAttribute(bufB,1,5));else{const groups=new Float32Array(n);for(let i=0;i<n;i++)groups[i]=toOrig(i)<meta.disk_count?2:7;g.setAttribute('ptype',new THREE.BufferAttribute(groups,1))}
    const gid=new Float32Array(n),gals=meta.galaxies||[];if(gals.length)for(let d=0;d<n;d++){const o=toOrig(d);for(const gal of gals){const a=gal.start||0;if(o>=a&&o<a+(gal.n||0)){gid[d]=(gal.id||1)-1;break}}}g.setAttribute('galaxyId',new THREE.BufferAttribute(gid,1));g.setAttribute('sparkle',new THREE.BufferAttribute(sparkles,1));
    const material=new THREE.ShaderMaterial({vertexShader:pointVertex,fragmentShader:pointFragment,uniforms:{blend:{value:0},pixelRatio:{value:renderer.getPixelRatio()},showDisk:{value:1},showHalo:{value:0},colorMode:{value:0},boost:{value:sampling?Math.sqrt(sampling.k):1}},transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
    points=new THREE.Points(g,material);points.frustumCulled=false;content.add(points);syncLayers()}
  function orbitCurve(b){const pts=[],node=THREE.MathUtils.degToRad(b.node),omega=THREE.MathUtils.degToRad(b.peri-b.node),inc=THREE.MathUtils.degToRad(b.inc);for(let i=0;i<=256;i++){const E=i/256*Math.PI*2,x=b.a*(Math.cos(E)-b.e),y=b.a*Math.sqrt(1-b.e*b.e)*Math.sin(E);const X=(Math.cos(omega)*Math.cos(node)-Math.sin(omega)*Math.sin(node)*Math.cos(inc))*x+(-Math.sin(omega)*Math.cos(node)-Math.cos(omega)*Math.sin(node)*Math.cos(inc))*y;const Y=(Math.cos(omega)*Math.sin(node)+Math.sin(omega)*Math.cos(node)*Math.cos(inc))*x+(-Math.sin(omega)*Math.sin(node)+Math.cos(omega)*Math.cos(node)*Math.cos(inc))*y;const Z=Math.sin(omega)*Math.sin(inc)*x+Math.cos(omega)*Math.sin(inc)*y;pts.push(new THREE.Vector3(X,Z,-Y))}return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:0x344b57,transparent:true,opacity:.47}))}
  function planetBodies(bodies){
    bodies.forEach((b,i)=>{const material=i===0?new THREE.MeshBasicMaterial({color:b.color}):new THREE.MeshStandardMaterial({color:b.color,roughness:.9,metalness:0});const mesh=new THREE.Mesh(new THREE.SphereGeometry(1,32,20),material);mesh.userData.radius=i===0?.13:i===5?.08:i===6?.07:.045;content.add(mesh);planetMeshes.push(mesh);if(i&&b.a)guides.add(orbitCurve(b));
      if(i===6){const ring=new THREE.Mesh(new THREE.RingGeometry(1.4,2.25,64),new THREE.MeshBasicMaterial({color:0xbfae8b,side:THREE.DoubleSide,transparent:true,opacity:.65}));ring.rotation.x=-Math.PI/2+.3;mesh.add(ring)}
      const label=document.createElement('div');label.className='planet-label';label.textContent=b.name;label.style.color=b.color;labelBox.append(label);labels.push(label)});
    const glowCanvas=document.createElement('canvas');glowCanvas.width=glowCanvas.height=128;const ctx=glowCanvas.getContext('2d'),gr=ctx.createRadialGradient(64,64,0,64,64,64);gr.addColorStop(0,'rgba(255,218,154,0.7)');gr.addColorStop(.2,'rgba(255,185,100,.18)');gr.addColorStop(1,'rgba(255,150,70,0)');ctx.fillStyle=gr;ctx.fillRect(0,0,128,128);
    const glow=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(glowCanvas),transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));glow.scale.set(7,7,1);planetMeshes[0].add(glow);syncLayers()}
  function syncLayers(){if(points){const u=points.material.uniforms;u.showDisk.value=layers.disk?1:0;u.showHalo.value=layers.halo?1:0;u.colorMode.value=layers.colorMode==='galaxy'?2:layers.colorMode==='speed'?1:0}guides.visible=layers.orbits}
  function placePlanets(fa,fb,blend,st){
    const dist=camera.position.distanceTo(controls.target),rect=canvas.getBoundingClientRect();
    planetMeshes.forEach((mesh,i)=>{const k=i*st;mesh.position.set(THREE.MathUtils.lerp(fa[k],fb[k],blend),THREE.MathUtils.lerp(fa[k+2],fb[k+2],blend),-THREE.MathUtils.lerp(fa[k+1],fb[k+1],blend));mesh.scale.setScalar(mesh.userData.radius*Math.max(.65,dist/10));
      const v=mesh.position.clone().project(camera),label=labels[i];label.style.left=((v.x*.5+.5)*rect.width)+'px';label.style.top=((-v.y*.5+.5)*rect.height)+'px';label.style.display=layers.labels&&Math.abs(v.x)<.96&&Math.abs(v.y)<.85&&v.z<1&&!(dist>25&&i>0&&i<5)?'block':'none'});
    if(planetMeshes[0])sunLight.position.copy(planetMeshes[0].position)}
  function frameData(i){if(allPlanets&&i<allPlanets.count){const w=job.meta.n*stride();return allPlanets.values.subarray(i*w,(i+1)*w)}return cache.get(i)}
  function cacheLimit(){const per=(sampling?sampling.m:(job?.meta.n||0))*((job?.meta.bytes_per_particle)||16);return per?Math.max(4,Math.min(12,Math.floor(96*1024*1024/per))):12}
  // A failed frame is retried after 1 s, doubling to 30 s, instead of on every animation tick.
  const backoff=new Map();
  function request(i){
    if(!job?.meta.n||i<0||i>=job.status.frames||frameData(i)||inflight.has(i))return;const id=job.id,key=`${id}:${i}`,b=backoff.get(key),gen=loadGen;if(b&&performance.now()<b.at)return;inflight.add(i);
    fetch(`/api/jobs/${id}/frames?start=${i}${sampling?`&every=${sampling.k}`:''}`).then(r=>{if(!r.ok)throw Error('Frame unavailable');return r.arrayBuffer()}).then(buf=>{backoff.delete(key);if(job?.id!==id||gen!==loadGen)return;let arr=new Float32Array(buf);if(sampling&&arr.length===job.meta.n*stride())arr=thin(arr);if(arr.length!==(sampling?sampling.m:job.meta.n)*stride())return;cache.set(i,arr);hooks.onReady?.();const lim=cacheLimit();if(cache.size>lim){for(const key of cache.keys()){if(Math.abs(key-position)>2){cache.delete(key);if(cache.size<=Math.max(4,lim-2))break}}}}).catch(e=>{const delay=Math.min(30000,(b?.delay||500)*2);backoff.set(key,{delay,at:performance.now()+delay});if(job?.id===id)hooks.onError?.(e.message)}).finally(()=>{if(job?.id===id&&gen===loadGen)inflight.delete(i)})}
  async function primePlanets(){const id=job.id,count=job.status.frames;if(!count)return;try{const r=await fetch(`/api/jobs/${id}/frames?start=0&count=${count}`);if(!r.ok)throw Error('Frames unavailable');const values=new Float32Array(await r.arrayBuffer());if(job?.id===id){allPlanets={values,count};hooks.onReady?.()}}catch(e){hooks.onError?.(e.message)}}

  function load(next){
    previewing=false;previewFrame=null;job=next;mode=next.config.mode;cache=new Map();inflight=new Set();allPlanets=null;loadedKey='';loadedA=loadedB=-1;loadGen++;position=0;playFrame=0;clearScene();
    sampling=mode==='galaxy'&&next.meta?.n?sampleMap(next.meta):null;
    if(!next.meta?.n){home();return}
    if(mode==='galaxy')galaxyPoints(sampling?sampling.m:next.meta.n,stride(),next.meta,false);else{planetBodies(next.meta.bodies||[]);primePlanets()}
    home()}
  function update(next){
    if(!job||next.id!==job.id)return;const hadMeta=!!job.meta?.n;job=next;
    if(!hadMeta&&next.meta?.n)load(next);
    else if(mode==='planets'&&next.status.frames>(allPlanets?.count||0))primePlanets()}
  function preview(buf,m){
    // Initial conditions only: one xyzsmt frame from /api/preview, never a saved run.
    job=null;previewing=true;previewFrame=null;mode=m;cache=new Map();allPlanets=null;sampling=null;loadedA=loadedB=-1;loadGen++;clearScene();const arr=new Float32Array(buf),n=arr.length/6;
    if(m==='galaxy'){galaxyPoints(n,6,{},true);buffers.a.array.set(arr);buffers.a.needsUpdate=true;points.material.uniforms.blend.value=0}
    else{planetBodies(PREVIEW_BODIES.slice(0,n).map(([name,color])=>({name,color})));previewFrame=arr;placePlanets(arr,arr,0,6)}
    // Re-frame when the layout changes scale (e.g. galaxy count or separation), not on every slider tick.
    const before=fitDistance;fitTo(arr,6);if(m==='galaxy'&&(!camera.userData.previewed||Math.abs(fitDistance-before)/Math.max(before,1)>.25)){home();camera.userData.previewed=true}
    else if(m!=='galaxy'&&!camera.userData.previewedPlanets){home();camera.userData.previewedPlanets=true}}
  function clear(){job=null;previewing=false;previewFrame=null;clearScene()}

  // ---------- star inspector ----------
  const toScene=(x,y,z,out=new THREE.Vector3())=>out.set(x,z,-y);
  function currentPos(i){
    if(mode==='planets')return planetMeshes[i]?.position.clone()||null;
    if(!points||!buffers)return null;const d=toDisp(i);if(d==null)return null;const k=d*curStride,fa=buffers.a.array,fb=buffers.b.array,bl=points.material.uniforms.blend.value;if(k+2>=fa.length)return null;
    return toScene(fa[k]+(fb[k]-fa[k])*bl,fa[k+1]+(fb[k+1]-fa[k+1])*bl,fa[k+2]+(fb[k+2]-fa[k+2])*bl)}
  function setTrack(pts){
    track=pts||[];if(trackLine){scene.remove(trackLine);trackLine.geometry.dispose();trackLine.material.dispose();trackLine=null}
    if(!track.length)return;const n=track.length+1,pos=new Float32Array(n*3),col=new Float32Array(n*3),v=new THREE.Vector3();
    // Older segments fade toward the background so the recent path reads first.
    track.forEach((p,i)=>{toScene(p.x,p.y,p.z,v);pos.set([v.x,v.y,v.z],i*3);const f=.18+.82*(i+1)/n;col.set([.70*f,.87*f,.78*f],i*3)});col.set([.70,.87,.78],(n-1)*3);
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(pos,3));g.setAttribute('color',new THREE.BufferAttribute(col,3));
    trackLine=new THREE.Line(g,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));trackLine.frustumCulled=false;trackLine.renderOrder=9;scene.add(trackLine)}
  function drawTrack(p){
    // Saved positions up to the playhead's frame, then the live (interpolated) point, so the line ends on the ring.
    if(!trackLine)return;let k=0;while(k<track.length&&track[k].frame<=playFrame)k++;
    const attr=trackLine.geometry.getAttribute('position');attr.setXYZ(k,p.x,p.y,p.z);attr.needsUpdate=true;trackLine.geometry.setDrawRange(0,k+1)}
  function pickAt(clientX,clientY){
    const rect=canvas.getBoundingClientRect(),w=rect.width,h=rect.height,mx=clientX-rect.left,my=clientY-rect.top;
    camera.updateMatrixWorld();const m=new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse).elements;
    let best=-1,bestD=Infinity,bestW=Infinity;
    const test=(i,px,py,pz,R)=>{const cw=m[3]*px+m[7]*py+m[11]*pz+m[15];if(cw<=camera.near)return;
      const sx=((m[0]*px+m[4]*py+m[8]*pz+m[12])/cw*.5+.5)*w,sy=(-(m[1]*px+m[5]*py+m[9]*pz+m[13])/cw*.5+.5)*h,d=(sx-mx)**2+(sy-my)**2;
      if(d>R*R)return;if(d<bestD-4||(d<=bestD+4&&cw<bestW)){best=i;bestD=d;bestW=cw}};   // nearest on screen; ties go to the nearer body
    if(mode==='galaxy'&&points&&buffers){
      const cs=curStride,fa=buffers.a.array,fb=buffers.b.array,bl=points.material.uniforms.blend.value,n=Math.floor(fa.length/cs),types=cs>=6?null:points.geometry.getAttribute('ptype').array;
      for(let i=0;i<n;i++){const k=i*cs,t=Math.round(types?types[i]:fb[k+5]);if(t===7?!layers.halo:!layers.disk)continue;   // hidden layers cannot be picked
        const x=fa[k]+(fb[k]-fa[k])*bl,y=fa[k+1]+(fb[k+1]-fa[k+1])*bl,z=fa[k+2]+(fb[k+2]-fa[k+2])*bl;test(i,x,z,-y,12)}}
    else planetMeshes.forEach((mesh,i)=>test(i,mesh.position.x,mesh.position.y,mesh.position.z,22));
    return best<0?null:mode==='galaxy'?toOrig(best):best}
  let down=null;
  canvas.addEventListener('pointerdown',e=>{down=e.button===0?{x:e.clientX,y:e.clientY,t:performance.now()}:null});
  canvas.addEventListener('pointerup',e=>{if(!down)return;const click=Math.hypot(e.clientX-down.x,e.clientY-down.y)<5&&performance.now()-down.t<600;down=null;
    if(!click||!(points||planetMeshes.length))return;const i=pickAt(e.clientX,e.clientY);if(i!=null)hooks.onPick?.(i)});

  function swapBuffers(){
    const t=buffers.a;buffers.a=buffers.b;buffers.b=t;const g=points.geometry;
    g.setAttribute('stateA',new THREE.InterleavedBufferAttribute(buffers.a,4,0));g.setAttribute('stateB',new THREE.InterleavedBufferAttribute(buffers.b,4,0));
    if(curStride>=6)g.setAttribute('ptype',new THREE.InterleavedBufferAttribute(buffers.b,1,5))}

  let last=performance.now(),frames=0,fpsAt=last,fps=0;
  function tick(now){
    raf=requestAnimationFrame(tick);if(!active||disposed)return;if(now-last<1000/60-1)return;const elapsed=Math.min((now-last)/1000,.08);last=now;controls.update();
    if(previewing&&mode==='planets'&&previewFrame)placePlanets(previewFrame,previewFrame,0,6);   // labels and sizes follow the camera
    if(job?.meta.n&&job.status.frames>0){
      const max=job.status.frames-1;
      if(playing&&frameData(Math.floor(position))){position+=elapsed*(mode==='galaxy'?5:32)*rate;if(position>max)position=job.status.phase==='complete'?0:max}
      const a=Math.floor(position),b=Math.min(a+1,max);request(a);request(b);if(mode==='galaxy'){request(Math.min(b+1,max));request(Math.min(b+2,max))}
      const fa=frameData(a),fb=frameData(b)||fa;
      if(fa&&fb){const blend=position-a;playFrame=a;
        if(mode==='galaxy'&&points&&buffers){const key=`${a}:${b}`;if(key!==loadedKey){if(loadedB===a&&b!==a){swapBuffers();buffers.b.array.set(fb);buffers.b.needsUpdate=true}else{buffers.a.array.set(fa);buffers.a.needsUpdate=true;buffers.b.array.set(fb);buffers.b.needsUpdate=true}loadedA=a;loadedB=b;loadedKey=key}points.material.uniforms.blend.value=blend}
        else if(mode==='planets')placePlanets(fa,fb,blend,stride());
        const times=job.meta.times||[];hooks.onTime?.({position,max,time:THREE.MathUtils.lerp(times[a]||0,times[b]||times[a]||0,blend)*(job.meta.time_scale||1),ready:true})}}
    if(selectedIdx!=null){const p=currentPos(selectedIdx);marker.visible=!!p;if(p){marker.position.copy(p);drawTrack(p);if(follow){camera.position.add(p.clone().sub(controls.target));controls.target.copy(p)}}}
    renderer.render(scene,camera);frames++;if(now-fpsAt>1000){fps=Math.round(frames*1000/(now-fpsAt));frames=0;fpsAt=now;hooks.onFps?.(fps)}}
  raf=requestAnimationFrame(tick);

  return {
    load,update,preview,clear,home,
    get job(){return job},get previewing(){return previewing},
    setLayers(next){Object.assign(layers,next);syncLayers()},
    setPlaying(v){playing=v},get playing(){return playing},
    setRate(v){rate=v},
    seek(v){position=Math.max(0,v);playing=false;request(Math.floor(position));request(Math.ceil(position))},
    setActive(v){active=v;if(!v){cache=new Map();inflight=new Set();loadedKey='';loadedA=loadedB=-1;loadGen++}},
    get sampling(){return sampling},
    setFullDetail(v){fullDetail=!!v;if(job&&mode==='galaxy'&&job.meta?.n){const pos=position,was=playing;load(job);position=pos;playing=was}},
    select(i){selectedIdx=i;setTrack([]);marker.visible=false;if(i==null)follow=false},
    get selected(){return selectedIdx},setTrack,setFollow(v){follow=!!v},
    focusSelected(){
      // Re-centre the orbit target on the selected body and move in if the camera is far away.
      const p=selectedIdx==null?null:currentPos(selectedIdx);if(!p)return;const off=camera.position.clone().sub(controls.target),max=mode==='galaxy'?6:3;
      if(off.length()>max)off.setLength(max);controls.target.copy(p);camera.position.copy(p).add(off);controls.update()},
    get playFrame(){return playFrame},
    sample(i){
      // Saved values of body i at the playhead's frame (not interpolated), or at the preview's single frame.
      if(i==null)return null;
      if(previewing){const arr=mode==='galaxy'?buffers?.a.array:previewFrame,k=i*6;if(!arr||k+5>=arr.length)return null;
        const o={frame:0,preview:true,x:arr[k],y:arr[k+1],z:arr[k+2],speed:arr[k+3],mass:arr[k+4],type:Math.round(arr[k+5])};if(mode==='planets')o.sun=[arr[0],arr[1],arr[2]];return o}
      if(!job?.meta.n)return null;const fa=frameData(playFrame);if(!fa)return null;const di=mode==='galaxy'?toDisp(i):i;if(di==null)return null;const st=stride(),k=di*st;
      const o={frame:playFrame,x:fa[k],y:fa[k+1],z:fa[k+2],speed:fa[k+3]};if(st>=6){o.mass=fa[k+4];o.type=Math.round(fa[k+5])}if(mode==='planets')o.sun=[fa[0],fa[1],fa[2]];return o},
    dispose(){disposed=true;setTrack([]);marker.material.map.dispose();marker.material.dispose();cancelAnimationFrame(raf);ro.disconnect();clearScene();controls.dispose();renderer.dispose();renderer.forceContextLoss()}}
}
