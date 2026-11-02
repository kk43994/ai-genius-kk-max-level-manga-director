import test from 'node:test';
import assert from 'node:assert/strict';
import {frameRenderer} from '../../frontend/workflow/frame-renderer.js';

function clock() {
  let serial=0;
  const pending=new Map();
  return {
    requestAnimationFrame(fn) {const id=serial++;pending.set(id,fn);return id;},
    cancelAnimationFrame(id) {pending.delete(id);},
    tick() {const callbacks=[...pending.values()];pending.clear();callbacks.forEach(fn=>fn());},
    get pending() {return pending.size;},
  };
}

test('a burst of pointer moves paints the latest position once per frame',()=>{
  const window=clock(),painted=[];let position=0;
  const frames=frameRenderer(window,()=>painted.push(position));
  for(let i=1;i<=120;i++){position=i;frames.request();}
  assert.equal(window.pending,1);assert.deepEqual(painted,[]);
  window.tick();assert.deepEqual(painted,[120]);
  position=121;frames.request();window.tick();assert.deepEqual(painted,[120,121]);
});

test('pointer release flushes the final position and cancels the queued paint',()=>{
  const window=clock();let paints=0;
  const frames=frameRenderer(window,()=>paints++);
  frames.request();frames.flush();assert.equal(paints,1);assert.equal(window.pending,0);
  window.tick();assert.equal(paints,1);
});

test('refresh cancels the previous canvas frame and unmount leaves no paint behind',()=>{
  const window=clock();let paints=0;
  const frames=frameRenderer(window,()=>paints++);
  frames.request();frames.cancel();window.tick();assert.equal(paints,0);
  frames.request();frames.dispose();window.tick();frames.request();frames.flush();
  assert.equal(paints,0);assert.equal(window.pending,0);
});
