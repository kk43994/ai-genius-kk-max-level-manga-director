import * as T from 'three';
import {OrbitControls} from '../vendor/examples/jsm/controls/OrbitControls.js';
import {TransformControls} from '../vendor/examples/jsm/controls/TransformControls.js';
import {createStage} from './stage.js';
import {rigPreferences,RIG_STORE} from './rigged-actor.js';
import {SHOT_GUIDE,axisSide} from './filming-guide.js';
import {PRESETS,getPreset,makePreset,actorSignature} from './camera-presets.js';
import {createProject,validateProject,sampleCamera,shotAt,keyAt,upsertKey,DURATION,FPS,clamp} from './timeline.js';
import {createDirectedProject,DIRECTION_VERSION} from './shot-design.js';
const $=id=>document.getElementById(id),STORE='dashixiong-director:v1';
let project=createProject(),restoreError='';try{const s=localStorage.getItem(STORE);if(s)project=validateProject(JSON.parse(s));}catch(e){restoreError='已使用初始方案；本机旧工程未能读取：'+e.message;}
const TAKE_STORE='dashixiong-director:take-comparison:v1';let takes={};
try{const saved=JSON.parse(localStorage.getItem(TAKE_STORE)||'{}');for(const key of ['before','designed'])if(saved[key])takes[key]=validateProject(saved[key]);}catch{takes={};}
let time=0,shotIndex=0,playing=false,lastStamp=0,view='free',edit='camera',selectedKey=0,dragging=false,currentSpace='hall',lastFilmRect,lastWorldRect,saveTimer,toastTimer;
let singlePreview=false,showAllKeys=false,presetCandidate=null;
const presetBackups=new Map(),undoStack=[],scene=new T.Scene();
function makeRenderer(canvas){const r=new T.WebGLRenderer({canvas,antialias:true,preserveDrawingBuffer:true});r.setPixelRatio(Math.min(devicePixelRatio,1.5));r.outputColorSpace=T.SRGBColorSpace;r.toneMapping=T.ACESFilmicToneMapping;r.toneMappingExposure=1.08;r.shadowMap.enabled=true;r.shadowMap.type=T.PCFShadowMap;return r;}
let worldRenderer,filmRenderer;try{worldRenderer=makeRenderer($('worldCanvas'));filmRenderer=makeRenderer($('filmCanvas'));}catch(e){$('loading').textContent='WebGL 无法启动，请使用支持 WebGL 2 的浏览器。';throw e;}
const filmCam=new T.PerspectiveCamera(40,16/9,.025,130),observer=new T.PerspectiveCamera(48,1,.05,160);
const orbit=new OrbitControls(observer,$('worldCanvas'));orbit.enableDamping=true;orbit.dampingFactor=.12;orbit.minDistance=.35;orbit.maxDistance=85;orbit.maxPolarAngle=Math.PI*.95;
const ceilingClip=new T.Plane(new T.Vector3(0,-1,0),3.2);
const stage=createStage(scene),helpers=new T.Group();scene.add(helpers);
const grid=new T.GridHelper(24,48,'#a4b5ac','#738c85');grid.position.y=.075;grid.material.transparent=true;grid.material.opacity=.22;helpers.add(grid);
const cameraRig=new T.Group();cameraRig.name='当前摄影机';helpers.add(cameraRig);const targetRig=new T.Group();targetRig.name='摄影机注视点';helpers.add(targetRig);
const camBody=new T.Mesh(new T.BoxGeometry(.22,.15,.27),new T.MeshBasicMaterial({color:'#efbc86',depthTest:false}));camBody.userData.pick='camera';cameraRig.add(camBody);
const camLens=new T.Mesh(new T.CylinderGeometry(.065,.085,.14,16),camBody.material);camLens.rotation.x=Math.PI/2;camLens.position.z=-.18;camLens.userData.pick='camera';cameraRig.add(camLens);
const targetBall=new T.Mesh(new T.OctahedronGeometry(.055),new T.MeshBasicMaterial({color:'#f2d6ac',depthTest:false}));targetBall.userData.pick='target';targetRig.add(targetBall);
const proxyCam=new T.PerspectiveCamera();proxyCam.near=.12;proxyCam.far=1.7;const frustum=new T.CameraHelper(proxyCam);frustum.material.depthTest=false;frustum.material.transparent=true;frustum.material.opacity=.55;helpers.add(frustum);
const lookLine=new T.Line(new T.BufferGeometry(),new T.LineDashedMaterial({color:'#c6ba91',dashSize:.12,gapSize:.09,transparent:true,opacity:.5,depthTest:false}));helpers.add(lookLine);
let pathLine,pathMarkers=new T.Group();helpers.add(pathMarkers);
const axisGeometry=new T.BufferGeometry();axisGeometry.setAttribute('position',new T.Float32BufferAttribute(new Float32Array(6),3));
const axisLine=new T.Line(axisGeometry,new T.LineDashedMaterial({color:'#86e0da',dashSize:.16,gapSize:.1,depthTest:false,transparent:true,opacity:.7}));axisLine.renderOrder=10;helpers.add(axisLine);
function updateAxis(){
 const el=$('axisStatus');el.hidden=!$('showAxis').checked||view==='camera';axisLine.visible=$('showAxis').checked&&shot().space==='hall';
 if(shot().space!=='hall'){el.textContent='异象空间 · 人物轴线不适用';el.dataset.state='neutral';return;}
 const a=stage.actors.get('ye').root.position.toArray(),b=stage.actors.get('shi').root.position.toArray(),side=axisSide(a,b,filmCam.position.toArray());
 const attr=axisGeometry.attributes.position,dx=b[0]-a[0],dz=b[2]-a[2],length=Math.hypot(dx,dz)||1;
 attr.setXYZ(0,a[0]-dx/length*1.5,.10,a[2]-dz/length*1.5);attr.setXYZ(1,b[0]+dx/length*1.5,.10,b[2]+dz/length*1.5);attr.needsUpdate=true;axisGeometry.computeBoundingSphere();axisLine.computeLineDistances();
 const ref=axisSide(project.actors.find(a=>a.id==='ye').p,project.actors.find(a=>a.id==='shi').p,project.shots[0].keys[0].p);
 let state='same',message='叶宇 ↔ 师心水 · 与首镜同侧';
 if(side.side===null){state='neutral';message='两人位置过近 · 无法判断轴线';}
 else if(side.side===0){state='neutral';message='接近人物轴线 · 请核对视线衔接';}
 else if(!ref.side){state='neutral';message='首镜接近轴线 · 请人工核对侧别';}
 else if(side.side!==ref.side){state='crossed';message='已到人物轴线另一侧 · 留意切镜衔接';}
 el.dataset.state=state;el.textContent=message;el.title='青色虚线连接叶宇与师心水。参照首镜起点侧别，使用当前人物位置计算；不是完整连续性检查。可用可见运镜或重新建立全景来交代换侧。';
}

