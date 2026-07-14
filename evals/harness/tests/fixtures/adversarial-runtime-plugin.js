'use strict';
globalThis.__WP_GENERATED_RUNTIME_MARKER__ = true;
globalThis.__WP_GENERATED_EDITOR_RUNTIME_MARKER__ = true;
const wpRuntimeDenied = url => fetch(url, {signal: AbortSignal.timeout(1500)}).then(() => false, () => true);
const wpRuntimeSocketDenied = () => new Promise(resolve => {
  const socket = new WebSocket('wss://example.com/generated-runtime');
  socket.onopen = () => resolve(false); socket.onerror = () => resolve(true);
  setTimeout(() => resolve(true), 2000);
});
const wpRuntimeNavigationDenied = label => new Promise(resolve => {
  const frame = document.createElement('iframe'); frame.hidden = true;
  frame.name = 'wp-runtime-navigation-sink-' + label; document.body.append(frame);
  const form = document.createElement('form'); form.hidden = true; form.method = 'GET';
  form.action = 'https://example.com/generated-navigation-' + label; form.target = frame.name;
  document.body.append(form); form.submit();
  setTimeout(() => {
    form.remove(); frame.remove(); resolve(true);
  }, 500);
});
const wpRuntimeGeneratedDenials = async label => {
  const results = {
    loopback: await wpRuntimeDenied('http://127.0.0.1:8080/generated-' + label),
    rfc1918: await wpRuntimeDenied('http://10.0.0.1/generated-' + label),
    metadata: await wpRuntimeDenied('http://169.254.169.254/generated-' + label),
    public_ip: await wpRuntimeDenied('http://93.184.216.34/generated-' + label),
    public_dns: await wpRuntimeDenied('https://example.com/generated-' + label),
    database_peer: await wpRuntimeDenied('http://database:3306/generated-' + label),
    host_gateway: await wpRuntimeDenied('http://host.docker.internal/generated-' + label),
    websocket: await wpRuntimeSocketDenied(),
    webrtc: (() => { try { new RTCPeerConnection(); return false; } catch (_) { return true; } })(),
    service_worker: !navigator.serviceWorker || await navigator.serviceWorker.register('/generated-worker.js').then(() => false, () => true),
    external_navigation: await wpRuntimeNavigationDenied(label),
    download: true,
    popup: window.open('https://example.com/generated-popup') === null,
  };
  const sink = document.createElement('iframe'); sink.hidden = true;
  sink.name = 'wp-runtime-download-sink-' + label; document.body.append(sink);
  const link = document.createElement('a'); link.href = 'https://example.com/generated-download';
  link.download = 'generated.txt'; link.target = sink.name; document.body.append(link); link.click();
  setTimeout(() => { link.remove(); sink.remove(); }, 2000);
  return results;
};
if (typeof document !== 'undefined') {
  globalThis.__WP_GENERATED_RUNTIME_DENIALS__ = wpRuntimeGeneratedDenials('frontend');
  globalThis.__WP_GENERATED_EDITOR_DENIALS__ = wpRuntimeGeneratedDenials('editor');
}
globalThis.wpRuntimeAdversarialMemory = () => { const items=[]; while (true) { const item=new Uint8Array(8*1024*1024); item.fill(1); items.push(item); } };
globalThis.wpRuntimeAdversarialCpu = () => { while (true) {} };
globalThis.wpRuntimeAdversarialFd = () => { const fs=require('fs'), items=[]; for(let i=0;i<2048;i++){ try { items.push(fs.openSync('/dev/null','r')); } catch (_) { return true; } } return false; };
globalThis.wpRuntimeAdversarialProcess = async () => { const {spawn}=require('child_process'), items=[]; let failed=false; for(let i=0;i<256;i++){ const child=spawn('/bin/sleep',['2']); child.once('error',()=>{failed=true;}); items.push(child); } await new Promise(resolve=>setTimeout(resolve,750)); for(const child of items) child.kill('SIGKILL'); return failed; };
globalThis.wpRuntimeAdversarialConsole = () => console.error('x'.repeat(65536));
globalThis.wpRuntimeAdversarialStorage = (root,kind) => { const fs=require('fs'), path=require('path'), dir=path.join(root,'.wp-runtime-generated'); fs.rmSync(dir,{recursive:true,force:true}); fs.mkdirSync(dir); let failed=false; if(kind==='bytes'){ const payload=Buffer.alloc(1024*1024,1); for(let i=0;i<256;i++){ try{fs.writeFileSync(path.join(dir,String(i)),payload)}catch(_){failed=true;break} } } else { for(let i=0;i<20000;i++){ try{fs.writeFileSync(path.join(dir,String(i)),'')}catch(_){failed=true;break} } } fs.rmSync(dir,{recursive:true,force:true}); fs.mkdirSync(dir); fs.writeFileSync(path.join(dir,'recovered'),'ok'); fs.rmSync(dir,{recursive:true,force:true}); return failed; };
