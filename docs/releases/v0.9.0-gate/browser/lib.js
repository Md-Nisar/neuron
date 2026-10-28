const { chromium } = require('playwright');
exports.login = async (b, user='alice') => {
  const ctx = await b.newContext(); const p = await ctx.newPage();
  p.setDefaultTimeout(20000);
  await p.goto('http://localhost:5173/'); await p.getByRole('button', { name: /sign in/i }).click();
  await p.fill('#username', user); await p.fill('#password', 'dev-only-' + user); await p.click('#kc-login');
  await p.waitForURL('http://localhost:5173/**'); await p.getByText('Signed in as ' + user).waitFor();
  return { ctx, p };
};
exports.chromium = chromium;