const actorProxy=new T.Object3D();helpers.add(actorProxy);
const gizmo=new TransformControls(observer,$('worldCanvas'));gizmo.setMode('translate');gizmo.setSize(.8);helpers.add(gizmo.getHelper());
gizmo.addEventListener('dragging-changed',e=>{dragging=e.value;orbit.enabled=!dragging&&view!=='camera';});
gizmo.addEventListener('mouseDown',()=>{checkpoint();pause();});
gizmo.addEventListener('objectChange',()=>{
 const o=gizmo.object;if(!o)return;
 if(edit==='camera'||edit==='target'){const p=sampleCamera(shot(),time);p[edit==='camera'?'p':'target']=o.position.toArray();upsertKey(shot(),time,p);markPresetEdited();selectedKey=keyAt(shot(),time);}
 else project.actors.find(a=>a.id===edit).p=o.position.toArray();
 rebuildPath();refreshEditor();dirty();
});
const labels=new Map();for(const a of project.actors){const el=document.createElement('span');el.className='actor-label';el.style.setProperty('--actor',a.color);const dot=document.createElement('i');el.append(dot,document.createTextNode(a.name));$('actorLabels').append(el);labels.set(a.id,el);}
const camLabel=document.createElement('span');camLabel.className='actor-label';camLabel.style.setProperty('--actor','#efbc86');camLabel.textContent='CAM · 拍摄机位';$('actorLabels').append(camLabel);
function shot(){return project.shots[shotIndex];}
function notify(s){$('toast').textContent=s;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,4200);}
function checkpoint(){const s=JSON.stringify(project);if(undoStack.at(-1)!==s)undoStack.push(s);if(undoStack.length>35)undoStack.shift();$('undo').disabled=!undoStack.length;}
function save(){try{localStorage.setItem(STORE,JSON.stringify(project));if(takes.before){takes[project.directionVersion===DIRECTION_VERSION?'designed':'before']=structuredClone(project);localStorage.setItem(TAKE_STORE,JSON.stringify(takes));}$('saveStatus').textContent='已保存到本机';}catch{$('saveStatus').textContent='保存失败 · 请导出工程';}}
function dirty(){clearTimeout(saveTimer);$('saveStatus').textContent='正在保存…';saveTimer=setTimeout(save,250);}
function change(fn){checkpoint();pause();fn();rebuildPath();refreshEditor();dirty();}
function pause(){playing=false;singlePreview=false;$('play').textContent='▶';$('play').setAttribute('aria-label','播放预演');}
function play(preview=false){if(preview&&time>=shot().end-.001)setTime(shot().start,true);else if(!preview&&time>=DURATION-.001)setTime(0);singlePreview=preview;playing=true;lastStamp=performance.now();$('play').textContent='Ⅱ';$('play').setAttribute('aria-label','暂停预演');gizmo.detach();}
function tc(t){const frame=Math.round(t*FPS),seconds=Math.floor(frame/FPS);return '00:'+String(seconds).padStart(2,'0')+':'+String(frame%FPS).padStart(2,'0');}
function setTime(t,keepShot=false){time=clamp(t,0,DURATION);const old=shotIndex;if(!keepShot)shotIndex=project.shots.indexOf(shotAt(project,time));selectedKey=keyAt(shot(),time);if(old!==shotIndex)onShotChanged();else if(!playing)refreshEditor();updateTimeUI();if(!playing)draw();}
function selectShot(index){pause();shotIndex=index;time=shot().start;selectedKey=0;onShotChanged();updateTimeUI();draw();}
function onShotChanged(){showAllKeys=false;rebuildPath();refreshShots();refreshEditor();const space=shot().space;if(space!==currentSpace){currentSpace=space;if(view!=='camera')frameStage();}else if(view==='top')frameStage();}
function updateTimeUI(){$('timecode').textContent=tc(time);$('scrubber').value=time;$('playhead').style.left=`${time/DURATION*100}%`;$('monitorShot').textContent=shot().id;$('worldCanvas').dataset.time=time.toFixed(4);$('worldCanvas').dataset.shot=shot().id;}
function refreshShots(){
 $('shotTitle').textContent=String(shotIndex+1).padStart(2,'0')+' / '+shot().name;$('spaceTag').textContent=shot().space==='hall'?'府邸正堂 · 三维片场':'体内异象 · 抽象视效片场';$('shotNote').textContent=shot().note;$('actionLabel').textContent=shot().action;
 const guide=shot().direction||SHOT_GUIDE[shot().id],preset=getPreset(shot().preset?.id);$('shotMethod').textContent=preset?preset.name+(shot().preset.modified?' · 已手调':' · 已套用'):guide.method;$('shotPurpose').textContent=preset?preset.purpose:guide.purpose;$('shotContinuity').textContent='衔接要点：'+guide.continuity+(guide.cut?' '+guide.cut:'');
 refreshTakeControls();
 $('sceneStatus').textContent=shot().space==='hall'?'同一片场 · 连续人物动作 · 镜头硬切':'异象插入镜头 · 仅用于尺度与运镜预演';
 for(const b of document.querySelectorAll('[data-shot]')){b.classList.toggle('active',Number(b.dataset.shot)===shotIndex);b.setAttribute('aria-current',Number(b.dataset.shot)===shotIndex?'true':'false');}
 for(const o of $('editTarget').options)o.disabled=shot().space==='vision'&&!['camera','target'].includes(o.value);
 if(shot().space==='vision'&&!['camera','target'].includes(edit)){edit='camera';$('editTarget').value=edit;}
 syncPresetForm();
}
function attachGizmo(){if(playing||view==='camera'){gizmo.detach();return;}if(edit==='camera')gizmo.attach(cameraRig);else if(edit==='target')gizmo.attach(targetRig);else{actorProxy.position.fromArray(project.actors.find(a=>a.id===edit).p);gizmo.attach(actorProxy);}}
function refreshEditor(){
 const pose=sampleCamera(shot(),time),isCam=['camera','target'].includes(edit),a=project.actors.find(a=>a.id===edit),p=isCam?pose[edit==='camera'?'p':'target']:a.p;
 for(const [i,id] of ['posX','posY','posZ'].entries()){if(document.activeElement!==$(id))$(id).value=p[i].toFixed(2);}
 $('lens').value=Math.round(pose.lens);$('lensValue').textContent=Math.round(pose.lens)+' mm';$('ease').value=shot().ease||'smooth';$('cameraSettings').hidden=!isCam;$('actorSettings').hidden=isCam;
 if(a){$('yaw').value=a.yaw;$('yawValue').textContent=Math.round(a.yaw)+'°';}
 $('editingState').textContent=!isCam?'整段人物位置':selectedKey<0?'编辑将新增关键帧':'编辑关键帧 '+(selectedKey+1);
 const visibleKeys=shot().keys.map((k,i)=>({k,i})).filter(({i})=>showAllKeys||shot().keys.length<=6||[0,Math.floor((shot().keys.length-1)/2),shot().keys.length-1,selectedKey].includes(i));
 $('keyList').replaceChildren(...visibleKeys.map(({k,i})=>{const b=document.createElement('button');b.textContent=(i===0?'起点':i===shot().keys.length-1?'终点':`K${i+1}`)+' '+k.t.toFixed(2)+'s';b.className=i===selectedKey?'active':'';b.setAttribute('aria-label','关键帧 '+b.textContent);b.onclick=()=>{pause();setTime(k.t,true);};return b;}));
 if(shot().keys.length>6){const b=document.createElement('button');b.className='key-expand';b.textContent=showAllKeys?'收起中间帧':'展开 '+shot().keys.length+' 个关键帧';b.onclick=()=>{showAllKeys=!showAllKeys;refreshEditor();};$('keyList').append(b);}
 $('deleteKey').disabled=selectedKey<=0||selectedKey>=shot().keys.length-1;$('captureView').disabled=view==='camera';$('addKey').disabled=!isCam||selectedKey>=0;
 $('editHelp').textContent=isCam?'选起点或终点，再拖空间中的箭头。橙线是摄影机运动轨迹。':'拖动人物的位置箭头，或填写坐标。人物的演示动作会继续沿时间轴执行。';
 if(!dragging)attachGizmo();refreshPresetStatus();
}
function rebuildPath(){
 if(pathLine){helpers.remove(pathLine);pathLine.geometry.dispose();pathLine.material.dispose();}
 const points=[];for(let i=0;i<=100;i++)points.push(new T.Vector3(...sampleCamera(shot(),shot().start+(shot().end-shot().start)*i/100).p));
 pathLine=new T.Line(new T.BufferGeometry().setFromPoints(points),new T.LineBasicMaterial({color:'#efb77e',transparent:true,opacity:.95,depthTest:false}));pathLine.renderOrder=9;helpers.add(pathLine);
 for(const c of [...pathMarkers.children]){c.geometry?.dispose();c.material?.dispose();}pathMarkers.clear();
 shot().keys.forEach((k,i)=>{const m=new T.Mesh(new T.SphereGeometry(.065,12,8),new T.MeshBasicMaterial({color:i===0?'#d3e2bb':i===shot().keys.length-1?'#f4ad81':'#b7d4d8',depthTest:false}));m.position.fromArray(k.p);m.userData.key=i;pathMarkers.add(m);});
}
function frameStage(){
 observer.up.set(0,1,0);if(shot().space==='vision'){if(view==='top'){observer.position.set(15,25,-6);orbit.target.set(0,0,-10);}else{observer.position.set(14,12,13);orbit.target.set(0,3,-12);}}
 else if(view==='top'){observer.position.set(.6,12,1.6);orbit.target.set(.6,.5,1.59);}else{observer.position.set(4.9,4.2,6.2);orbit.target.set(.35,.8,-.35);}orbit.update();
}
function setView(mode){view=mode;orbit.enabled=mode!=='camera';$('viewModes').querySelectorAll('button').forEach(b=>{b.classList.toggle('active',b.dataset.view===mode);b.setAttribute('aria-pressed',String(b.dataset.view===mode));});if(mode!=='camera')frameStage();$('worldLabel').innerHTML=mode==='camera'?'<i></i>摄影机视角 · 与右侧监看一致':mode==='top'?'<i></i>俯视布置 · 查看位置与运动轨迹':'<i></i>自由观察 · 不影响拍摄机位';$('worldHint').hidden=mode==='camera';$('enterCamera').textContent=mode==='camera'?'返回空间总览 ↗':'放大摄影机画面 ↗';refreshEditor();draw();}
function cameraPose(){const p=sampleCamera(shot(),time);filmCam.aspect=ratio();filmCam.position.fromArray(p.p);filmCam.up.set(0,1,0);filmCam.setFocalLength(p.lens);filmCam.lookAt(...p.target);filmCam.updateProjectionMatrix();filmCam.updateMatrixWorld(true);if(!dragging){cameraRig.position.copy(filmCam.position);targetRig.position.fromArray(p.target);}cameraRig.quaternion.copy(filmCam.quaternion);
 proxyCam.position.copy(filmCam.position);proxyCam.quaternion.copy(filmCam.quaternion);proxyCam.fov=filmCam.fov;proxyCam.aspect=filmCam.aspect;proxyCam.updateProjectionMatrix();proxyCam.updateMatrixWorld(true);frustum.update();
 lookLine.geometry.dispose();lookLine.geometry=new T.BufferGeometry().setFromPoints([filmCam.position,targetRig.position]);lookLine.computeLineDistances();
 $('monitorLens').textContent=p.lens.toFixed(0)+' mm';$('cameraTelemetry').textContent=`CAM  ${p.p.map(v=>v.toFixed(2)).join('  ')}\n焦距 ${p.lens.toFixed(0)} mm · ${tc(time)}`;$('cameraTelemetry').style.whiteSpace='pre';
 $('filmCanvas').dataset.position=p.p.map(n=>n.toFixed(4)).join(',');$('filmCanvas').dataset.target=p.target.map(n=>n.toFixed(4)).join(',');$('filmCanvas').dataset.lens=p.lens.toFixed(3);return p;}
