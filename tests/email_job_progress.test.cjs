const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('批量任务将账号跳过计入已处理进度，同时保留提交前筛掉的数量', () => {
  const source = fs.readFileSync('static/email_list.js','utf8');
  const context = {};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function emailJobView('), source.indexOf('function renderEmailTask(')), context);
  const view = context.emailJobView({skipped:2}, {total:9,total_created:3,total_errors:1,total_skipped:5,
    events:[{skipped:true,base_email:'base@icloud.com'}]});
  assert.equal(view.skipped,7);
  assert.equal(view.success+view.failed+view.processedSkipped,view.total);
  assert.equal(view.rows[0].base_email,'base@icloud.com');
});
