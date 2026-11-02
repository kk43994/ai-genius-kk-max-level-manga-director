const nanoName=/nano(?:[\s_-]*(?:banana|[2-9]))?|香蕉/i;
export const NANO_CLEANUP_MARKER='【Nano 保真洗图】';
export const NANO_CLEANUP_PROMPT=NANO_CLEANUP_MARKER+'\n以本次指定原图为唯一画面基准，其他人物与场景参考只用于核对一致性。只清理压缩噪点、局部糊边和细小生成瑕疵；保留原有画风、脸型五官、表情、发型、服饰纹样、人物位置、肢体姿势、道具、背景空间、光影方向、色彩与画幅。多视图保持视图数量与顺序。不要重新构图、改动作、换脸、美颜、增加细节或过度锐化，保留已有文字和标识。宁可改动很小，也不要重绘或丢失结构。';

/** Use only advertised names and IDs. Never invent a Nano provider key. */
export function nanoModels(catalog){
 return {...catalog,items:(catalog?.items||[]).filter(m=>nanoName.test(m.name)||nanoName.test(m.id))};
}
export function selectedNanoModel(draft,catalog){
 const rows=nanoModels(catalog).items;
 const selected=rows.find(m=>m.id===draft?.modelId||m.name===draft?.modelId);
 return selected||rows.find(m=>/nano[\s_-]*(?:banana[\s_-]*)?2\b/i.test(m.name+' '+m.id))||rows[0]||null;
}

/** Repeat cleanup from the preserved original, avoiding successive lossy washes. */
export function nanoCleanupSource(revision,assets){
 let current=revision;const seen=new Set();
 const all=(assets||[]).flatMap(a=>a.revisions||[]);
 while(current?.prompt?.includes(NANO_CLEANUP_MARKER)){
  if(seen.has(current.id))return null;seen.add(current.id);
  const seed=(current.sourceRevisionIds||[]).map(id=>all.find(r=>r.id===id)).find(r=>r?.provenance?.kind==='image_edit');
  const original=seed&&all.find(r=>r.id===seed.provenance.revisionId);
  if(!original||original.entityId!==revision.entityId||original.assetId!==revision.assetId||original.stage!==revision.stage||original.ownership?.providerAccountId!==revision.ownership?.providerAccountId||original.ownership?.spaceId!==revision.ownership?.spaceId)return null;
  current=original;
 }
 return current;
}