function ratio(){const [w,h]=project.aspect.split(':').map(Number);return w/h;}
function fit(w,h,aspect){let width=w,height=w/aspect;if(height>h){height=h;width=h*aspect;}return {x:(w-width)/2,y:(h-height)/2,w:width,h:height};}
function resizeRenderer(r,element){const w=Math.max(1,element.clientWidth),h=Math.max(1,element.clientHeight),size=new T.Vector2();r.getSize(size);if(size.x!==w||size.y!==h)r.setSize(w,h,false);return {w,h};}
function renderBox(r,cam,element,aspect=null){const {w,h}=resizeRenderer(r,element);r.setScissorTest(false);r.setViewport(0,0,w,h);r.setClearColor('#080d10',1);r.clear();const rect=aspect?fit(w,h,aspect):{x:0,y:0,w,h};r.setViewport(rect.x,rect.y,rect.w,rect.h);r.setScissor(rect.x,rect.y,rect.w,rect.h);r.setScissorTest(true);r.render(scene,cam);r.setScissorTest(false);return rect;}
function guide(el,rect,parent){el.hidden=!$('guides').checked;if(rect){el.style.left=rect.x+'px';el.style.top=(parent.clientHeight-rect.y-rect.h)+'px';el.style.width=rect.w+'px';el.style.height=rect.h+'px';}}
function updateLabels(){for(const a of project.actors){const el=labels.get(a.id);el.hidden=view==='camera'||shot().space!=='hall';if(el.hidden)continue;const pos=stage.actors.get(a.id).headPoint.clone().project(observer);el.hidden=pos.z>1||pos.z<-1||Math.abs(pos.x)>1||Math.abs(pos.y)>1;if(!el.hidden){el.style.left=(pos.x*.5+.5)*$('worldView').clientWidth+'px';el.style.top=(-pos.y*.5+.5)*$('worldView').clientHeight+'px';}}
 const cp=cameraRig.position.clone().add(new T.Vector3(0,.23,0)).project(observer);camLabel.hidden=view==='camera'||cp.z>1||cp.z<-1||Math.abs(cp.x)>1||Math.abs(cp.y)>1;camLabel.style.left=(cp.x*.5+.5)*$('worldView').clientWidth+'px';camLabel.style.top=(-cp.y*.5+.5)*$('worldView').clientHeight+'px';}
