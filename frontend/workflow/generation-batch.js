// Each group retains its own receipt. A rejection never cancels sibling reads
// and never invents a new key for an uncertain submission.
export function batchSize(value){
 const n=Number(value||1);
 if(!Number.isInteger(n)||n<1||n>8)throw new Error('每批请选择 1 至 8 组。');
 return n;
}
export async function parallelGroups(items,action,limit=3){
 const results=new Array(items.length);let next=0;
 await Promise.all(Array.from({length:Math.min(limit,items.length)},async()=>{
  while(next<items.length){const i=next++;try{results[i]={status:'fulfilled',value:await action(items[i],i)};}catch(reason){results[i]={status:'rejected',reason};}}
 }));
 return results;
}
