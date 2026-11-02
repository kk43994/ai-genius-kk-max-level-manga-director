import {clampZoom,zoomAt} from './production-canvas.js';

export function fitStoryView(width,height,bounds) {
  const scale=clampZoom(Math.min((width-64)/Math.max(1,bounds.width),(height-64)/Math.max(1,bounds.height),1));
  return {scale,x:(width-bounds.width*scale)/2-bounds.x*scale,y:(height-bounds.height*scale)/2-bounds.y*scale};
}
export function storyLayout(sceneIds,characterIds,sceneBottom=580) {
  return Object.fromEntries([...sceneIds.map((id,i)=>['scene:'+id,{x:40+i*460,y:70}]),...characterIds.map((id,i)=>['character:'+id,{x:40+i*340,y:sceneBottom+100}])]);
}

/** Navigation/layout only. Moving a card never edits screenplay order or invokes a provider. */
export function mountStoryCanvas(root,{storage,storageKey='asset-lab:story-canvas'}={}) {
  const views=new Map(),abort=new AbortController();
  let drag=null,observer=null,saveTimer=null,suppressClickUntil=0;
  const viewport=()=>root.querySelector('[data-story-viewport]');
  const finite=n=>typeof n==='number'&&Number.isFinite(n)&&Math.abs(n)<1e6;
  function current(){const el=viewport();if(!el)return null;return {el,key:el.dataset.storyKey,state:views.get(el.dataset.storyKey)};}
  function nodes(ctx){return [...ctx.el.querySelectorAll('[data-story-node]')];}
  function save(){clearTimeout(saveTimer);const ctx=current();if(!ctx?.state)return;try{storage?.setItem(storageKey+':'+encodeURIComponent(ctx.key),JSON.stringify(ctx.state));}catch{/* Layout is optional; screenplay data is untouched. */}}
  root.ownerDocument.defaultView.addEventListener('beforeunload',save,{signal:abort.signal});
  function draw(){
    const ctx=current();if(!ctx?.state)return;const {view,positions}=ctx.state;
    ctx.el.querySelector('[data-story-stage]').style.transform=`translate(${view.x}px,${view.y}px) scale(${view.scale})`;
    for(const node of nodes(ctx)){const p=positions[node.dataset.storyNode];if(p){node.style.left=p.x+'px';node.style.top=p.y+'px';}}
    ctx.el.style.backgroundPosition=`${view.x}px ${view.y}px`;ctx.el.style.backgroundSize=`${24*view.scale}px ${24*view.scale}px`;
    ctx.el.closest('.story-canvas').querySelector('[data-story-zoom-label]').textContent=Math.round(view.scale*100)+'%';
    const scenes=nodes(ctx).filter(n=>n.dataset.storyNode.startsWith('scene:'));
    const svg=ctx.el.querySelector('[data-story-links]'),ns='http://www.w3.org/2000/svg';svg.replaceChildren();
    for(let i=1;i<scenes.length;i++){
      const from=scenes[i-1],to=scenes[i],a=positions[from.dataset.storyNode],b=positions[to.dataset.storyNode];
      const x1=a.x+from.offsetWidth,y1=a.y+60,x2=b.x,y2=b.y+60,dx=Math.max(35,Math.abs(x2-x1)/2);
      const path=root.ownerDocument.createElementNS(ns,'path');path.setAttribute('d',`M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2-7} ${y2}`);svg.append(path);
      const arrow=root.ownerDocument.createElementNS(ns,'path');arrow.setAttribute('d',`M ${x2-12} ${y2-5} L ${x2-4} ${y2} L ${x2-12} ${y2+5}`);svg.append(arrow);
    }
    saveTimer=setTimeout(save,180);
  }
  function bounds(ctx){const rows=nodes(ctx).map(n=>({...ctx.state.positions[n.dataset.storyNode],width:n.offsetWidth,height:n.offsetHeight}));if(!rows.length)return {x:0,y:0,width:400,height:300};const x=Math.min(...rows.map(r=>r.x)),y=Math.min(...rows.map(r=>r.y));return {x,y,width:Math.max(...rows.map(r=>r.x+r.width))-x,height:Math.max(...rows.map(r=>r.y+r.height))-y};}
  function fit(){const ctx=current();if(!ctx)return;ctx.state.view=fitStoryView(ctx.el.clientWidth,ctx.el.clientHeight,bounds(ctx));draw();}
  function locate(index){const ctx=current();if(!ctx)return;const node=ctx.el.querySelector('#story-scene-'+Number(index));if(!node)return;const p=ctx.state.positions[node.dataset.storyNode],scale=Math.min(1,(ctx.el.clientWidth-48)/node.offsetWidth);ctx.state.view={scale,x:(ctx.el.clientWidth-node.offsetWidth*scale)/2-p.x*scale,y:35-p.y*scale};draw();ctx.el.scrollIntoView({block:'nearest'});}
  function arrange(){const ctx=current();if(!ctx)return;const rows=nodes(ctx),scenes=rows.filter(n=>n.dataset.storyNode.startsWith('scene:')),characters=rows.filter(n=>n.dataset.storyNode.startsWith('character:'));ctx.state.positions=storyLayout(scenes.map(n=>n.dataset.storyNode.slice(6)),characters.map(n=>n.dataset.storyNode.slice(10)),Math.max(500,...scenes.map(n=>n.offsetHeight))+70);draw();fit();}
  function focus(expanded){const ctx=current();if(!ctx)return;ctx.state.expanded=expanded;const shell=ctx.el.closest('.story-canvas');shell.classList.toggle('story-canvas-expanded',expanded);const button=shell.querySelector('[data-story-canvas-command="fullscreen"]');button.setAttribute('aria-pressed',String(expanded));button.textContent=expanded?'退出专注':'专注画布';}
  function command(action){const ctx=current();if(!ctx)return;
    if(action==='fit')return fit();if(action==='arrange')return arrange();if(action==='reset')return locate(0);
    if(action==='fullscreen'){focus(!ctx.state.expanded);return;}
    ctx.state.view=zoomAt(ctx.state.view,ctx.state.view.scale*(action==='in'?1.2:1/1.2),{x:ctx.el.clientWidth/2,y:ctx.el.clientHeight/2});draw();
  }
  function listen(type,fn,options={}){root.addEventListener(type,fn,{...options,signal:abort.signal});}
  listen('click',event=>{
    if(Date.now()<suppressClickUntil&&event.target.closest('[data-story-viewport]')){event.preventDefault();event.stopImmediatePropagation();return;}
    const commandButton=event.target.closest('[data-story-canvas-command]');if(commandButton){event.preventDefault();command(commandButton.dataset.storyCanvasCommand);}
  },{capture:true});
  listen('wheel',event=>{const ctx=current();if(!ctx||!ctx.el.contains(event.target)||event.target.closest('.story-card-detail'))return;event.preventDefault();const rect=ctx.el.getBoundingClientRect();if(event.ctrlKey||event.metaKey){ctx.state.view=zoomAt(ctx.state.view,ctx.state.view.scale*Math.exp(-event.deltaY*.006),{x:event.clientX-rect.left,y:event.clientY-rect.top});}else{ctx.state.view={...ctx.state.view,x:ctx.state.view.x-event.deltaX,y:ctx.state.view.y-event.deltaY};}draw();},{passive:false});
  listen('pointerdown',event=>{
    const ctx=current();if(!ctx||!ctx.el.contains(event.target)||event.button!==0)return;
    const handle=event.target.closest('[data-story-drag]'),node=handle?.closest('[data-story-node]');
    if(!handle&&event.target.closest('[data-story-node]'))return;
    drag={pointer:event.pointerId,startX:event.clientX,startY:event.clientY,view:{...ctx.state.view},node:node?.dataset.storyNode,position:node?{...ctx.state.positions[node.dataset.storyNode]}:null,moved:false};
    ctx.el.setPointerCapture(event.pointerId);ctx.el.classList.add('story-panning');event.preventDefault();
  });
  listen('pointermove',event=>{const ctx=current();if(!ctx||!drag||drag.pointer!==event.pointerId)return;const dx=event.clientX-drag.startX,dy=event.clientY-drag.startY;drag.moved||=Math.abs(dx)+Math.abs(dy)>4;if(drag.node)ctx.state.positions[drag.node]={x:drag.position.x+dx/drag.view.scale,y:drag.position.y+dy/drag.view.scale};else ctx.state.view={...drag.view,x:drag.view.x+dx,y:drag.view.y+dy};draw();});
  const end=()=>{if(drag?.moved)suppressClickUntil=Date.now()+120;viewport()?.classList.remove('story-panning');drag=null;save();};
  listen('pointerup',end);listen('pointercancel',end);
  listen('keydown',event=>{const ctx=current();if(!ctx)return;if(event.key==='Escape'){focus(false);return;}const handle=event.target.closest('[data-story-drag]');if(event.target!==ctx.el&&!handle)return;const deltas={ArrowLeft:[-40,0],ArrowRight:[40,0],ArrowUp:[0,-40],ArrowDown:[0,40]};if(deltas[event.key]){event.preventDefault();const [dx,dy]=deltas[event.key];if(handle){const id=handle.closest('[data-story-node]').dataset.storyNode,p=ctx.state.positions[id];ctx.state.positions[id]={x:p.x+dx,y:p.y+dy};}else{ctx.state.view.x-=dx;ctx.state.view.y-=dy;}draw();}if(!handle&&['+','=','-','0'].includes(event.key)){event.preventDefault();command(event.key==='0'?'fit':event.key==='-'?'out':'in');}});
  return {command,locate,exitFocus:()=>focus(false),refresh(){
    observer?.disconnect();const ctx=current();if(!ctx)return;
    const rows=nodes(ctx),defaults=storyLayout(rows.filter(n=>n.dataset.storyNode.startsWith('scene:')).map(n=>n.dataset.storyNode.slice(6)),rows.filter(n=>n.dataset.storyNode.startsWith('character:')).map(n=>n.dataset.storyNode.slice(10)));
    let state=views.get(ctx.key);if(!state){try{const saved=JSON.parse(storage?.getItem(storageKey+':'+encodeURIComponent(ctx.key))||'null');if(saved&&finite(saved.view?.x)&&finite(saved.view?.y)&&finite(saved.view?.scale)&&saved.view.scale>=.12&&saved.view.scale<=1.6)state=saved;}catch{/* Fresh view for absent or invalid layout. */}}
    const first=!state;state||={view:{x:28,y:28,scale:.85},positions:{}};state.positions=Object.fromEntries(Object.entries(defaults).map(([id,p])=>[id,finite(state.positions?.[id]?.x)&&finite(state.positions?.[id]?.y)?state.positions[id]:p]));views.set(ctx.key,state);focus(Boolean(state.expanded));draw();
    if(first){const fit=fitStoryView(ctx.el.clientWidth,ctx.el.clientHeight,bounds(current()));state.view=fit.scale>=.6?fit:{x:28,y:28,scale:.8};draw();}
    const Resize=root.ownerDocument.defaultView.ResizeObserver;if(Resize){observer=new Resize(()=>draw());rows.forEach(n=>observer.observe(n));}
  },dispose(){save();clearTimeout(saveTimer);observer?.disconnect();abort.abort();}};
}
