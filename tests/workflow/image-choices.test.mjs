import test from 'node:test';
import assert from 'node:assert/strict';
import {imageChoice,sourceImagePicker} from '../../frontend/workflow/image-choices.js';
import {referencePool,chooseExtraReference,imageReferencePicker,libraryPanel} from '../../frontend/workflow/image-references.js';
import {referencePicker} from '../../frontend/workflow/production-references.js';
import {referenceCards,productionPanel} from '../../frontend/workflow/production.js';
import {generationInspector} from '../../frontend/workflow/production-generation.js';
import {bindingPicker} from '../../frontend/workflow/production-bindings.js';

const owner={providerAccountId:'account',spaceId:'space'};
const revision=(id,patch={})=>({id,assetId:'archive',entityId:'entity',stage:'asset',createdAt:'2026-11-02',status:'ready',review:'approved',ownership:owner,...patch});
const archive={id:'archive',entityId:'entity',name:'合成道具',active:true,revisions:[revision('first'),revision('second')]};

test('source images are native single-choice inputs with exact submitted IDs and separate previews',()=>{
 const html=sourceImagePicker(archive.revisions,'second','/api/v1');
 assert.doesNotMatch(html,/<select/);
 assert.equal((html.match(/type="radio"/g)||[]).length,2);
 assert.match(html,/<input[^>]*name="sourceRevisionId" value="second"[^>]* checked/);
 assert.doesNotMatch(html,/<input[^>]*value="first"[^>]* checked/);
 assert.match(html,/<\/label><button[^>]*data-wf-review="second"/);
 for(const label of html.matchAll(/<label[^>]*>[\s\S]*?<\/label>/g))assert.doesNotMatch(label[0],/<button/);
 const stale=sourceImagePicker(archive.revisions,'gone','/api/v1');
 assert.doesNotMatch(stale,/ checked/);assert.match(stale,/原参考版本已不可用/);
});

