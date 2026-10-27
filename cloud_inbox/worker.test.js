import test from 'node:test';
import assert from 'node:assert/strict';
import worker, {extractCode, hashToken, readMessages} from './worker.js';
import {renderPage} from './page.js';

test('extracts verification codes from plain text and Chinese messages', () => {
  assert.equal(extractCode('Enter this temporary verification code to continue: 123456'), '123456');
  assert.equal(extractCode('您的验证码为：654321，请勿泄露'), '654321');
  assert.equal(extractCode('欢迎使用邮箱'), '');
});

test('filters an unexpected destination before returning any mail', async () => {
  const record = {api_token:'private-credential', destination:'isolated@fastaiapi.cloud'};
  let sentToken = '';
  const messages = await readMessages(record, async (url, options) => {
    sentToken = options.headers.Authorization;
    return Response.json({results:[
      {id:1,address:record.destination,raw:'From: Sender <sender@example.com>\r\nSubject: Your verification code\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nYour verification code is 123456'},
      {id:2,address:'other@fastaiapi.cloud',raw:'Subject: Other mailbox\r\n\r\nSecret 999999'},
    ]});
  });
  assert.equal(messages.length, 1);
  assert.equal(messages[0].code, '123456');
  assert.equal(sentToken, 'Bearer private-credential');
  assert.ok(!JSON.stringify(messages).includes('private-credential'));
});

test('rejects wrong public token and never exposes a mailbox credential', async () => {
  const secret = 'a'.repeat(43);
  const record = {id:'mbx_123456789',alias:'one@icloud.com',token_hash:await hashToken(secret),api_token:'private-credential',destination:'isolated@fastaiapi.cloud'};
  const env = {DB:{prepare(){return {bind(){return {first:async()=>record}}}}}};
  const denied = await worker.fetch(new Request('https://webmail.fastaiapi.cloud/m/'+record.id+'.'+'b'.repeat(43)), env);
  assert.equal(denied.status, 404);
  assert.ok(!(await denied.text()).includes('one@icloud.com'));
  const allowed = await worker.fetch(new Request('https://webmail.fastaiapi.cloud/m/'+record.id+'.'+secret), env);
  assert.equal(allowed.status, 200);
  const html = await allowed.text();
  assert.ok(html.includes('one@icloud.com'));
  assert.ok(!html.includes('private-credential'));
  assert.equal(allowed.headers.get('Cache-Control'), 'no-store');
});

test('page scripts are valid and mail content is rendered as text', () => {
  const html = renderPage('one@icloud.com','testnonce');
  new Function(html.split('<script nonce="testnonce">')[1].split('</script>')[0]);
  assert.ok(html.includes('detailBody\').textContent'));
  assert.ok(!html.includes('?jwt='));
});

test('admin registration requires an independent admin secret', async () => {
  const response = await worker.fetch(new Request('https://webmail.fastaiapi.cloud/m/_admin/mailboxes/mbx_123456789',{method:'PUT'}),{ADMIN_TOKEN:'admin-only'});
  assert.equal(response.status, 401);
});

test('撤销短链接校验邮箱归属，删除幂等且旧链接立即失效', async()=>{
 const id='mbx_123456789',secret='x'.repeat(43),tokenHash=await hashToken(secret);
 let record={id,alias:'old+tag@icloud.com',token_hash:tokenHash,destination:'box@fastaiapi.cloud'};
 const env={ADMIN_TOKEN:'private-admin',DB:{prepare(sql){return {bind(...args){return {
   first:async()=>record,
   run:async()=>{assert.equal(args[0],id);record=null}
 }}}}}};
 const call=(alias,hash=tokenHash)=>worker.fetch(new Request('https://webmail.fastaiapi.cloud/m/_admin/mailboxes/'+id,{
   method:'DELETE',headers:{Authorization:'Bearer private-admin','Content-Type':'application/json'},
   body:JSON.stringify({alias,token_hash:hash})}),env);
 assert.equal((await call('another@icloud.com')).status,409);
 assert.ok(record);
 assert.equal((await call('old+tag@icloud.com')).status,200);
 assert.equal((await call('old+tag@icloud.com')).status,200);
 const old=await worker.fetch(new Request('https://webmail.fastaiapi.cloud/m/'+id+'.'+secret),env);
 assert.equal(old.status,404);
});
