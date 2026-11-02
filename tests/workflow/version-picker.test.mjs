import test from 'node:test';
import assert from 'node:assert/strict';
import {versionPicker,versionTarget} from '../../frontend/workflow/version-picker.js';
const owner={providerAccountId:'a',spaceId:'s'},r={id:'v2',assetId:'archive',entityId:'shot',stage:'storyboard',status:'ready',review:'pending',ownership:owner,reviewHistory:[],settings:{},createdAt:'2026-11-03'};
const asset={name:'测试镜头',revisions:[{...r,id:'v1',review:'approved'},r,{...r,id:'v3',status:'stale'},{...r,id:'alien',ownership:{...owner,spaceId:'other'}}]};
const job={status:'ready',shotBindings:[{shotId:'s1',entityId:'shot'}]};
const args={asset,revision:r,job,selection:owner,apiBase:'/api/v1'};
test('all same-owner shot versions are clickable; zoom is independent and stale is view-only',()=>{
 const html=versionPicker(args);
 assert.match(html,/3 个版本/);assert.doesNotMatch(html,/alien|人工审核|退回修改/);
 assert.match(html,/data-version-select="v2"/);assert.match(html,/data-wf-review="v2"/);
 assert.match(html,/data-version-select="v3"/);assert.match(html,/aria-label="查看 V3/);assert.match(html,/当前选用 V1/);
 assert.match(html,/正在查看 V2/);assert.match(html,/data-version-reroll="v2"/);
});
test('reroll requires an actual binding, and reference-only images are not production targets',()=>{
 assert.deepEqual(versionTarget(job,r),{shotId:'s1',recipe:'image25_storyboard'});
 assert.equal(versionTarget({...job,stale:true},r),null);
 assert.equal(versionTarget(job,{...r,entityId:'else'}),null);
 assert.equal(versionTarget(job,{...r,referenceOnly:true}),null);
});
test('edit fields are collapsed until requested, original target is pinned and notes escaped',()=>{
 assert.doesNotMatch(versionPicker(args),/name="editNote"/);
 const html=versionPicker({...args,reroll:true,draft:{editNote:'<script>bad</script>'}});
 assert.match(html,/data-revision-id="v2"/);assert.match(html,/重抽参考原图 V2/);
 assert.match(html,/&lt;script&gt;bad/);assert.match(html,/带原图重抽/);
 assert.match(html,/新图生成后由你选择/);
});
test('compact toolbar only submits new selections; the selected and stale versions open comparison',()=>{
 const html=versionPicker({...args,compact:true});
 assert.match(html,/data-quick-image-pick="v2"/);
 assert.doesNotMatch(html,/data-quick-image-pick="(?:v1|v3)"/);
 assert.match(html,/data-image-tools-versions="v1"/);
 assert.match(html,/data-image-tools-versions="v3"/);
});
