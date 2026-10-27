'use strict';
const launch = document.querySelector('#demo-launch');
const preview = document.querySelector('#demo-workbench');
const close = document.querySelector('#demo-close');
function showPreview(show) {
  preview.hidden = !show;
  launch.setAttribute('aria-expanded', String(show));
  if (show) close.focus(); else launch.focus();
}
launch.addEventListener('click', () => showPreview(true));
close.addEventListener('click', () => showPreview(false));
preview.addEventListener('keydown', event => { if (event.key === 'Escape') showPreview(false); });
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
