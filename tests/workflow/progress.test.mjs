import test from 'node:test';
import assert from 'node:assert/strict';
import {operationLabel,elapsedLabel,reviewProgress,taskProgress} from '../../frontend/workflow/progress.js';

test('feedback distinguishes waiting for receipt, collection, review and real completion',()=>{
  assert.match(operationLabel('/tasks/abc/submit','POST'),/等待官方回执/);
  assert.match(operationLabel('/tasks/abc/recover','POST'),/原任务/);
  assert.match(operationLabel('/assets/abc/reviews','POST'),/审核/);
  assert.equal(taskProgress({status:'running'}),'LibTV 正在生成');
  assert.equal(elapsedLabel(0,62000),'已用时 1 分 2 秒');
});

test('overall progress counts unique approved current stages, not candidate images',()=>{
  const r=(stage,extra={})=>({stage,status:'ready',review:'approved',owner:'a',...extra});
  const assets=[{active:true,entityId:'one',revisions:[r('style'),r('style'),r('asset',{review:'pending'}),r('refine',{status:'stale'}),r('asset',{owner:'b'})]}];
  assert.deepEqual(reviewProgress([{id:'one'}],assets,{owner:'a'},(r,s)=>r.owner===s.owner),{done:1,total:3});
});
