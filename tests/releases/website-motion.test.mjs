import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source = readFileSync(new URL('../../local_client/website/stage.js', import.meta.url), 'utf8');
function scene(reduce = false, width = 1440, coarse = false) {
  const eventSource = () => ({events: new Map(), addEventListener(name, fn) { this.events.set(name, fn); }, emit(name, event = {}) { this.events.get(name)?.(event); }});
  const nodes = new Map();
  for (const selector of ['#film-stage','.art-camera','.hero','.paper-story','.hero-intro','.camera-caption','#motion-toggle','.iris-frame','.cinema-shade','.shot-indicator small','.film-upper','.film-lower','.film-dust']) {
    nodes.set(selector, {...eventSource(), style:{}, dataset:{}, attrs:{}, offsetHeight:selector === '.hero' ? 1200 : 2000, setAttribute(k,v){this.attrs[k]=v;}, classList:{toggle(){}}});
  }
  const document = {...eventSource(), hidden:false, documentElement:{dataset:{}}, querySelector:s=>nodes.get(s), querySelectorAll:()=>[], dispatchEvent(event){this.emit(event.type,event);}};
  const media = {...eventSource(), matches:reduce};
  const touch = {...eventSource(), matches:coarse};
  const window = eventSource();
  let id = 0, ms = 0;
  const frames = new Map();
  const context = {document,window,innerWidth:width,innerHeight:700,scrollY:0,matchMedia:q=>q.includes('prefers-reduced-motion')?media:touch,Math,CustomEvent:class{constructor(type, init){this.type=type;Object.assign(this,init);}},requestAnimationFrame(fn){frames.set(++id,fn);return id;},cancelAnimationFrame(id){frames.delete(id);}};
  runInNewContext(source, context);
  return {context,document,window,nodes,frames,media,step(){ms+=16;const work=[...frames.values()];frames.clear();work.forEach(fn=>fn(ms));},scroll(y){context.scrollY=y;window.emit('scroll');},pause(){nodes.get('#motion-toggle').emit('click');}};
}
test('pause retains the exact camera and film frame and stops scheduling',()=>{
  const s=scene();s.step();s.scroll(300);for(let i=0;i<40;i++)s.step();
  const camera=s.nodes.get('.art-camera').style.transform,film=s.nodes.get('.film-upper').attrs.transform;
  assert.notEqual(camera,'translate3d(0%,0%,0) scale(1) rotateY(0deg) rotateX(0deg)');
  s.pause();s.step();assert.equal(s.nodes.get('.art-camera').style.transform,camera);assert.equal(s.nodes.get('.film-upper').attrs.transform,film);assert.equal(s.frames.size,0);
  s.scroll(400);s.step();assert.equal(s.nodes.get('.art-camera').style.transform,camera);assert.equal(s.frames.size,0);
  s.pause();s.step();s.step();assert.equal(s.frames.size,1);assert.notEqual(s.nodes.get('.art-camera').style.transform,camera);
});
test('opaque content stops drawing; returning to the stage restarts one loop',()=>{
  const s=scene();s.step();s.scroll(3300);s.step();assert.equal(s.frames.size,0);
  s.scroll(200);s.step();assert.equal(s.frames.size,1);
});
test('background and bfcache suspend and resume without duplicate loops',()=>{
  const s=scene();s.step();s.document.hidden=true;s.document.emit('visibilitychange');assert.equal(s.frames.size,0);
  s.document.hidden=false;s.document.emit('visibilitychange');s.window.emit('pageshow');assert.equal(s.frames.size,1);
  s.window.emit('pagehide');assert.equal(s.frames.size,0);s.window.emit('pageshow');s.window.emit('pageshow');assert.equal(s.frames.size,1);
});
test('system reduced motion is static and remains authoritative',()=>{
  const s=scene(true);s.step();assert.equal(s.frames.size,0);assert.equal(s.nodes.get('#motion-toggle').disabled,true);
  assert.equal(s.nodes.get('.hero-intro').style.opacity,'1');assert.equal(s.document.documentElement.dataset.motion,'paused');
  s.media.matches=false;s.media.emit('change');s.step();assert.equal(s.nodes.get('#motion-toggle').disabled,false);assert.equal(s.frames.size,1);
});
test('a manual pause is preserved across changes to system motion preferences',()=>{
  const s=scene();s.step();s.pause();s.step();s.media.matches=true;s.media.emit('change');s.step();s.media.matches=false;s.media.emit('change');s.step();assert.equal(s.frames.size,0);assert.equal(s.document.documentElement.dataset.motion,'paused');
});
test('mobile idle yields JS while scroll settles without repainting SVG layers',()=>{
  const s=scene(false,390);s.step();assert.equal(s.frames.size,0);
  const stage=s.nodes.get('#film-stage'),camera=s.nodes.get('.art-camera');
  assert.equal(stage.dataset.render,'light');assert.equal(stage.dataset.playing,'true');
  const opening=camera.style.transform;
  s.scroll(180);for(let i=0;i<100;i++)s.step();
  assert.notEqual(camera.style.transform,opening);assert.equal(s.frames.size,0);
  assert.equal(s.nodes.get('.film-upper').attrs.transform,undefined);
  assert.equal(s.nodes.get('.film-lower').attrs.transform,undefined);
  assert.equal(s.nodes.get('.film-dust').attrs.transform,undefined);
  assert.equal(s.nodes.get('.iris-frame').style.clipPath,'none');
  s.pause();s.step();const frozen=camera.style.transform;
  assert.equal(stage.dataset.playing,'false');s.scroll(250);s.step();
  assert.equal(camera.style.transform,frozen);assert.equal(s.frames.size,0);
  s.pause();for(let i=0;i<100;i++)s.step();assert.notEqual(camera.style.transform,frozen);assert.equal(s.frames.size,0);
});
test('mobile ambient motion suspends offscreen, in background and across page history',()=>{
  const s=scene(false,390);const stage=s.nodes.get('#film-stage');s.step();
  s.scroll(1200);s.step();assert.equal(stage.dataset.playing,'false');assert.equal(stage.dataset.covered,'true');assert.equal(s.frames.size,0);
  s.scroll(0);s.step();assert.equal(stage.dataset.playing,'true');assert.equal(stage.dataset.covered,'false');
  s.document.hidden=true;s.document.emit('visibilitychange');assert.equal(stage.dataset.playing,'false');
  s.document.hidden=false;s.document.emit('visibilitychange');s.step();assert.equal(stage.dataset.playing,'true');
  s.window.emit('pagehide');assert.equal(stage.dataset.playing,'false');
  s.window.emit('pageshow');s.step();assert.equal(stage.dataset.playing,'true');
});
test('touch tablets use the light renderer; resizing restores the desktop film',()=>{
  const tablet=scene(false,1024,true);tablet.step();assert.equal(tablet.frames.size,0);assert.equal(tablet.nodes.get('#film-stage').dataset.render,'light');
  const s=scene(false,760);s.step();assert.equal(s.frames.size,0);
  s.context.innerWidth=1440;s.window.emit('resize');s.step();
  assert.equal(s.nodes.get('#film-stage').dataset.render,'full');assert.equal(s.frames.size,1);
  assert.match(s.nodes.get('.iris-frame').style.clipPath,/polygon/);
  assert.ok(s.nodes.get('.film-upper').attrs.transform);
});
