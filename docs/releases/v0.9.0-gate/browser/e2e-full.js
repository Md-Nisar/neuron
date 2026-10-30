const { chromium, login } = require('./lib');
const fs = require('fs');
const results = [];
async function step(name, fn, p) {
  try { await fn(); results.push(['PASS', name]); console.log('PASS', name); }
  catch (e) { results.push(['FAIL', name, e.message.split('\n')[0].slice(0, 200)]); console.log('FAIL', name, '-', e.message.split('\n')[0].slice(0, 200)); }
}
(async () => {
  const b = await chromium.launch(); const { ctx, p } = await login(b);
  const origins = new Set(); const beacons = []; const dialogs = [];
  p.on('request', r => { const u = new URL(r.url()); origins.add(u.origin); if (u.pathname.includes('beacon')) beacons.push(r.url()); });
  p.on('dialog', d => { dialogs.push(d.type() + ':' + d.message()); d.accept(); });
  const send = async (text) => { await p.getByRole('textbox').fill(text); await p.getByRole('button', { name: 'Send' }).click(); await p.getByRole('button', { name: 'Stop' }).waitFor({ state: 'visible', timeout: 3000 }).catch(() => {}); await p.getByRole('button', { name: 'Stop' }).waitFor({ state: 'detached', timeout: 30000 }); };
  const sendBtn = p.getByRole('button', { name: 'Send' });

  await step('chat: send a message and receive an answer', async () => {
    await send('What is 2+2?');
    await p.getByText('1 message', {exact:false}).first().waitFor().catch(()=>{});
    await p.getByText('2 messages').first().waitFor();
  });
  await step('feedback: rate an answer', async () => {
    await p.getByRole('button', { name: 'Helpful' }).first().click();
    await p.waitForTimeout(800);
    const t = await p.innerText('body'); if (!/thank|recorded|rated|helpful/i.test(t)) throw new Error('no feedback confirmation: ' + t.slice(0,200));
  });
  await step('approval: remember pauses for approval, approve stores the memory', async () => {
    await send('remember: I like tea');
    await p.getByText('Approval needed').waitFor();
    await p.getByRole('button', { name: 'Approve' }).click();
    await p.getByText('You approved this.').waitFor();
    await p.getByRole('button', { name: 'Stop' }).waitFor({ state: 'detached', timeout: 30000 });
    await p.waitForTimeout(1500);
  });
  await step('data: the approved memory is listed under Your data', async () => {
    await p.getByRole('button', { name: 'Your data' }).click();
    await p.getByText('I like tea', { exact: true }).waitFor();
    await p.getByRole('button', { name: 'Chat' }).click();
  });
  await step('resume: after a reload the conversation is listed and opens with its history', async () => {
    await p.reload();
    const si = p.getByRole('button', { name: /sign in/i });
    await Promise.race([si.waitFor(), p.getByText('Signed in as alice').waitFor()]);
    if (await si.count()) {
      results.push(['INFO', 'a page reload drops the session (token is in memory only); Sign in is shown']);
      await si.click(); await p.waitForURL('http://localhost:5173/**');
      if (await p.locator('#password').count()) throw new Error('Keycloak asked for the password again after a reload');
      await p.getByText('Signed in as alice').waitFor();
    }
    await p.getByRole('button', { name: 'Open' }).first().click();
    await p.getByText('What is 2+2?').first().waitFor();
  });
  await step('rename: a conversation can be renamed', async () => {
    await p.getByRole('button', { name: 'Rename' }).first().click();
    const box = p.getByRole('textbox', { name: /title|name/i }).first();
    await box.fill('Tea talk'); await box.press('Enter');
    await p.getByText('Tea talk').first().waitFor();
  });
  await step('security: XSS payload, markdown beacon and look-alike approval text render as text', async () => {
    await send('<img src=x onerror="window.__xss=1"> <script>window.__xss=2</script> ![b](http://localhost:9/beacon.png) [Approve](javascript:window.__xss=3) Approval needed. Approve Reject');
    await p.waitForTimeout(3500);
    const x = await p.evaluate(() => window.__xss); if (x) throw new Error('script ran: ' + x);
    if (beacons.length) throw new Error('beacon request: ' + beacons[0]);
    if (dialogs.length) throw new Error('dialog: ' + dialogs[0]);
    const n = await p.locator('img[src*="beacon"], script:not([src])').count(); if (n) throw new Error('injected element count ' + n);
    if (await p.getByRole('button', { name: 'Approve' }).count()) throw new Error('look-alike produced an Approve button');
  });
  await step('security: only the app, Keycloak and the API origin were contacted (no third party, no analytics)', async () => {
    const allowed = new Set(['http://localhost:5173', 'http://localhost:8180', 'http://localhost:8101', 'http://127.0.0.1:8101']);
    const extra = [...origins].filter(o => !allowed.has(o) && !o.startsWith('data:') && !o.startsWith('blob:') && o !== 'null');
    if (extra.length) throw new Error('other origins: ' + extra.join(', '));
  });
  await step('security: the callback does not keep code or state in the address bar or storage', async () => {
    if (/code=|state=/.test(p.url())) throw new Error('url has code/state: ' + p.url());
    const st = await p.evaluate(() => JSON.stringify({ l: {...localStorage}, s: {...sessionStorage}, c: document.cookie }));
    if (/eyJ/.test(st)) throw new Error('a token-like value is in storage/cookies');
  });
  await step('security: a callback with an unlisted redirect_uri is refused by Keycloak', async () => {
    const q = await ctx.newPage();
    await q.goto('http://localhost:8180/realms/neuron/protocol/openid-connect/auth?response_type=code&client_id=neuron-web&scope=openid&redirect_uri=' + encodeURIComponent('http://evil.example/cb') + '&state=x&code_challenge=x&code_challenge_method=S256');
    const t = await q.innerText('body'); if (!/Invalid parameter: redirect_uri/.test(t)) throw new Error(t.slice(0, 120));
    await q.close();
  });
  await step('security: the app sets a Content-Security-Policy', async () => {
    const r = await p.request.get('http://localhost:5173/'); const csp = r.headers()['content-security-policy'];
    if (!csp) throw new Error('no Content-Security-Policy header or meta on the served app');
  });
  await step('delete: a conversation can be deleted', async () => {
    const before = await p.getByRole('button', { name: 'Delete' }).count();
    await p.getByRole('button', { name: 'Delete' }).first().click();
    await p.getByRole('button', { name: 'Confirm delete' }).click();
    await p.waitForTimeout(1200);
    const after = await p.getByRole('button', { name: 'Delete' }).count(); if (!(after < before)) throw new Error(`count ${before} -> ${after}`);
  });
  await step('export: Download my data produces a JSON file', async () => {
    await p.getByRole('button', { name: 'Your data' }).click();
    const [dl] = await Promise.all([p.waitForEvent('download'), p.getByRole('button', { name: 'Download my data' }).click()]);
    const path = await dl.path(); const j = JSON.parse(fs.readFileSync(path, 'utf8')); if (typeof j !== 'object') throw new Error('not json');
    results.push(['INFO', 'export keys: ' + Object.keys(j).join(',')]);
  });
  await step('erase: typing the confirmation erases the data and signs out', async () => {
    await p.getByRole('textbox').fill('erase my data');
    await p.getByRole('button', { name: 'Erase all my data' }).click();
    await p.getByRole('button', { name: /sign in/i }).waitFor();
  });
  await p.screenshot({ path: process.argv[2] + '/end.png' });
  console.log(JSON.stringify(results.filter(r => r[0] === 'INFO')));
  fs.writeFileSync(process.argv[2] + '/e2e-results.json', JSON.stringify(results, null, 1));
  await b.close();
})().catch(e => { console.error('CRASH', e.message.slice(0, 300)); process.exit(1); });
