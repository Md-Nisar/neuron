const { chromium, login } = require('./lib');
const fs = require('fs');
(async () => {
  const b = await chromium.launch(); const { p } = await login(b); const out = [];
  // CSP blocks an injected inline script
  const violations = []; await p.exposeFunction('__v', d => violations.push(d));
  await p.evaluate(() => { document.addEventListener('securitypolicyviolation', e => window.__v(e.violatedDirective)); });
  await p.evaluate(() => { const s = document.createElement('script'); s.textContent = 'window.__inline = 1'; document.body.appendChild(s); });
  await p.waitForTimeout(500);
  const ran = await p.evaluate(() => window.__inline);
  out.push(['csp-inline-script', ran ? 'FAIL: inline script ran' : 'PASS: blocked (' + violations.join(',') + ')']);
  console.log(out.at(-1).join(' '));
  // silent renew
  const reqs = []; const t0 = Date.now();
  p.on('request', r => { if (r.url().includes(':8180')) reqs.push(Math.round((Date.now() - t0) / 1000) + 's ' + r.method() + ' ' + r.url().replace('http://localhost:8180/realms/neuron/protocol/openid-connect', '').slice(0, 70)); });
  p.on('framenavigated', f => { if (f !== p.mainFrame()) reqs.push(Math.round((Date.now() - t0) / 1000) + 's frame ' + f.url().slice(0, 90)); });
  await p.waitForTimeout(7 * 60 * 1000);
  const body = await p.innerText('body');
  const signedIn = /Signed in as alice/.test(body), ended = /session ended/i.test(body);
  out.push(['after-7-min', { signedIn, sessionEndedText: ended, page: body.replace(/\n+/g, ' | ').slice(0, 220) }]);
  if (signedIn) {
    await p.getByRole('textbox').fill('still there?'); await p.getByRole('button', { name: 'Send' }).click();
    await p.getByRole('button', { name: 'Stop' }).waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    await p.getByRole('button', { name: 'Stop' }).waitFor({ state: 'detached', timeout: 30000 }).catch(() => {});
    out.push(['chat-after-7-min', /still there\?/.test(await p.innerText('body'))]);
  }
  out.push(['keycloak-requests', reqs]);
  console.log(JSON.stringify(out, null, 1));
  fs.writeFileSync(process.argv[2] + '/e2e-renew.json', JSON.stringify(out, null, 1));
  await b.close();
})().catch(e => { console.error('CRASH', e.message.slice(0, 300)); process.exit(1); });
