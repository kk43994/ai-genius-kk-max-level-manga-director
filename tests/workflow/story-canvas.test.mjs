import test from 'node:test';
import assert from 'node:assert/strict';
import {fitStoryView,storyLayout} from '../../frontend/workflow/story-canvas.js';
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