function draw(){
 stage.update(project,time,shot().space,shot().id);cameraPose();updateAxis();orbit.update();observer.aspect=$('worldView').clientWidth/$('worldView').clientHeight;observer.updateProjectionMatrix();
 helpers.visible=view!=='camera';grid.visible=$('showGrid').checked&&shot().space==='hall';pathLine.visible=pathMarkers.visible=$('showPath').checked;frustum.visible=lookLine.visible=$('showFrustum').checked;
 worldRenderer.clippingPlanes=view==='top'&&shot().space==='hall'?[ceilingClip]:[];
 lastWorldRect=renderBox(worldRenderer,view==='camera'?filmCam:observer,$('worldView'),view==='camera'?ratio():null);helpers.visible=false;
 lastFilmRect=renderBox(filmRenderer,filmCam,$('monitor'),ratio());helpers.visible=true;
 guide($('safeGuide'),lastFilmRect,$('monitor'));if(view==='camera')guide($('bigGuide'),lastWorldRect,$('worldView'));else $('bigGuide').hidden=true;updateLabels();
}
let workspaceVisible=true;window.addEventListener("workspacevisibility",e=>{workspaceVisible=e.detail.visible;if(!workspaceVisible){pause();if(saveTimer)save();}});
function loop(stamp){requestAnimationFrame(loop);if(!workspaceVisible){lastStamp=stamp;return;}if(playing){const dt=Math.min((stamp-lastStamp)/1000,.12)*Number($('speed').value);let next=time+dt;if(singlePreview||$('loop').checked){const s=shot();if(next>=s.end){if($('loop').checked)next=s.start+(next-s.end)%(s.end-s.start);else{next=s.end;pause();}}setTime(next,true);}else{if(next>=DURATION){next=DURATION;pause();}setTime(next);}}lastStamp=stamp;draw();}
function initLists(){
 $('shotList').replaceChildren(...project.shots.map((s,i)=>{const b=document.createElement('button');b.className='shot-card';b.dataset.shot=i;b.style.setProperty('--shot',s.color);const num=document.createElement('span');num.className='num';num.textContent=String(i+1).padStart(2,'0');const details=document.createElement('div'),title=document.createElement('strong'),meta=document.createElement('small');title.textContent=s.name;meta.textContent=`${s.start.toFixed(0)}—${s.end.toFixed(0)}s · ${s.move.split(' / ')[0]}`;details.append(title,meta);if(s.space==='vision'){const tag=document.createElement('span');tag.className='tag';tag.textContent='异象空间';details.append(tag);}b.append(num,details);b.onclick=()=>selectShot(i);return b;}));
 $('shotTrack').replaceChildren(...project.shots.map((s,i)=>{const b=document.createElement('button');b.dataset.shot=i;b.className='shot-clip';b.style.setProperty('--shot',s.color);b.style.width=((s.end-s.start)/DURATION*100)+'%';b.textContent=s.id+' '+s.name;const small=document.createElement('small');small.textContent=(s.end-s.start).toFixed(1)+'s';b.append(small);b.onclick=()=>selectShot(i);return b;}));
 $('ruler').replaceChildren(...Array.from({length:16},(_,i)=>{const s=document.createElement('span');s.textContent=String(i).padStart(2,'0')+'s';return s;}));$('aspect').value=project.aspect;
}
for(const [i,id] of ['posX','posY','posZ'].entries()){let editingInput=false;$(id).onfocus=()=>{editingInput=false;pause();};$(id).oninput=()=>{const value=Number($(id).value);if(!Number.isFinite(value)||Math.abs(value)>200||$(id).value==='')return;if(!editingInput){checkpoint();editingInput=true;}const isCam=['camera','target'].includes(edit);if(isCam){const p=sampleCamera(shot(),time);p[edit==='camera'?'p':'target'][i]=value;if(Math.hypot(...p.p.map((v,n)=>v-p.target[n]))<.02)return;upsertKey(shot(),time,p);markPresetEdited();selectedKey=keyAt(shot(),time);}else project.actors.find(a=>a.id===edit).p[i]=value;rebuildPath();refreshEditor();dirty();};}
for(const id of ['lens','yaw']){$(id).onpointerdown=()=>{checkpoint();pause();};$(id).onkeydown=()=>{checkpoint();pause();};}
 $('lens').oninput=()=>{const p=sampleCamera(shot(),time);p.lens=Number($('lens').value);upsertKey(shot(),time,p);markPresetEdited();selectedKey=keyAt(shot(),time);refreshEditor();dirty();};
 $('yaw').oninput=()=>{project.actors.find(a=>a.id===edit).yaw=Number($('yaw').value);$('yawValue').textContent=$('yaw').value+'°';dirty();};
 $('ease').onchange=()=>change(()=>{shot().ease=$('ease').value;markPresetEdited();});
 $('aspect').onchange=()=>{change(()=>project.aspect=$('aspect').value);refreshPresetCandidate();};
 $('editTarget').onchange=()=>{pause();edit=$('editTarget').value;refreshEditor();};
 $('addKey').onclick=()=>change(()=>{upsertKey(shot(),time,sampleCamera(shot(),time));markPresetEdited();selectedKey=keyAt(shot(),time);});
 $('deleteKey').onclick=()=>{if(selectedKey>0&&selectedKey<shot().keys.length-1)change(()=>{shot().keys.splice(selectedKey,1);markPresetEdited();selectedKey=-1;});};
 $('captureView').onclick=()=>{if(view==='camera')return;change(()=>{const distance=observer.position.distanceTo(orbit.target),frameHeight=2*distance*Math.tan(T.MathUtils.degToRad(observer.fov)/2),filmFov=T.MathUtils.radToDeg(2*Math.atan(frameHeight/(2*distance)));const f=new T.PerspectiveCamera(filmFov,ratio());const pose={p:observer.position.toArray(),target:orbit.target.toArray(),lens:clamp(f.getFocalLength(),18,100)};upsertKey(shot(),time,pose);markPresetEdited();selectedKey=keyAt(shot(),time);});notify('观察视角已写入 '+shot().id+' 的 '+time.toFixed(2)+' 秒关键帧');};
 $('resetShot').onclick=()=>change(()=>{presetBackups.delete(shot().id);project.shots[shotIndex]=(project.directionVersion===DIRECTION_VERSION?createDirectedProject(project):createProject()).shots[shotIndex];selectedKey=keyAt(shot(),time);refreshShots();});
 $('undo').onclick=()=>{if(!undoStack.length)return;pause();presetBackups.clear();project=JSON.parse(undoStack.pop());initLists();onShotChanged();$('undo').disabled=!undoStack.length;dirty();notify('已撤销上一次编辑');};
 $('viewModes').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.view));$('frameStage').onclick=()=>{if(view==='camera')setView('free');else frameStage();};$('enterCamera').onclick=()=>setView(view==='camera'?'free':'camera');
 $('play').onclick=()=>{if(playing){pause();refreshEditor();}else play();};$('rewind').onclick=()=>{pause();setTime(0);};$('scrubber').oninput=()=>{pause();setTime(Number($('scrubber').value));};
 let scrubbing=false;$('timelineTracks').addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;scrubbing=true;$('timelineTracks').setPointerCapture(e.pointerId);pause();scrub(e);});$('timelineTracks').addEventListener('pointermove',e=>{if(scrubbing)scrub(e);});$('timelineTracks').addEventListener('pointerup',()=>scrubbing=false);function scrub(e){const r=$('timelineTracks').getBoundingClientRect();setTime((e.clientX-r.left)/r.width*DURATION);}
 document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)||e.ctrlKey||e.metaKey)return;if(e.code==='Space'){e.preventDefault();$('play').click();}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();pause();setTime(time+(e.key==='ArrowLeft'?-1:1)/FPS);}else if(e.key.toLowerCase()==='c')setView(view==='camera'?'free':'camera');});
 const pickRay=new T.Raycaster();let pointerStart;
 $('worldCanvas').addEventListener('pointerdown',e=>{pointerStart=[e.clientX,e.clientY];});$('worldCanvas').addEventListener('pointerup',e=>{if(!pointerStart||Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>4||view==='camera'||gizmo.axis)return;const r=$('worldCanvas').getBoundingClientRect();pickRay.setFromCamera(new T.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),observer);const objects=[cameraRig,targetRig,pathMarkers,...(shot().space==='hall'?[...stage.actors.values()].map(a=>a.root):[])];const hits=pickRay.intersectObjects(objects,true);if(!hits.length)return;let obj=hits[0].object;if(obj.userData.key!==undefined){pause();setTime(shot().keys[obj.userData.key].t,true);return;}let target=obj.userData.pick;while(obj&&!target){if(obj.userData.actorId)target=obj.userData.actorId;obj=obj.parent;}if(target){pause();edit=target;$('editTarget').value=edit;refreshEditor();}});
 function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),10000);}
 $('exportProject').onclick=()=>{save();download(new Blob([JSON.stringify({...project,exportedAt:new Date().toISOString(),referenceMap:{ye:'叶宇风格图.png / 大师兄四视图脸部模糊.png',shi:'师心水风格图.png / 师心水四视图脸部模糊.png',feng:'封不平风格图.png / 封不平四视图脸部模糊.png'},status:'previsualization-not-final-video'},null,2)],{type:'application/json'}),'探查神体-导演工程.json');notify('导演工程已生成，包含机位、注视点、焦距、关键帧与角色位置');};
 $('importProject').onclick=()=>$('importFile').click();$('importFile').onchange=async()=>{try{const file=$('importFile').files[0];if(!file)return;if(file.size>1e6)throw Error('工程文件超过 1 MB');const p=validateProject(JSON.parse(await file.text()));checkpoint();pause();presetBackups.clear();project=p;initLists();selectShot(0);dirty();notify('工程已导入');}catch(e){notify('无法导入：'+e.message);}finally{$('importFile').value='';}};
 $('snapshot').onclick=()=>{pause();draw();const canvas=document.createElement('canvas'),width=project.aspect==='9:16'?1080:1920,height=Math.round(width/ratio()),exporter=makeRenderer(canvas);exporter.setPixelRatio(1);exporter.setSize(width,height,false);helpers.visible=false;exporter.render(scene,filmCam);helpers.visible=true;const filename=shot().id+'-'+time.toFixed(2)+'s.png';canvas.toBlob(blob=>{exporter.dispose();exporter.forceContextLoss();if(blob){download(blob,filename);notify('已生成 '+width+'×'+height+' 当前摄影机画面');}else notify('图片导出失败');},'image/png');};

