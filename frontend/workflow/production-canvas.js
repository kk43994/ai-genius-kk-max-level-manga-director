import {frameRenderer} from './frame-renderer.js';

/** View-only canvas navigation. Never submits work or alters production data. */
export const clampZoom = value => Math.min(1.6,Math.max(.12,value));
export function zoomAt(view,scale,point) {
  const next=clampZoom(scale),ratio=next/view.scale;
  return {scale:next,x:point.x-(point.x-view.x)*ratio,y:point.y-(point.y-view.y)*ratio};
}
export function fitView(width,height,contentWidth,contentHeight) {
  const scale=clampZoom(Math.min((width-64)/contentWidth,(height-64)/contentHeight,1));
  return {scale,x:Math.max(24,(width-contentWidth*scale)/2),y:Math.max(24,(height-contentHeight*scale)/2)};
}
export function mountCanvas(root) {
  const views=new Map(),abort=new AbortController();
  let drag=null,observer=null;
  const frames=frameRenderer(root.ownerDocument.defaultView,paint);
  const viewport=()=>root.querySelector('[data-board-viewport]');
  function current(){const el=viewport();if(!el)return null;const key=el.dataset.boardKey;return {el,key,view:views.get(key)||{x:32,y:32,scale:1}};}
  function draw(view){const ctx=current();if(!ctx)return;views.set(ctx.key,view);frames.request();}
  function paint(){const ctx=current();if(!ctx)return;const {view}=ctx;ctx.el.querySelector('[data-board-stage]').style.transform=`translate(${view.x}px,${view.y}px) scale(${view.scale})`;ctx.el.style.backgroundPosition=`${view.x}px ${view.y}px`;ctx.el.style.backgroundSize=`${Math.max(16,24*view.scale)}px ${Math.max(16,24*view.scale)}px`;root.querySelectorAll('[data-board-zoom-label]').forEach(n=>n.textContent=Math.round(view.scale*100)+'%');}
  function fit(){const ctx=current();if(!ctx)return;draw(fitView(ctx.el.clientWidth,ctx.el.clientHeight,Number(ctx.el.dataset.contentWidth),Number(ctx.el.dataset.contentHeight)));}
  function locate(zone){const ctx=current();if(!ctx)return;const target=[...ctx.el.querySelectorAll('[data-board-zone]')].find(n=>n.dataset.boardZone===zone);if(!target)return;const d=target.dataset,scale=clampZoom(Math.min(1,(ctx.el.clientWidth-64)/Number(d.zoneWidth)));draw({scale,x:Math.max(24,(ctx.el.clientWidth-Number(d.zoneWidth)*scale)/2)-Number(d.zoneX)*scale,y:24-Number(d.zoneY)*scale});}
  function command(action){const ctx=current();if(!ctx)return;if(action==='fit')return fit();if(action==='reset')return draw({x:32,y:32,scale:1});draw(zoomAt(ctx.view,ctx.view.scale*(action==='in'?1.15:1/1.15),{x:ctx.el.clientWidth/2,y:ctx.el.clientHeight/2}));}
  function listen(type,fn,options={}){root.addEventListener(type,fn,{...options,signal:abort.signal});}
  listen('wheel',event=>{
    if(!event.target.closest('[data-board-viewport]'))return;
    const ctx=current();if(!ctx)return;event.preventDefault();
    if(event.ctrlKey||event.metaKey){const rect=ctx.el.getBoundingClientRect();draw(zoomAt(ctx.view,ctx.view.scale*Math.exp(-event.deltaY*.004),{x:event.clientX-rect.left,y:event.clientY-rect.top}));}
    else draw({...ctx.view,x:ctx.view.x-event.deltaX,y:ctx.view.y-event.deltaY});
  },{passive:false});
  listen('pointerdown',event=>{
    const el=event.target.closest('[data-board-viewport]');
    if(!el||event.target.closest('button')||event.button!==0)return;
    const ctx=current();drag={id:event.pointerId,x:event.clientX,y:event.clientY,view:{...ctx.view}};
    el.setPointerCapture(event.pointerId);el.classList.add('is-panning');event.preventDefault();
  });
  listen('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;draw({...drag.view,x:drag.view.x+event.clientX-drag.x,y:drag.view.y+event.clientY-drag.y});});
  const end=()=>{if(!drag)return;viewport()?.classList.remove('is-panning');drag=null;frames.flush();};
  listen('pointerup',end);listen('pointercancel',end);
  listen('keydown',event=>{
    if(!event.target.matches('[data-board-viewport]'))return;
    const ctx=current(),deltas={ArrowLeft:[80,0],ArrowRight:[-80,0],ArrowUp:[0,80],ArrowDown:[0,-80]};
    if(deltas[event.key]){event.preventDefault();draw({...ctx.view,x:ctx.view.x+deltas[event.key][0],y:ctx.view.y+deltas[event.key][1]});}
    if(['+','=','-','0'].includes(event.key)){event.preventDefault();command(event.key==='0'?'fit':event.key==='-'?'out':'in');}
  });
  return {command,locate,refresh(){frames.cancel();observer?.disconnect();const ctx=current();if(!ctx)return;if(!views.has(ctx.key))views.set(ctx.key,{x:32,y:24,scale:.85});frames.flush();const Resize=root.ownerDocument.defaultView.ResizeObserver;if(Resize){observer=new Resize(()=>{if(current()?.key===ctx.key)frames.request();});observer.observe(ctx.el);}},dispose(){frames.dispose();observer?.disconnect();abort.abort();}};
}
