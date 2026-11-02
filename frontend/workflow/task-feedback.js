// Failed attempts are feedback, not asset versions. Keep unresolved receipts
// visible independently; a later attempt cannot resolve an earlier paid call.
export function isTaskFailure(task){
 return task.status==='failed'&&(!task.canRecover||task.remoteStatus==='failed'||task.error?.details?.generationSubmitted===false)
  ||task.status==='needs_attention'&&task.submissionAttempted===false&&!task.canRecover&&!task.canConfirm;
}
const phases={mj_style:'style',image25_style:'style',image2_asset:'asset',image25_asset:'asset',nano_refine:'refine',storyboard_image:'storyboard',image25_storyboard:'storyboard'};
const scope=task=>JSON.stringify([task.projectId,task.entityId||task.id,phases[task.recipe]||task.recipe,task.ownership?.providerAccountId,task.ownership?.spaceId]);
const started=task=>Date.parse(task.createdAt||task.submittedAt||task.updatedAt||'')||0;
export function currentTaskFeedback(tasks=[]){
 const latest=new Map();
 for(const task of tasks){const key=scope(task),previous=latest.get(key);if(!previous||started(task)>started(previous))latest.set(key,task);}
 return tasks.filter(task=>!['completed','cancelled'].includes(task.status)&&(!isTaskFailure(task)||!started(task)||started(latest.get(scope(task)))<=started(task)));
}
export function taskFailureReason(task){
 const message=task.error?.message?.trim();
 if(!message||message==='官方原任务失败，未自动重新生成。')return '生成服务确认失败，但未提供具体原因。可查询原任务核对详情。';
 return message;
}