test('image actions preserve their purpose, escape text, and missing previews cannot be selected',()=>{
 const html=imageChoice({src:'/image',name:'<img onerror="bad">',action:{'data-library-import':2},choose:'保存为项目参考图',previewURL:'javascript:bad()'});
 assert.match(html,/class="image-choice-pick" data-library-import="2"/);assert.match(html,/&lt;img/);
 assert.doesNotMatch(html,/href="javascript:|<img onerror/);
 assert.match(imageChoice({name:'无预览',action:{'data-library-import':2}}),/<button[^>]*data-library-import="2"[^>]* disabled/);
});

test('extra image choices remain scoped to approved current images in the original account and space',()=>{
 const bad=[revision('pending',{review:'pending'}),revision('rejected',{review:'changes_requested'}),revision('stale',{status:'stale'}),revision('foreign',{ownership:{...owner,spaceId:'other'}})];
 const assets=[{...archive,revisions:[...archive.revisions,...bad]},{...archive,active:false,revisions:[revision('inactive')]}];
 assert.deepEqual(referencePool(assets,owner).map(r=>r.id),['first','second']);
 const html=imageReferencePicker({assets,job:{ownership:owner},apiBase:'/api/v1',generationDraft:{extraReferences:'[{"id":"second","purpose":"prop"}]'}});
 assert.match(html,/type="checkbox" data-reference-toggle="second" checked/);
 assert.doesNotMatch(html,/data-reference-choice|data-reference-add|data-reference-toggle="(pending|foreign|stale|inactive)"/);
 assert.match(html,/data-reference-purpose-change="second"/);
});

test('multi-choice references add, remove and change purpose without duplicates or silently exceeding the limit',()=>{
 const original=[{id:'first',purpose:'identity'}],pool=archive.revisions;
 const added=chooseExtraReference(original,pool,'second','prop',true);
 assert.deepEqual(original,[{id:'first',purpose:'identity'}]);assert.equal(added.length,2);
 assert.deepEqual(chooseExtraReference(added,pool,'second','scene',true),[{id:'first',purpose:'identity'},{id:'second',purpose:'scene'}]);
 assert.deepEqual(chooseExtraReference(added,pool,'second','prop',false),original);
 assert.throws(()=>chooseExtraReference(original,pool,'foreign','prop',true),/不可用于参考/);
 assert.throws(()=>chooseExtraReference(original,pool,'second','unknown',true),/参考用途/);
 assert.throws(()=>chooseExtraReference(Array.from({length:19},(_,i)=>({id:String(i),purpose:'style'})),pool,'second','prop',true),/19/);
 assert.deepEqual(chooseExtraReference([{id:'expired',purpose:'style'}],[],'expired','style',false),[]);
});

test('pending uploaded references use the same direct choice and exclude another account',()=>{
 const html=imageReferencePicker({assets:[{...archive,referenceOnly:true,revisions:[revision('upload',{review:'pending'}),revision('foreign',{review:'pending',ownership:{...owner,providerAccountId:'other'}})]}],job:{ownership:owner},apiBase:'/api/v1'});
 assert.match(html,/data-creator-keep="upload"/);assert.doesNotMatch(html,/foreign/);
 assert.match(html,/data-wf-review="upload"/);
});

test('LibTV detail images select the exact index while missing preview stays unavailable',()=>{
 const html=libraryPanel({open:true,items:[],detail:{name:'合成素材',images:[{index:0,preview:'/preview/0'},{index:3,preview:'/preview/3'},{index:4,previewError:'不可读'}]}});
 assert.match(html,/<button[^>]*class="image-choice-pick" data-library-import="3"/);
 assert.match(html,/<button[^>]*data-library-import="4"[^>]* disabled/);
 assert.match(html,/href="\/preview\/3"/);
});

test('linking a historical archive by image remains separate from approving its images',()=>{
 const html=bindingPicker({job:{ownership:owner,bindings:[{assetId:'prop',stateId:'base',legacyCandidates:[{entityId:'entity',name:'旧档案'}]}]},asset:{id:'prop',name:'道具'},state:{id:'base',name:'基础'},assets:[archive],apiBase:'/api/v1'});
 assert.match(html,/class="image-choice-pick" data-production-bind="entity" data-binding-asset="prop" data-binding-state="base"/);
 assert.doesNotMatch(html,/data-creator-keep/);assert.match(html,/data-wf-review="first"/);
});

const asset={id:'prop',category:'prop',name:'信封',design:'合成',states:[{id:'base',name:'基础',sceneIds:['scene']}]};
const shot={id:'shot',sceneId:'scene',references:[{assetId:'prop',stateId:'base',revisionId:'first'}],dialogueIds:[],durationSeconds:3,evidence:[],continuity:[]};
const job={id:'job',status:'ready',ownership:owner,result:{assets:[asset],shots:[shot],scenePlans:[]},bindings:[{assetId:'prop',stateId:'base',entityId:'entity',saved:true}],dialogues:[]};

test('director image-version choices preserve a pinned older image instead of switching to the newest',()=>{
 const html=productionPanel({script:{id:'script'},job,assets:[archive],selection:owner,apiBase:'/api/v1',view:{inspector:'shots',index:0}});
 assert.match(html,/<input[^>]*value="first"[^>]*data-reference-version="0"[^>]* checked/);
 assert.match(html,/data-reference-shot="0"/);assert.doesNotMatch(html,/<select[^>]*data-reference-version/);
 assert.match(html,/data-reference-unpin="0"/);
});

test('the director mention picker carries approved image IDs and offers only applicable states',()=>{
 const result={assets:[{...asset,states:[...asset.states,{id:'other',name:'另一个场次',sceneIds:['other']}]}]};
 const cards=referenceCards({...job,result},shot,[archive],owner,'/api/v1');
 const html=referencePicker(result,shot,'shots.0.beat','',cards);
 assert.match(html,/data-reference-insert="prop" data-reference-state="base"[^>]*data-reference-image="first"/);
 assert.doesNotMatch(html,/另一个场次/);assert.match(html,/data-wf-review="first"/);
});

test('an expired generation source requires a new image choice, not silent fallback',()=>{
 const html=generationInspector({result:job.result,job,view:{kind:'assets',index:0,stage:'asset'},assets:[{...archive,revisions:[revision('style',{stage:'style'})]}],selection:owner,apiBase:'/api/v1',project:{artDirection:{valid:true}},generationDraft:{sourceRevisionId:'expired',modelId:'pro'},imageContracts:{pro:{verified:true}}});
 assert.match(html,/原参考版本已不可用/);assert.doesNotMatch(html,/<input[^>]*name="sourceRevisionId"[^>]* checked/);
 assert.match(html,/<button class="primary" type="submit"[^>]* disabled/);
});