function markPresetEdited(){if(shot().preset)shot().preset.modified=true;}
function presetOptions(){return {id:$('presetType').value,target:$('presetSubject').value,framing:$('presetFraming').value,amount:$('presetAmount').value,direction:Number($('presetDirection').value)};}
function initPresets(){
 let group;
 for(const p of PRESETS){if(group?.label!==p.group){group=document.createElement('optgroup');group.label=p.group;$('presetType').append(group);}const option=document.createElement('option');option.value=p.id;option.textContent=p.name;group.append(option);}
 for(const id of ['presetType','presetSubject','presetFraming','presetAmount','presetDirection'])$(id).onchange=()=>{pause();if(id==='presetType'&&$('presetType').value==='follow'&&shot().space==='hall')$('presetSubject').value='shi';refreshPresetCandidate();};
 $('applyPreset').onclick=applyPreset;
 $('replayPreset').onclick=()=>{pause();setTime(shot().start,true);setView('camera');play(true);showPreview();};
 $('restorePreset').onclick=()=>{const old=presetBackups.get(shot().id);if(!old)return;checkpoint();pause();project.shots[shotIndex]=structuredClone(old);presetBackups.delete(old.id);time=old.start;selectedKey=0;initLists();onShotChanged();updateTimeUI();dirty();draw();notify('已恢复套用前的 '+old.id+' 机位');};
 $('backToPresets').onclick=()=>{pause();$('presetType').focus();$('presetType').scrollIntoView({block:'center',behavior:'smooth'});};
}
function syncPresetForm(){
 const r=shot().preset,vision=shot().space==='vision';
 for(const option of $('presetType').options){const p=getPreset(option.value);option.disabled=vision&&(p.hallOnly||['two-shot','follow'].includes(p.id));}
 const id=r?.id||'push';$('presetType').value=getPreset(id)&&!Array.from($('presetType').options).find(o=>o.value===id).disabled?id:'push';
 $('presetSubject').value=vision?'vision':r?.target||'pair';$('presetFraming').value=r?.framing||'medium';$('presetAmount').value=r?.amount||'normal';$('presetDirection').value=String(r?.direction||1);
 refreshPresetCandidate();
}
function refreshPresetStatus(){
 const r=shot().preset,def=getPreset(r?.id),stale=r&&(r.aspect!==project.aspect||r.actorSignature!==actorSignature(project));
 $('presetApplied').textContent=def?'当前：'+def.name+(stale?' · 人物或画幅已变，请重新套用':r.modified?' · 已手动调整':' · 已套用'):'当前：原始导演机位';
 $('presetScope').textContent=shot().id+' · '+(shot().end-shot().start)+' 秒 · 仅替换本镜头';
 $('restorePreset').disabled=!presetBackups.has(shot().id);
}
function refreshPresetCandidate(){
 const p=getPreset($('presetType').value);if(!p)return;
 const vision=shot().space==='vision';
 for(const o of $('presetSubject').options)o.disabled=vision?o.value!=='vision':o.value==='vision';
 if(vision)$('presetSubject').value='vision';else if(p.forcedTarget)$('presetSubject').value=p.forcedTarget;else if($('presetSubject').value==='vision')$('presetSubject').value='pair';
 $('presetSubject').disabled=vision||!!p.forcedTarget;
 $('presetDirection').disabled=!p.direction;
 $('presetDirection').options[0].textContent=p.direction==='vertical'?'向上':'向右 / 顺时针';$('presetDirection').options[1].textContent=p.direction==='vertical'?'向下':'向左 / 逆时针';
 $('presetAmount').disabled=['locked','two-shot','ots-ye','ots-shi','follow','orbit'].includes(p.id);
 $('presetEnglish').textContent=p.en;$('presetDescription').textContent=p.description;
 try{presetCandidate=makePreset(project,shot(),presetOptions());$('applyPreset').disabled=false;const {stats,notes}=presetCandidate;$('presetStats').textContent=stats.pathLength.toFixed(2)+' m · '+Math.round(stats.lensStart)+' → '+Math.round(stats.lensEnd)+' mm';$('presetNotice').textContent=notes.join(' ');drawPresetMap(presetCandidate);}
 catch(e){presetCandidate=null;$('applyPreset').disabled=true;$('presetNotice').textContent=e.message;$('presetStats').textContent='请调整拍摄设置';$('presetMap').replaceChildren();}
 refreshPresetStatus();
}
function drawPresetMap(candidate){
 const svg=$('presetMap'),ns='http://www.w3.org/2000/svg',keys=candidate.keys,positions=[...keys.map(k=>k.p),...candidate.marks.map(a=>a.p),keys[0].target];
 let minX=Math.min(...positions.map(p=>p[0])),maxX=Math.max(...positions.map(p=>p[0])),minZ=Math.min(...positions.map(p=>p[2])),maxZ=Math.max(...positions.map(p=>p[2]));
 const extent=Math.max(maxX-minX,maxZ-minZ,1),factor=76/extent,cx=(minX+maxX)/2,cz=(minZ+maxZ)/2;
 const point=p=>[110+(p[0]-cx)*factor,50+(p[2]-cz)*factor];
 const el=(name,attrs)=>{const n=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));svg.append(n);return n;};svg.replaceChildren();
 el('path',{d:keys.map((k,i)=>(i?'L':'M')+point(k.p).map(n=>n.toFixed(2)).join(',')).join(' '),fill:'none',stroke:'#efb77e','stroke-width':1.8});
 const start=point(keys[0].p),target=point(keys[0].target);el('line',{x1:start[0],y1:start[1],x2:target[0],y2:target[1],stroke:'#869991','stroke-dasharray':'3 3'});
 for(const a of candidate.marks){const [cx,cy]=point(a.p);el('circle',{cx,cy,r:4,fill:a.color});}
 const [tx,ty]=target;el('path',{d:`M${tx-3},${ty}h6 M${tx},${ty-3}v6`,stroke:'#d7dfcf','stroke-width':1});
 keys.filter((_,i)=>i===0||i===keys.length-1).forEach((k,i)=>{const [cx,cy]=point(k.p);el('circle',{cx,cy,r:i?2.8:4,fill:i?'#f3b17c':'#c1dea5'});});
}
function applyPreset(){
 // Recompute here: staged options may have been chosen before an actor was moved.
 let result;try{result=makePreset(project,shot(),presetOptions());}catch(e){notify(e.message);return;}
 checkpoint();pause();presetBackups.set(shot().id,structuredClone(shot()));
 Object.assign(shot(),{keys:result.keys,ease:result.ease,move:result.move,preset:result.preset});
 time=shot().start;selectedKey=0;edit='camera';$('editTarget').value=edit;
 initLists();onShotChanged();updateTimeUI();setView('camera');dirty();play(true);showPreview();
 notify(getPreset(result.preset.id).name+' 已套用到 '+shot().id+'，正在预演 '+(shot().end-shot().start)+' 秒');
}
function showPreview(){const box=$('worldView').getBoundingClientRect();if(box.bottom>innerHeight||box.top<0)$('worldView').scrollIntoView({block:'center',behavior:'smooth'});}

