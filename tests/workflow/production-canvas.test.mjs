import test from 'node:test';
import assert from 'node:assert/strict';
import {clampZoom,zoomAt,fitView} from '../../frontend/workflow/production-canvas.js';
test('zoom anchors the same world point and stays bounded',()=>{
 const before={x:40,y:20,scale:.8},point={x:230,y:170};
 const next=zoomAt(before,1.2,point);
 assert.ok(Math.abs((point.x-next.x)/next.scale-(point.x-before.x)/before.scale)<1e-9);
 assert.ok(Math.abs((point.y-next.y)/next.scale-(point.y-before.y)/before.scale)<1e-9);
 assert.equal(clampZoom(0),.12);assert.equal(clampZoom(10),1.6);
});
test('fit view keeps the full plan within the viewport when scale range allows it',()=>{
 const view=fitView(1200,700,1800,900);
 assert.ok(view.x>=24&&view.y>=24);
 assert.ok(view.x+1800*view.scale<=1200);
 assert.ok(view.y+900*view.scale<=700);
});
