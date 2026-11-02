import test from 'node:test';
import assert from 'node:assert/strict';
import {fitStoryView,storyLayout,storyWorkflowLayout} from '../../frontend/workflow/story-canvas.js';
test('fit view includes cards moved into negative coordinates and stays centered',()=>{
  const b={x:-900,y:-400,width:1500,height:600},v=fitStoryView(1200,700,b);
  assert.ok(b.x*v.scale+v.x>=31);
  assert.ok((b.x+b.width)*v.scale+v.x<=1169);
  assert.equal((b.x+b.width/2)*v.scale+v.x,600);
  assert.equal((b.y+b.height/2)*v.scale+v.y,350);
});
test('automatic layout preserves supplied story order and leaves room for expanded scenes',()=>{
  const scenes=['third-in-storage','first-in-storage'],before=[...scenes];
  const layout=storyLayout(scenes,['actor'],1000);
  assert.ok(layout['scene:third-in-storage'].x<layout['scene:first-in-storage'].x);
  assert.ok(layout['character:actor'].y>1000);
  assert.deepEqual(scenes,before);
});

test('unified canvas reserves ordered shot slots per scene and a separate multiview area',()=>{
 const rows=[{id:'scene:a'},{id:'scene:b'},{id:'shot:a2',sceneId:'a'},{id:'shot:a1',sceneId:'a'},{id:'shot:b',sceneId:'b'},{id:'character:hero'},{id:'asset:hero:master'}];
 const before=JSON.stringify(rows),layout=storyWorkflowLayout(rows);
 assert.equal(layout['scene:a'].y,layout['shot:a2'].y);
 assert.ok(layout['shot:a2'].x<layout['shot:a1'].x,'saved order is preserved');
 assert.ok(layout['scene:b'].y>=layout['scene:a'].y+1100);
 assert.ok(layout['asset:hero:master'].y>layout['character:hero'].y);
 assert.deepEqual(storyWorkflowLayout(rows.map(r=>r.id==='shot:a1'?{...r,height:800}:r)),layout,'normal portrait arrival fits reserved scene slots without moving them');
 assert.equal(JSON.stringify(rows),before);
});
test('fit includes a long screenplay and its asset rows below the previous zoom limit',()=>{
 const b={x:40,y:70,width:4200,height:7600},v=fitStoryView(1390,548,b);
 assert.ok(v.scale<.12);
 assert.ok(b.x*v.scale+v.x>=31&&b.y*v.scale+v.y>=31);
 assert.ok((b.x+b.width)*v.scale+v.x<=1359&&(b.y+b.height)*v.scale+v.y<=517);
});
