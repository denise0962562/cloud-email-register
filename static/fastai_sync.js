/* FastAI 导入任务由本地后端执行，页面不接收 Apple Cookie。 */
var fastaiSyncSnapshot=null, fastaiPollId=null, fastaiPolling=false;
function fastaiStatusHtml(email){
  var status=email.fastai_synced?'synced':email.fastai_sync_status;
  var text=status==='synced'?'已同步':status==='running'?'同步中':status==='failed'?'同步失败':'未同步';
  var title=email.fastai_sync_error||'';
  if(email.fastai_synced_at)title='同步时间：'+new Date(email.fastai_synced_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
  return '<span class="fastai-status fastai-'+escAttr(status||'pending')+'" title="'+escAttr(title)+'">'+text+'</span>';
}
function ensureFastaiDialogs(){
  if(document.getElementById('fastaiSyncDialog'))return;
  document.body.insertAdjacentHTML('beforeend',
    '<dialog class="fastai-dialog" id="fastaiSyncDialog" aria-labelledby="fastaiSyncTitle">'+
    '<div class="fastai-dialog-heading"><h2 id="fastaiSyncTitle">同步 FastAI</h2><button class="btn btn-outline btn-sm" id="fsClose">关闭</button></div>'+
    '<p class="fastai-hint">同步所有已配置收件、尚未同步的邮箱；关闭弹窗后后台继续执行。</p>'+
    '<div id="fsEndpoint" class="fastai-endpoint"></div><p id="fsMessage" role="status" aria-live="polite">正在准备同步…</p>'+
    '<progress id="fsProgress" max="1" value="0" aria-label="FastAI 同步进度"></progress>'+
    '<div id="fsCounts" class="fastai-counts"></div><div class="fastai-items-wrap"><table class="fastai-items"><thead><tr><th>邮箱</th><th>状态</th><th>结果</th></tr></thead><tbody id="fsItems"></tbody></table></div>'+
    '<div class="fastai-actions"><button class="btn btn-primary" id="fsRetry">重试未同步</button></div></dialog>'+
    '<dialog class="fastai-dialog fastai-config" id="fastaiConfigDialog" aria-labelledby="fastaiConfigTitle">'+
    '<div class="fastai-dialog-heading"><h2 id="fastaiConfigTitle">FastAI 同步配置</h2><button class="btn btn-outline btn-sm" id="fsConfigClose">关闭</button></div>'+
    '<label class="fastai-field">FastAI 导入接口地址<input id="fsApiUrl" type="url" placeholder="http://127.0.0.1:8766/api/import"></label>'+
    '<p class="fastai-hint">填写 gpt-auto-register 的导入接口地址。只填服务根地址时，会补上 /api/import。</p>'+
    '<label class="fastai-field">接口 Token<input id="fsApiToken" type="password" maxlength="8192" autocomplete="new-password" placeholder="输入 Token，无需填写 Bearer 前缀"></label>'+
    '<p class="fastai-hint" id="fsTokenHint"></p><label class="fastai-check"><input id="fsClearToken" type="checkbox"> 清除已保存的 Token</label>'+
    '<label class="fastai-check"><input id="fsEnabled" type="checkbox"> 自动同步未同步邮箱</label>'+
    '<label class="fastai-field">执行间隔（分钟）<input id="fsInterval" type="number" min="1" max="10080" step="1"></label>'+
    '<p class="fastai-hint">配置保存在本项目 SQLite。开启后先等待设定间隔；保存配置保留已排定时间，新间隔用于下次重新计时。当前任务继续使用启动时的接口地址。</p>'+
    '<div id="fsNextRun" class="fastai-hint"></div><p id="fsConfigMessage" role="status"></p>'+
    '<div class="fastai-actions"><button class="btn btn-primary" id="fsConfigSave">保存配置</button></div></dialog>');
  E('fsClose').onclick=function(){E('fastaiSyncDialog').close();};
  E('fsConfigClose').onclick=function(){E('fastaiConfigDialog').close();};
  E('fsRetry').onclick=startFastaiSync;
  E('fsConfigSave').onclick=saveFastaiConfig;
}
async function fastaiRequest(url,options){
  var response=await fetch(url,options),data;
  try{data=await response.json();}catch(error){throw new Error('同步服务返回无效响应');}
  if(!response.ok||!data.ok)throw new Error(data.error||'同步请求失败');
  return data;
}
async function loadFastaiSyncState(){
  fastaiSyncSnapshot=await fastaiRequest('/api/fastai-sync');
  var button=E('btnFastaiSync');
  if(button)button.textContent=fastaiSyncSnapshot.job&&fastaiSyncSnapshot.job.status==='running'?'查看 FastAI 同步进度':'一键同步所有未同步（'+fastaiSyncSnapshot.pending+'）';
  if(fastaiSyncSnapshot.job&&fastaiSyncSnapshot.job.status==='running'&&!fastaiPolling){
    ensureFastaiDialogs();fastaiPollId=fastaiSyncSnapshot.job.id;pollFastaiSync();
  }
  return fastaiSyncSnapshot;
}
async function openFastaiConfig(){
  ensureFastaiDialogs();
  try{
    var state=await loadFastaiSyncState(),c=state.config;
    E('fsApiUrl').value=c.api_url;E('fsEnabled').checked=c.enabled;E('fsInterval').value=c.interval_minutes;
    E('fsApiToken').value='';E('fsClearToken').checked=false;
    E('fsTokenHint').textContent=c.api_token_configured?'已配置 Token；留空保留，输入新值替换。':'未配置 Token；留空不使用授权。';
    E('fsConfigMessage').textContent='';
    E('fsNextRun').textContent=state.next_run?'下次执行：'+new Date(state.next_run*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）':'自动同步未开启';
    E('fastaiConfigDialog').showModal();
  }catch(error){toast(error.message,true);}
}
async function saveFastaiConfig(){
  var button=E('fsConfigSave');button.disabled=true;
  try{
    var data=await fastaiRequest('/api/fastai-sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({... (E('fsClearToken').checked?{api_token:''}:E('fsApiToken').value.trim()?{api_token:E('fsApiToken').value.trim()}:{}),api_url:E('fsApiUrl').value.trim(),enabled:E('fsEnabled').checked,interval_minutes:Number(E('fsInterval').value)})});
    fastaiSyncSnapshot=data;E('fsConfigMessage').textContent='配置已保存';
    E('fsApiUrl').value=data.config.api_url;
    E('fsApiToken').value='';E('fsClearToken').checked=false;
    E('fsTokenHint').textContent=data.config.api_token_configured?'已配置 Token；留空保留，输入新值替换。':'未配置 Token；留空不使用授权。';
    E('fsNextRun').textContent=data.next_run?'下次执行：'+new Date(data.next_run*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）':'自动同步未开启';
    await refreshEmails();await loadFastaiSyncState();
  }catch(error){E('fsConfigMessage').textContent=error.message;}finally{button.disabled=false;}
}
function renderFastaiJob(job){
  E('fsEndpoint').textContent='目标接口：'+job.api_url;
  var remaining=job.total-job.processed;
  E('fsMessage').textContent=job.message;
  E('fsProgress').max=Math.max(1,job.total);E('fsProgress').value=job.processed;
  E('fsCounts').textContent='进度 '+job.processed+' / '+job.total+' · 成功 '+job.succeeded+' · 失败 '+job.failed+' · 未处理 '+remaining;
  E('fsItems').innerHTML=job.items.length?job.items.map(function(item){
    var names={pending:'等待同步',running:'同步中',synced:'已同步',failed:'同步失败'};
    return '<tr><td class="mono">'+esc(item.email)+'</td><td><span class="fastai-status fastai-'+escAttr(item.status)+'">'+esc(names[item.status]||item.status)+'</span></td><td>'+esc(item.error||item.action||'—')+'</td></tr>';
  }).join(''):'<tr><td colspan="3">所有可同步邮箱均已同步，或尚无已配置收件的邮箱。</td></tr>';
  E('fsRetry').disabled=job.status==='running';
}
async function openFastaiLatest(){
  ensureFastaiDialogs();
  try{
    var state=await loadFastaiSyncState();
    if(!state.job){toast('暂无同步任务');return;}
    renderFastaiJob(state.job);if(!E('fastaiSyncDialog').open)E('fastaiSyncDialog').showModal();
  }catch(error){toast(error.message,true);}
}
async function startFastaiSync(){
  ensureFastaiDialogs();var dialog=E('fastaiSyncDialog');
  if(!dialog.open)dialog.showModal();
  E('fsMessage').textContent='正在准备同步…';E('fsRetry').disabled=true;
  try{
    var data=await fastaiRequest('/api/fastai-sync/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})});
    fastaiPollId=data.job.id;renderFastaiJob(data.job);
    await loadFastaiSyncState();
    if(!fastaiPolling)pollFastaiSync();
  }catch(error){E('fsMessage').textContent=error.message;E('fsRetry').disabled=false;}
}
async function pollFastaiSync(){
  fastaiPolling=true;
  try{
    while(fastaiPollId){
      var key=fastaiPollId,data=await fastaiRequest('/api/fastai-sync/jobs/'+encodeURIComponent(key));
      if(key!==fastaiPollId)continue;
      renderFastaiJob(data.job);await refreshEmails();await loadFastaiSyncState();
      if(data.job.status!=='running'){fastaiPollId=null;break;}
      await new Promise(function(resolve){setTimeout(resolve,1000);});
    }
  }catch(error){E('fsMessage').textContent='进度连接中断：'+error.message+'。后台任务仍会继续，可重新打开弹窗查看。';E('fsRetry').disabled=false;}
  finally{fastaiPolling=false;}
}
document.addEventListener('DOMContentLoaded',function(){
  loadFastaiSyncState().catch(function(){});
  setInterval(function(){if(!fastaiPolling)loadFastaiSyncState().catch(function(){});},5000);
});
