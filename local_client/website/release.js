'use strict';
document.querySelectorAll('[data-download]').forEach(link => link.addEventListener('click', () => {
  document.querySelector('#download-status').textContent = '已请求下载。下载完成后，请打开安装程序；安装结束会自动创建桌面快捷方式。';
}));
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const status = document.querySelector('#copy-status');
  try {
    await navigator.clipboard.writeText(document.getElementById(button.dataset.copy).textContent.trim());
    status.textContent = '校验值已复制。';
  } catch {
    status.textContent = '暂时无法自动复制，请选择上方校验值手动复制，或下载校验文件。';
  }
}));

const sections = [...document.querySelectorAll('main section[id]')];
const chapterLinks = [...document.querySelectorAll('.chapter-nav a')];
const sectionObserver = new IntersectionObserver(entries => {
  const visible = entries.filter(row => row.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio)[0];
  if (!visible) return;
  chapterLinks.forEach(link=>{
    const active=link.hash==='#'+visible.target.id;
    link.classList.toggle('active',active);
    if(active)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');
  });
},{rootMargin:'-15% 0px -40% 0px',threshold:[0,.2,.5]});
sections.forEach(section=>sectionObserver.observe(section));
// A failed animation never hides the actual page or its download links.
if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const revealObserver=new IntersectionObserver(entries=>entries.forEach(row=>{
    if(row.isIntersecting){row.target.dataset.visible='true';revealObserver.unobserve(row.target);}
  }),{threshold:.08});
  document.querySelectorAll('.chapter h2,.section-heading,.director-decisions>div,.workflow-tour,.delivery-reel,.delivery-items article,.connection-graph,.installer-card,.setup-journey li,.platform-intro').forEach((el,index)=>{
    el.style.setProperty('--reveal-delay', `${index%3*80}ms`);
    el.classList.add('reveal');el.dataset.visible='false';revealObserver.observe(el);
  });
}

// The tour is progressive enhancement: without JavaScript all five stages remain readable.
const workflowTabs = [...document.querySelectorAll('[data-workflow-step]')];
const workflowPanels = [...document.querySelectorAll('.workflow-panel')];
function selectWorkflowStep(index, focus = false) {
  workflowTabs.forEach((tab, current) => {
    const selected = current === index;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    workflowPanels[current].hidden = !selected;
    if (selected && focus) tab.focus();
    if (selected && document.documentElement.dataset.motion !== 'paused' && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      workflowPanels[current].animate([{opacity:0,transform:'translateY(16px)',filter:'blur(4px)'},{opacity:1,transform:'translateY(0)',filter:'blur(0)'}],{duration:420,easing:'cubic-bezier(.2,.7,.2,1)'});
    }
  });
}
if (workflowTabs.length && workflowTabs.length === workflowPanels.length) {
  document.querySelector('.workflow-tabs').setAttribute('role', 'tablist');
  workflowTabs.forEach((tab, index) => {
    tab.setAttribute('role', 'tab');
    workflowPanels[index].setAttribute('role', 'tabpanel');
    tab.addEventListener('click', () => selectWorkflowStep(index));
    tab.addEventListener('keydown', event => {
      let next = index;
      if (event.key === 'ArrowRight') next = (index + 1) % workflowTabs.length;
      else if (event.key === 'ArrowLeft') next = (index + workflowTabs.length - 1) % workflowTabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = workflowTabs.length - 1;
      else return;
      event.preventDefault();
      selectWorkflowStep(next, true);
    });
  });
  selectWorkflowStep(0);
}


// OS detection only highlights a family; it never assumes Mac CPU architecture or starts a download.
const platformHint = navigator.userAgentData?.platform || navigator.platform || '';
const mobileDevice = /Android|iPhone|iPad/i.test(navigator.userAgent) || (/Mac/i.test(platformHint) && navigator.maxTouchPoints > 1);
const currentOS = mobileDevice ? null : /Mac/i.test(platformHint) ? 'mac' : /Win/i.test(platformHint) ? 'windows' : null;
const guidance = document.querySelector('#device-guidance');
if (guidance && mobileDevice) guidance.textContent = '请在电脑浏览器打开本页，选择对应版本安装。';
else if (guidance && currentOS) {
  const card = document.querySelector(`[data-os="${currentOS}"]`);
  card.classList.add('device-current');
  card.querySelector('.device-match').hidden = false;
  guidance.textContent = currentOS === 'mac' ? '你正在使用 Mac · 下载前请确认电脑为 Apple 芯片。' : '你正在使用 Windows · 请选择 64 位版本。';
}
document.querySelectorAll('.installer-card').forEach(card => {
  card.addEventListener('pointermove', event => {
    if (document.documentElement.dataset.motion === 'paused') return;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--light-x', `${event.clientX-rect.left}px`);
    card.style.setProperty('--light-y', `${event.clientY-rect.top}px`);
  }, {passive:true});
});
const motionSections = document.querySelectorAll('.connection-graph,.delivery-reel');
const motionObserver = new IntersectionObserver(entries => entries.forEach(entry => {
  entry.target.classList.toggle('is-playing', entry.isIntersecting);
}), {threshold:.15});
motionSections.forEach(section => motionObserver.observe(section));
