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
  document.querySelectorAll('.chapter h2,.provider,.steps li,.section-heading').forEach(el=>{
    el.classList.add('reveal');el.dataset.visible='false';revealObserver.observe(el);
  });
}
