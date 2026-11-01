import {mount} from '../../frontend/workflow/controller.js';
const init=await fetch('/demo-init').then(r=>r.json());
const api={request:async(path,options={})=>{
 const response=await fetch('/demo-api'+path,{method:options.method||'GET',headers:{'Content-Type':'application/json'},...(options.body?{body:JSON.stringify(options.body)}:{})});
 if(options.responseType==='blob')return response.blob();
 const data=await response.json();if(!response.ok)throw Object.assign(new Error(data.message||'操作未完成'),{code:data.code});return data;
}};
mount({root:document.getElementById('workflow-root'),api,apiBase:'/demo-api',session:init.session});
