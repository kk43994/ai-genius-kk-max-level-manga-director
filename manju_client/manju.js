'use strict';
document.querySelector('#stop').addEventListener('click',async()=>{
  const status=document.querySelector('#status');
  try{
    const bootstrap=await fetch('api/v1/session');
    if(!bootstrap.ok)throw Error('请刷新后重试');
    const {data}=await bootstrap.json();
    const response=await fetch('api/v1/local-runtime/stop',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':data.csrfToken,'X-Asset-Lab-Session':data.session.id},body:'{}'});
    if(!response.ok)throw Error('退出未完成，请重试');
    status.textContent='本地工作台已停止。可以关闭此页面；下次双击桌面图标即可打开。';
    document.querySelector('#stop').disabled=true;
  }catch(error){status.textContent=error.message;}
});
