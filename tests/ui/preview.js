// Synthetic visuals only. Never used by production HTML or imported by a feature module.
import { mount } from '../shell/index.js';
const events = new EventTarget();
const shell = mount({ root: document, events });
const $ = id => document.getElementById(id);
const state = new URLSearchParams(location.search).get('state') || 'empty';
const picture = new URL('./synthetic-assets.svg', import.meta.url).href;
document.querySelector('.workspace-context span:last-child').textContent = '合成数据预览';
$('saveStatus').textContent = '视觉预览';
$('update-root').innerHTML = '<div class="preview-release"><span>UI 预览 · 合成数据，不代表真实授权或生成</span><nav aria-label="预览状态"><a href="?state=empty">首次进入</a><a href="?state=connected">工作中</a><a href="?state=expired">授权过期</a></nav><span>v0.1.0 · 界面预览</span></div>';

function showInfo(title, text, trigger) {
  $('shell-info-title').textContent = title;
  const p = document.createElement('p'); p.textContent = text;
  $('shell-info-body').replaceChildren(p);
  shell.openPanel('info', trigger);
}
events.addEventListener('shell:action', event => {
  if (!['connect', 'manual-plan'].includes(event.detail.action)) return;
  event.preventDefault();
  showInfo('合成界面预览', '这里仅展示页面布局。账号授权、项目保存和生成由对应业务模块接入；本预览不会请求 LibTV，也不会保存或提交任务。', event.detail.trigger);
});
$('importScript').addEventListener('click', event => showInfo('导入剧本', '业务接入后支持 TXT、Markdown 和 Word 剧本。本预览不上传文件。', event.currentTarget));

