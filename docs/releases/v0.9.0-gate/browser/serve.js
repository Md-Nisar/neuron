const http = require('http'), fs = require('fs'), path = require('path');
const root = path.resolve(__dirname, '../../../../web/dist');
const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.json': 'application/json' };
http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let f = path.join(root, p); if (!f.startsWith(root) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { f = path.join(root, 'index.html'); p = '/index.html'; }
  const h = { ...cfg.headers, 'Content-Type': types[path.extname(f)] || 'application/octet-stream' };
  h['Cache-Control'] = p.startsWith('/assets/') ? cfg.cache['/assets/*'] : cfg.cache['/index.html'];
  res.writeHead(200, h); fs.createReadStream(f).pipe(res);
}).listen(5173, '127.0.0.1');
