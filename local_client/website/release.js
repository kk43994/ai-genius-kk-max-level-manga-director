'use strict';
document.querySelectorAll('[data-download]').forEach(link => link.addEventListener('click', () => {
  const message = `已请求${link.closest('[data-os]')?.dataset.os === 'mac' ? ' Mac' : link.closest('[data-os]')?.dataset.os === 'windows' ? ' Windows' : ''} 安装包。请在浏览器下载列表查看进度，下载完成后打开安装。`;
  document.querySelector('#download-status').textContent = message;
  showNotice(message);
}));
let noticeTimer;
function showNotice(message) {
  const notice = document.querySelector('#download-notice');
  if (!notice) return;
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 8000);
}
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const status = document.querySelector('#copy-status');
  try {
    await navigator.clipboard.writeText(document.getElementById(button.dataset.copy).textContent.trim());
    status.textContent = '校验值已复制。';
  } catch {
    status.textContent = '暂时无法自动复制，请选择上方校验值手动复制，或下载校验文件。';
  }
}));

const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const canAnimate = () => !reducedMotion.matches && document.documentElement.dataset.motion !== 'paused';
const effects = new Set();
function enter(element, delay = 0) {
  if (!canAnimate() || !element.animate) return;
  // Base content stays visible if an observer or animation API is unavailable.
  try {
    const effect = element.animate([{opacity:0, transform:'translateY(16px)'}, {opacity:1, transform:'translateY(0)'}],
      {duration:550, delay, easing:'cubic-bezier(.2,.7,.2,1)'});
    effects.add(effect);
    effect.onfinish = effect.oncancel = () => effects.delete(effect);
  } catch { /* Static content is the fallback. */ }
}
document.addEventListener('site-motion-change', event => {
  if (event.detail.paused) [...effects].forEach(effect => effect.finish());
});
if ('IntersectionObserver' in window) {
  const revealObserver = new IntersectionObserver(entries => entries.forEach(row => {
    if (!row.isIntersecting) return;
    enter(row.target);
    revealObserver.unobserve(row.target);
  }), {threshold:.08});
  document.querySelectorAll('.chapter h2,.section-heading,.director-decisions>div,.workflow-tour,.delivery-reel,.delivery-items article,.connection-graph,.installer-card,.setup-journey li,.platform-intro').forEach(el => revealObserver.observe(el));
}

// A single navigation serves desktop and mobile; focus never remains inside a closed menu.
const navigation = document.querySelector('#primary-navigation');
const menu = document.querySelector('#menu-toggle');
const header = document.querySelector('.header');
function closeMenu() {
  header?.removeAttribute('data-menu');
  menu?.setAttribute('aria-expanded', 'false');
}
if (navigation && menu && header) {
  document.documentElement.dataset.navigation = 'enhanced';
  menu.hidden = false;
  menu.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open));
    if (open) header.dataset.menu = 'open'; else closeMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && header.dataset.menu === 'open') { closeMenu(); menu.focus(); }
  });
  document.addEventListener('click', event => {
    if (!header.contains(event.target)) closeMenu();
  });
  navigation.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    if (header.dataset.menu !== 'open') return;
    closeMenu();
    const target = document.querySelector(link.hash);
    if (target) { target.tabIndex = -1; target.focus({preventScroll:true}); }
  }));
  matchMedia('(min-width: 761px)').addEventListener('change', closeMenu);
}
const sections = [...document.querySelectorAll('main section[id]')];
const chapterLinks = [...document.querySelectorAll('#primary-navigation a,.nav-download')];
let navigationFrame = 0;
function trackChapter() {
  if (navigationFrame) return;
  navigationFrame = requestAnimationFrame(() => {
    navigationFrame = 0;
    const edge = (header?.getBoundingClientRect().height || 80) + 40;
    const current = sections.filter(section => section.getBoundingClientRect().top <= edge).at(-1);
    chapterLinks.forEach(link => {
      const active = link.hash === '#' + current?.id;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current');
    });
  });
}
window.addEventListener('scroll', trackChapter, {passive:true});
window.addEventListener('resize', trackChapter, {passive:true});
window.addEventListener('pageshow', trackChapter);
trackChapter();

// The tour is progressive enhancement: without JavaScript all five stages remain readable.
const workflowTabs = [...document.querySelectorAll('[data-workflow-step]')];
const workflowPanels = [...document.querySelectorAll('.workflow-panel')];
function selectWorkflowStep(index, focus = false) {
  [...effects].forEach(effect => effect.finish());
  workflowTabs.forEach((tab, current) => {
    const selected = current === index;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    workflowPanels[current].hidden = !selected;
    if (selected && focus) tab.focus();
    if (selected) enter(workflowPanels[current]);
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
    if (!canAnimate() || event.pointerType === 'touch') return;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--light-x', `${event.clientX-rect.left}px`);
    card.style.setProperty('--light-y', `${event.clientY-rect.top}px`);
  }, {passive:true});
});
const motionSections = document.querySelectorAll('.connection-graph,.delivery-reel');
if ('IntersectionObserver' in window) {
  const motionObserver = new IntersectionObserver(entries => entries.forEach(entry => {
    entry.target.classList.toggle('is-playing', entry.isIntersecting);
  }), {threshold:.15});
  motionSections.forEach(section => motionObserver.observe(section));
}
