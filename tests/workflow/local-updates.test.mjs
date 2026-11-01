import test from 'node:test';
import assert from 'node:assert/strict';
import {mountLocalUpdates} from '../../scripts/browser/local-updates.mjs';

function surface(){
 const nodes=[];
 const doc={createElement(tag){
  const node={tag,children:[],handlers:{},hidden:false,disabled:false,textContent:'',
   setAttribute(){},append(...items){this.children.push(...items);},remove(){this.removed=true;},
   addEventListener(event,fn){this.handlers[event]=fn;}};
  nodes.push(node);return node;
 }};
 const root={ownerDocument:doc,append(){}};
 return {root,nodes,button:label=>nodes.find(n=>n.tag==='button'&&n.textContent===label)};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const ready={enabled:true,status:'ready',canInstall:true,message:'已准备',latestVersion:'0.3.0-preview.5'};

test('workspace teardown stops the updater even when its status request resolves late',async()=>{
 const ui=surface();let resolve,calls=0;
 const mounted=mountLocalUpdates({root:ui.root,api:{request(){calls++;return new Promise(r=>resolve=r);}}});
 mounted.unmount();resolve(ready);await tick();
 assert.equal(calls,1);assert.equal(ui.nodes[0].removed,true);
 assert.equal(ui.nodes.find(n=>n.tag==='span').textContent,'');
});

test('installation preserves the active-work gate before calling the server',async()=>{
 const ui=surface(),calls=[];let handoff=false;
 const mounted=mountLocalUpdates({root:ui.root,api:{async request(path){calls.push(path);return ready;}},
  saveDraft:async()=>({saved:true}),getSafetyState:async()=>({activeTasks:1}),onInstalling:()=>{handoff=true;}});
 await tick();await ui.button('保存并安装更新').handlers.click();
 assert.deepEqual(calls,['/local-runtime/update']);assert.equal(handoff,false);
 assert.match(ui.nodes.find(n=>n.tag==='span').textContent,/运行中的任务/);mounted.unmount();
});

test('checking stays disabled while the server checks and failed checks remain visible',async()=>{
 const ui=surface();let failed=false;
 const mounted=mountLocalUpdates({root:ui.root,api:{async request(path){
  if(path.endsWith('/check')){if(failed)throw new Error('更新源不可读');return {...ready,status:'checking',canInstall:false};}
  return ready;
 }}});
 await tick();await ui.button('检查更新').handlers.click();
 assert.equal(ui.button('检查更新').disabled,true);
 failed=true;await ui.button('检查更新').handlers.click();
 assert.match(ui.nodes.find(n=>n.tag==='span').textContent,/更新源不可读/);mounted.unmount();
});