function refreshTakeControls(){
 const designed=project.directionVersion===DIRECTION_VERSION;
 $('designedTake').setAttribute('aria-pressed',String(designed));$('beforeTake').setAttribute('aria-pressed',String(!designed));$('beforeTake').disabled=!takes.before;
 $('takeStatus').textContent=designed?'导演新版 · 六镜头设计':'改版前 · 当前工程';
}
function selectTake(target){
 const current=project.directionVersion===DIRECTION_VERSION?'designed':'before';
 if(target===current&&target==='designed'){setTime(0);setView('camera');return;}
 const next={...takes,[current]:structuredClone(project)};
 if(!next[target]){if(target==='before')return;next.designed=createDirectedProject(project);}
 try{localStorage.setItem(TAKE_STORE,JSON.stringify(next));}catch{notify('未能保存对比备份；请先导出当前工程，再重试');return;}
 checkpoint();pause();clearTimeout(saveTimer);takes=next;project=validateProject(structuredClone(takes[target]));presetBackups.clear();initLists();selectShot(0);setView('camera');save();
 notify(target==='designed'?'已套用六镜头导演新版；点击播放查看完整 15 秒':'已回到改版前；新版保留，可随时切换比较');
}
 $('designedTake').onclick=()=>selectTake('designed');$('beforeTake').onclick=()=>selectTake('before');

 window.addEventListener('beforeunload',()=>{if(saveTimer)save();});
 window.addEventListener('error',e=>{if(!$('loading').hidden)$('loading').textContent='载入失败：'+e.message;});
 function updateRigLabels(){const p=rigPreferences();document.querySelectorAll('[data-rig-label]').forEach(el=>el.textContent=p[el.dataset.rigLabel].heads+' 头身');}
 $('loading').textContent='正在载入动漫白模…';
 try{await stage.ready;}catch(e){$('loading').textContent='白模载入失败：'+e.message;throw e;}
 updateRigLabels();window.addEventListener('storage',async e=>{if(e.key!==RIG_STORE)return;try{await stage.refreshRigs();updateRigLabels();draw();notify('人物白模已更新');}catch(e){notify('人物白模更新失败：'+e.message);}});
 initPresets();initLists();onShotChanged();frameStage();updateTimeUI();$('undo').disabled=true;$('loading').hidden=true;$('worldCanvas').dataset.ready='true';draw();requestAnimationFrame(loop);if(restoreError)notify(restoreError);

$('motionMode').value=project.motionVersion==='legacy'?'legacy':'natural';
$('motionMode').onchange=()=>{project.motionVersion=$('motionMode').value;dirty();draw();};
$('previewReaction').onclick=()=>{pause();setTime(11.6);$('loop').checked=false;play(false);};
