const destinations = [
  ['home', '/workbench/', '创作首页'],
  ['assets', '/workbench/asset-workflow.html', '剧本与资产'],
  ['scenes', '/workbench/studio/index.html', '场景建模'],
  ['actors', '/workbench/studio/actors/index.html', '人物白模'],
  ['director', '/workbench/studio/director/index.html', '导演预演'],
  ['motion', '/workbench/studio/director/motion-lab.html', '动作实验室'],
];
customElements.define('project-navigation', class extends HTMLElement {
  connectedCallback() {
    const menu = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'M · 漫剧工作台 ▾';
    summary.setAttribute('aria-label', '切换工作区');
    const nav = document.createElement('nav');
    nav.setAttribute('aria-label', '工作区');
    for (const [id, href, label] of destinations) {
      const link = Object.assign(document.createElement('a'), { href, textContent: label });
      if (id === this.getAttribute('current')) link.setAttribute('aria-current', 'page');
      nav.append(link);
    }
    menu.append(summary, nav);
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape') { menu.open = false; summary.focus(); }
    });
    menu.addEventListener('focusout', event => {
      if (!menu.contains(event.relatedTarget)) menu.open = false;
    });
    this.replaceChildren(menu);
  }
});
