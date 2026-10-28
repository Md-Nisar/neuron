const { chromium, login } = require('./lib');
(async () => {
  const b = await chromium.launch(); const { p } = await login(b);
  await p.getByRole('button', { name: 'Your data' }).click();
  await p.getByRole('textbox').fill('erase my data'); await p.getByRole('button', { name: 'Erase all my data' }).click();
  await p.getByRole('button', { name: /sign in/i }).waitFor(); console.log('erased'); await b.close();
})().catch(e => { console.error('FAIL', e.message.slice(0,300)); process.exit(1); });
