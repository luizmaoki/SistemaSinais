// Local browser containers need the same loopback issuer/callback URLs as the host.
// These TCP forwarders preserve HTTP Host and never inspect credentials or cookies.
const net = require('node:net');
const { spawn } = require('node:child_process');
const targets = process.env.E2E_AUTH_MODE === 'oidc'
  ? [[13000, 'web', 3000], [18080, 'keycloak', 8080]]
  : [[3000, 'web', 3000]];
const servers = targets.map(([port, host, targetPort]) => net.createServer(client => {
  const upstream = net.connect(targetPort, host);
  client.on('error', () => upstream.destroy());
  upstream.on('error', () => client.destroy());
  client.on('close', () => upstream.destroy());
  upstream.on('close', () => client.destroy());
  client.pipe(upstream).pipe(client);
}));
Promise.all(servers.map((server, index) => new Promise((resolve, reject) => {
  server.on('error', reject);
  server.listen(targets[index][0], '127.0.0.1', resolve);
}))).then(() => {
  const child = spawn('npm', ['run', 'test:e2e'], {stdio:'inherit', env:process.env});
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
  child.on('error', () => { servers.forEach(server => server.close()); process.exit(1); });
  child.on('exit', code => { servers.forEach(server => server.close()); process.exit(code ?? 1); });
}).catch(() => process.exit(1));
