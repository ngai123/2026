const http = require('http');
const fs = require('fs');
const path = require('path');
const dir = path.dirname(__filename || '.');

const server = http.createServer((req, res) => {
  let filePath = req.url === '/' ? '/documentation.html' : req.url;
  filePath = path.join(process.cwd(), filePath);
  const ext = path.extname(filePath);
  const types = { '.html': 'text/html', '.hex': 'text/plain', '.js': 'text/javascript' };
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
    res.end(data);
  });
});

server.listen(8123, () => console.log('Serving on http://localhost:8123'));