if (state === 'connected' || state === 'expired') {
  shell.setView({ connectionState: state === 'expired' ? 'expired' : 'connected', workspaceState: 'ready', projectName: '风从庭院来', saveLabel: '合成项目 · 视觉预览' });
  $('account-root').innerHTML = '<div class="demo-account"><span class="demo-avatar" aria-hidden="true">舟</span><button class="demo-account-name" type="button">示例创作账号 <span aria-hidden="true">⌄</span></button><span class="demo-space">个人空间 <span aria-hidden="true">⌄</span></span><span class="demo-connection '+(state === 'expired' ? 'expired' : '')+'">'+(state === 'expired' ? '需重新授权' : '已连接 · 示例')+'</span><span class="demo-quota">可用额度未知</span></div>';
  document.querySelector('.demo-account-name').addEventListener('click', event => showInfo('账号与空间', '这是合成账号，不包含真实凭据。正式账号选择、空间切换和重授权由账号模块负责。', event.currentTarget));
  $('scriptSelect').innerHTML = '<option>风从庭院来 · 示例项目</option>';
  $('warehouseCount').textContent = '3';
  $('reviewCount').textContent = '2';
  $('taskCount').textContent = '2';
  $('warehouseList').innerHTML = [
    ['character', '角色', '舟宁', '风格已确认 · 资产待审核', '01'],
    ['scene', '场景', '午后的庭院', '资产已确认 · 等待精修', '02'],
    ['prop', '道具', '青瓷茶盏', '清单已确认 · 待制作', '03'],
  ].map(([category, label, title, status, number], i) => '<button type="button" class="demo-asset-row '+(i === 0 ? 'selected' : '')+'" data-demo-category="'+category+'"><span class="demo-thumb thumb-'+category+'" aria-hidden="true">'+number+'</span><span><small>'+label+'</small><b>'+title+'</b><em>'+status+'</em></span></button>').join('');
  $('warehouseFilters').addEventListener('click', event => {
    const button = event.target.closest('[data-warehouse-filter]'); if (!button) return;
    document.querySelectorAll('#warehouseFilters button').forEach(item => { item.classList.toggle('active', item === button); item.setAttribute('aria-pressed', String(item === button)); });
    document.querySelectorAll('[data-demo-category]').forEach(item => { item.hidden = button.dataset.warehouseFilter !== 'all' && button.dataset.warehouseFilter !== item.dataset.demoCategory; });
  });
  $('warehouseSearch').addEventListener('input', event => document.querySelectorAll('[data-demo-category]').forEach(item => { item.hidden = !item.textContent.includes(event.target.value); }));
  $('main').innerHTML = '<div class="canvas-heading"><div><span class="eyebrow">YOUR STORY, IN THE MAKING</span><h1>风从庭院来</h1><p>一间庭院，一场久别重逢。让每个细节留住故事的温度。</p></div><span class="demo-project-tag">示例项目</span></div>' +
    (state === 'expired' ? '<div class="demo-expired" role="status"><b>当前账号需要重新授权</b><p>已有项目、素材和任务归属继续保留。完成授权后，再继续制作。</p><button class="lab-button secondary" data-shell-action="connect" type="button">重新授权</button></div>' : '') +
    '<div class="demo-project-stats"><span><strong>3</strong>项资产</span><span><strong>2</strong>个结果待审</span><span><strong>1</strong>份已定版</span><span class="demo-stat-note">逐步制作 · 逐步确认</span></div>' +
    '<section class="demo-work-card" aria-labelledby="demo-work-title"><div class="demo-work-heading"><div><span class="caption">正在制作 / 角色</span><h2 id="demo-work-title">舟宁 <small>基础设定</small></h2></div><button type="button" class="lab-button text-button" data-demo-info>查看清单 ↗</button></div>' +
    '<ol class="demo-stagebar"><li class="done"><span>✓</span><div><b>MJ 风格</b><small>已人工确认</small></div></li><li class="current"><span>02</span><div><b>Image2 资产</b><small>等待你的审核</small></div></li><li><span>03</span><div><b>Nano 精修</b><small>审核通过后继续</small></div></li></ol>' +
    '<div class="demo-result-top"><h3>资产设定 · 第 2 版</h3><span class="demo-pill pending">待审核</span></div><figure class="demo-result-image"><img src="'+picture+'" alt="合成角色示意图：正面、侧面和背面服装轮廓，用于检查界面布局"><figcaption>合成示意图 · 非模型生成结果</figcaption></figure>' +
    '<div class="demo-result-meta"><span>Image2 · 角色设定</span><span>来源：已确认风格 V1</span><span>示例创作账号 / 个人空间</span></div><div class="demo-review-action"><p><b>仔细看过，再进入下一步</b><span>检查造型、比例与风格一致性。</span></p><button class="lab-button primary" type="button" data-demo-review>对比与审核 <span aria-hidden="true">→</span></button></div></section>' +
    '<div class="demo-next-assets"><h2>继续制作其他资产</h2><div><span class="demo-small-symbol">▧</span><p><b>午后的庭院</b><small>场景 · 等待保真精修</small></p><button class="lab-button text-button" type="button" data-demo-info>打开 →</button></div><div><span class="demo-small-symbol">◇</span><p><b>青瓷茶盏</b><small>道具 · 等待风格探索</small></p><button class="lab-button text-button" type="button" data-demo-info>打开 →</button></div></div>';
  document.querySelector('#steps [data-nav="asset"]').classList.add('active');
  document.querySelector('#steps [data-nav="asset"]').setAttribute('aria-current', 'step');
  $('steps').addEventListener('click', event => { if (event.target.closest('[data-nav]')) showInfo('制作流程', '这是工作流模块的挂载位置。该预览仅展示布局，不创建或切换真实任务。', event.target.closest('button')); });
  $('task-root').innerHTML = '<div class="demo-task-group"><div class="demo-task-label"><b>等待处理</b><span>2</span></div><article class="demo-task-card"><div><span class="demo-pill pending">待审核</span><time>刚刚</time></div><h3>舟宁 · Image2 资产</h3><p>第 2 版已返回，等待你确认。</p><small>示例创作账号 · 个人空间</small><button class="lab-button secondary" type="button" data-demo-review>查看结果 →</button></article><article class="demo-task-card"><div><span class="demo-pill attention">需核对</span><time>5 分钟前</time></div><h3>庭院 · Nano 精修</h3><p>任务状态待核对，可查询原任务。</p><small>示例创作账号 · 个人空间</small><button class="lab-button text-button" type="button" data-demo-info>查看详情 →</button></article></div>';
  $('review-root').innerHTML = '<span class="demo-pill pending">待人工审核 · 示例</span><h3 class="demo-review-title">舟宁 · 资产设定 V2</h3><figure class="demo-result-image"><img src="'+picture+'" alt="合成角色设定示意图"><figcaption>合成数据，不是已完成生成</figcaption></figure><p class="demo-review-hint">请检查人物比例、服装细节和风格是否保持一致。</p><label class="demo-review-label" for="demo-review-note">返修意见</label><textarea id="demo-review-note" placeholder="例如：保留服装轮廓，调整袖口细节。" rows="4"></textarea><div class="demo-review-buttons"><button class="lab-button secondary" type="button" data-demo-info>需要返修</button><button class="lab-button primary" type="button" data-demo-info>确认通过</button></div><p class="demo-review-hint">本预览不保存审核意见或批准任何生成。</p>';
  document.addEventListener('click', event => {
    if (event.target.closest('[data-demo-review]')) shell.openPanel('review', event.target.closest('button'));
    if (event.target.closest('[data-demo-info]')) showInfo('合成界面预览', '此按钮为业务模块预留。当前没有提交、审批、下载或保存任何真实数据。', event.target.closest('button'));
  });
}
