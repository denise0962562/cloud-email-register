const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(isPlus = true) {
  const fields = Object.fromEntries(['count','mode','fixedMinutes','minMinutes','maxMinutes','itemInterval','label']
    .map(key => [key, {value: key === 'mode' ? 'fixed' : key === 'label' ? 'auto' : '3'}]));
  fields.allSources = {checked:true}; fields.syncToFastai = {checked:false}; fields.sourceCount = {textContent:''};
  const inputs = [{value:'a@icloud.com',checked:false}, {value:'b@icloud.com',checked:false}];
  const context = {isPlus, targetKey:isPlus?'base_emails':'account_ids', byId:id=>fields[id],
    snapshot:{config:{base_emails:inputs.map(input=>input.value)}},
    document:{querySelectorAll:selector=>selector.endsWith(':checked')?inputs.filter(input=>input.checked):inputs}};
  const source = fs.readFileSync('static/auto_registration.js','utf8');
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function configFromForm()'), source.indexOf('function countdown()')), context);
  return {fields, inputs, context};
}

test('all sources selects and disables individual checkboxes and submits the mode', () => {
  const {fields,inputs,context} = setup();
  context.sourceSelection();
  assert.ok(inputs.every(input=>input.checked&&input.disabled));
  assert.equal(fields.sourceCount.textContent,'（2 个）');
  assert.equal(context.configFromForm().all_sources,true);
});

test('disabling all sources restores manual selection without affecting native registration', () => {
  const {fields,inputs,context} = setup();
  context.sourceSelection(); fields.allSources.checked=false; context.sourceSelection();
  assert.ok(inputs.every(input=>!input.disabled));
  inputs[1].checked=false;
  assert.deepEqual(Array.from(context.configFromForm().base_emails),['a@icloud.com']);
  assert.equal(context.configFromForm().all_sources,false);
  const native=setup(false); native.context.sourceSelection();
  assert.ok(!Object.hasOwn(native.context.configFromForm(),'all_sources'));
});

 test('分裂后同步开关随配置保存，普通自动注册不提交此字段', () => {
  const {fields,context} = setup();
  assert.equal(context.configFromForm().sync_to_fastai,false);
  fields.syncToFastai.checked=true;
  assert.equal(context.configFromForm().sync_to_fastai,true);
  assert.ok(!Object.hasOwn(setup(false).context.configFromForm(),'sync_to_fastai'));
 });
