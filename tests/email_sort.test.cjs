const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function load(){const context={renderAliasTable:()=>{}};vm.createContext(context);vm.runInContext(fs.readFileSync('static/email_sort.js','utf8'),context);return context;}
const names=rows=>Array.from(rows,r=>r.email);
test('default order compares ISO, epoch seconds and milliseconds; missing dates last without mutating source',()=>{
 const c=load(),rows=[{email:'iso',created_at:'2026-10-22T01:00:00Z'},{email:'missing'},{email:'seconds',created_at:1792634400},{email:'milliseconds',created_at:1792638000000}];
 assert.deepEqual(names(c.sortEmailRecords(rows)),['milliseconds','seconds','iso','missing']);
 assert.deepEqual(names(rows),['iso','missing','seconds','milliseconds']);
});
test('registration header toggles ascending and invalid dates remain last',()=>{
 const c=load();c.toggleEmailSort('created_at');
 assert.deepEqual(names(c.sortEmailRecords([{email:'late',created_at:'2026-10-22T04:00:00Z'},{email:'invalid',created_at:'bad'},{email:'early',created_at:'2026-10-21T04:00:00Z'}])),['early','late','invalid']);
 assert.equal(c.emailSortDirection,'asc');c.toggleEmailSort('created_at');assert.equal(c.emailSortDirection,'desc');
});
test('sync header starts descending, then ascends and retains selected field for subsequent refreshes',()=>{
 const c=load();c.toggleEmailSort('fastai_synced_at');
 const rows=[{email:'first',fastai_synced_at:100},{email:'second',fastai_synced_at:200},{email:'never',fastai_synced_at:null}];
 assert.deepEqual(names(c.sortEmailRecords(rows)),['second','first','never']);
 c.toggleEmailSort('fastai_synced_at');assert.deepEqual(names(c.sortEmailRecords(rows)),['first','second','never']);
 assert.deepEqual(names(c.sortEmailRecords(rows.slice())),['first','second','never']);
});
