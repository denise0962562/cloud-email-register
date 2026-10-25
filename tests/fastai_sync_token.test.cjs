const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function panel() {
  const elements = new Map(), calls = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value:'', checked:false, style:{},
      addEventListener(event, handler) { this[event] = handler; }});
    return elements.get(id);
  };
  const state = {ok:true, config:{enabled:false, include_synced:false, api_url:'https://example.com/api/import',
    batch_size:1, interval_minutes:60, api_token_configured:true}, server_time:1000,
    logs:[], history:[], pending:1, eligible:1};
  const context = {document:{getElementById:element}, setInterval(){}, console,
    fetch:async (url, options) => {calls.push({url, options}); return {ok:true, json:async()=>state};}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('static/fastai_sync_panel.js', 'utf8'), context);
  return {element, calls, state, context};
}

test('发送页面保存新 Token，随后清空输入且不回显凭据', async () => {
  const p = panel(); await new Promise(setImmediate);
  p.element('apiToken').value = 'new-test-token';
  p.element('configForm').input();
  // 后台轮询不会覆盖尚未保存的输入。
  vm.runInContext('render(snapshot)', p.context);
  assert.equal(p.element('apiToken').value, 'new-test-token');
  await p.element('configForm').submit({preventDefault(){}});
  const body = JSON.parse(p.calls.find(call=>call.options?.method==='POST').options.body);
  assert.equal(body.api_token, 'new-test-token');
  assert.equal(p.element('apiToken').value, '');
  assert.match(p.element('tokenHint').textContent, /已配置/);
});

test('发送页面留空保留原 Token，勾选清除则显式提交空值', async () => {
  const p = panel(); await new Promise(setImmediate);
  await p.element('configForm').submit({preventDefault(){}});
  let body = JSON.parse(p.calls.find(call=>call.options?.method==='POST').options.body);
  assert.equal(Object.hasOwn(body, 'api_token'), false);
  p.calls.length = 0;
  p.element('clearToken').checked = true;
  await p.element('configForm').submit({preventDefault(){}});
  body = JSON.parse(p.calls.find(call=>call.options?.method==='POST').options.body);
  assert.equal(body.api_token, '');
});

test('邮箱列表配置弹窗也支持设置、保留和清除 Token', async () => {
  const elements = new Map();
  const E = id => {if (!elements.has(id)) elements.set(id, {value:'',checked:false}); return elements.get(id);};
  let body;
  const context = {E, refreshEmails:async()=>{}, console, document:{addEventListener(){}}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('static/fastai_sync.js', 'utf8'), context);
  context.fastaiRequest = async (url, options) => {
    body = JSON.parse(options.body);
    return {config:{api_url:'https://example.com/api/import',api_token_configured:body.api_token!==''}};
  };
  context.loadFastaiSyncState = async()=>{};
  E('fsApiUrl').value = 'https://example.com/api/import'; E('fsInterval').value = '60';
  for (const [input, clear, expected] of [['secret-value',false,'secret-value'], ['',false,undefined], ['',true,'']]) {
    E('fsApiToken').value = input; E('fsClearToken').checked = clear;
    await context.saveFastaiConfig();
    assert.equal(body.api_token, expected);
    assert.equal(E('fsApiToken').value, '');
  }
});
