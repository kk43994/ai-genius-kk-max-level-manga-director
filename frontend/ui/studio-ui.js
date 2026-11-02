import {icon} from './icons.js';

// Presentation only: no task requests, draft writes or inferred review states.
export function mountStudioUI(root) {
  const doc=root.ownerDocument,win=doc.defaultView;
  if(!win?.MutationObserver)return {ready:Promise.resolve(),refresh(){},restoreFocus(){return false;},dispose(){}};
  const stylesheet=doc.createElement('link');
  stylesheet.rel='stylesheet';stylesheet.href=new URL('./studio-ui.css',import.meta.url).href;
  const ready=new Promise(resolve=>{stylesheet.onload=resolve;stylesheet.onerror=resolve;});
  doc.head.append(stylesheet);
  let alive=true,frame=0,lastPanel='',lastView='',motion=null;
  const reduced=win.matchMedia('(prefers-reduced-motion: reduce)');
  // The upstream distribution is UMD; load it as a classic local script.
  // Importing UMD as strict ESM can fail on window.window's readonly setter.
  const motionScript=doc.createElement('script');motionScript.src=new URL('./vendor/gsap.min.js',import.meta.url).href;motionScript.async=true;
  const motionReady=new Promise(resolve=>{motionScript.onload=()=>{motion=win.gsap;resolve(motion||null);};motionScript.onerror=()=>resolve(null);});
  doc.head.append(motionScript);
  const pending=new Set(),animated=new Set();
  const entries=[
    ['[data-wf-action="new-project"]','plus'],
    ['[data-wf-action="refresh"]','refresh-cw','刷新状态'],
    ['[data-wf-nav="plan"]','panels-top-left'],['[data-wf-nav="review"]','history'],
    ['[data-ui-file]','upload'],['[data-analysis-open]','file-text'],
    ['[data-story-canvas-command="art"]','palette'],['[data-story-canvas-command="assets"]','layers'],
    ['[data-canvas-batch]','image'],['[data-canvas-preview]','play'],
    ['[data-canvas-recipes]','book-open'],['[data-story-canvas-command="fit"]','scan','适应画布'],
    ['[data-story-canvas-command="fullscreen"]','maximize','切换专注画布'],
    ['[data-story-canvas-command="arrange"]','columns-3'],
    ['[data-story-canvas-command="out"]','minimize','缩小画布'],
    ['[data-story-canvas-command="in"]','plus','放大画布'],
    ['[data-story-canvas-command="reset"]','arrow-left'],
    ['[data-canvas-close]','x','关闭制作面板'],
    ['[data-image-models-refresh]','refresh-cw','刷新模型列表'],
    ['[data-wf-action="production-review-save"]','save'],
    ['[data-quick-tray-toggle]','list-todo'],
    ['[data-ui-more]','ellipsis'],
    ['#helpButton','circle-help','使用说明'],
    ['.integration-account-close','x','关闭账号面板'],
    ['.integration-account-trigger[data-ui-account]','circle-user-round'],
    ['.integration-account-trigger[data-ui-balance]','wallet']
  ];
  const selector=entries.map(([s])=>s).join(',');
  function enhance(node) {
    if(node.nodeType!==1)return;
    const controls=[...(node.matches(selector)?[node]:[]),...node.querySelectorAll(selector)];
    for(const control of controls) {
      const [,name,label]=entries.find(([s])=>control.matches(s));
      if(label){control.classList.add('ui-icon-button');control.setAttribute('aria-label',label);control.title=label;}
      if(!control.querySelector(':scope > .ui-icon'))control.insertAdjacentHTML('afterbegin',icon(name));
    }
  }
  // Observe new controls, never pan/zoom attributes or the full canvas on each frame.
  const observer=new win.MutationObserver(records=>{
    for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1&&!node.matches('.ui-icon,.ui-icon *'))pending.add(node);
    if(!pending.size||frame)return;
    frame=win.requestAnimationFrame(()=>{frame=0;const nodes=[...pending];pending.clear();for(const node of nodes)if(node.isConnected&&!nodes.some(parent=>parent!==node&&parent.contains(node)))enhance(node);});
  });
  observer.observe(doc.body,{childList:true,subtree:true});
  enhance(doc.body);

  function closeMenus(except) {for(const menu of root.querySelectorAll('.ui-menu[open]'))if(menu!==except)menu.open=false;}
  function onClick(event) {
    const picker=event.target.closest('[data-ui-file]');
    if(picker&&root.contains(picker)&&!picker.disabled){
      const target=picker.dataset.uiFile==='quick'?'[data-wf-quick-upload]':'[data-wf-upload]';
      root.querySelector(target)?.click();
    }
    const menu=event.target.closest('.ui-menu');
    closeMenus(menu);
    if(menu&&event.target.closest('.ui-menu-content button,.ui-menu-content a'))menu.open=false;
  }
  function onKey(event) {
    if(event.key!=='Escape')return;
    const menu=root.querySelector('.ui-menu[open]');
    if(menu){event.preventDefault();event.stopPropagation();menu.open=false;menu.querySelector('summary')?.focus();}
  }
  function animate(node,kind) {
    if(!node||reduced.matches)return;
    void motionReady.then(gsap=>{
      if(!alive||!node.isConnected||reduced.matches||!gsap)return;
      animated.add(node);
      gsap.fromTo(node,{opacity:0,...(kind==='panel'?{x:12}:{y:5})},{opacity:1,x:0,y:0,duration:kind==='panel'?.2:.16,ease:'power2.out',overwrite:true,clearProps:'opacity,transform',onComplete:()=>animated.delete(node)});
    });
  }
  function stopMotion(){if(!motion)return;for(const node of animated){motion.killTweensOf(node);motion.set(node,{clearProps:'opacity,transform'});}animated.clear();}
  function onMotion(){if(reduced.matches)stopMotion();}
  doc.addEventListener('click',onClick,true);doc.addEventListener('keydown',onKey,true);
  reduced.addEventListener('change',onMotion);
  return {ready,restoreFocus(trigger){
    // Rendering replaces controls; restore to the corresponding action, not a detached node.
    const attrs=[...(trigger?.attributes||[])].filter(a=>a.name.startsWith('data-')&&!a.name.startsWith('data-ui-'));
    const control=trigger?.isConnected?trigger:attrs.length?[...root.querySelectorAll('button,a,summary')].find(n=>attrs.every(a=>n.getAttribute(a.name)===a.value)):null;
    if(!control)return false;control.focus({preventScroll:true});return true;
  },refresh({view='',panel=''}={}){
    enhance(root);
    // Polling and keystrokes preserve positions; animate only an actual navigation.
    if(panel&&panel!==lastPanel)animate(root.querySelector('[data-canvas-drawer]'),'panel');
    if(view!==lastView)animate(root.querySelector('.wf-start')||root.querySelector('.wf-tabs'),'view');
    lastPanel=panel;lastView=view;
  },dispose(){alive=false;observer.disconnect();win.cancelAnimationFrame(frame);pending.clear();stopMotion();doc.removeEventListener('click',onClick,true);doc.removeEventListener('keydown',onKey,true);reduced.removeEventListener('change',onMotion);stylesheet.remove();motionScript.remove();}};
}
