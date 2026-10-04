const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ''; this.listeners = {}; }
  appendChild(child) { this.children.push(child); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}
const context = { window: {}, document: { createElement: (tag) => new Element(tag) } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../Archon/Portal/static/node-card.js'), 'utf8'), context);
const translate = (key,args={}) => key.replace(/\{(\w+)\}/g, (_, name) => args[name]?.i18nKey ? translate(args[name].i18nKey,args[name]) : args[name]);
const options = { t: (key) => key, bind: (node, key, args={}) => { node.textContent = translate(key,args); } };
function texts(node) { return [node.textContent, ...node.children.flatMap(texts)].join('\n'); }
test('always shows unconfigured status instead of hiding Node connectivity', () => {
  const panel = context.window.EverSparkNodeCard.render(undefined, options);
  assert.equal(panel.dataset.nodeStatus, 'unconfigured');
  assert.match(texts(panel), /Not configured/);
  assert.match(texts(panel), /SSH deployment does not verify Node registration/);
});
test('shows independent identity, hardware and capacity vs availability as text', () => {
  const node = { status: 'online', node_id: 'a'.repeat(32), hostname: '<img src=x onerror=alert(1)>',
    system: { os: 'Linux', architecture: 'x86_64' }, resources: {
      capacity: { cpu: 8, memory: 8*1024**3, disk: 100*1024**3, gpu: { G1: { vram: 24*1024**3 } } },
      allocatable: { cpu: 4, memory: 4*1024**3, disk: 50*1024**3, gpu: { G1: { vram: 12*1024**3 } } } } };
  const panel = context.window.EverSparkNodeCard.render(node, options);
  assert.match(texts(panel), /aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/);
  assert.match(texts(panel), /24.0 GiB/); assert.match(texts(panel), /12.0 GiB/);
  assert.match(texts(panel), /Linux \/ x86_64/);
  assert.match(texts(panel), /<img src=x onerror=alert\(1\)>/);
  const offline = context.window.EverSparkNodeCard.render({ ...node, status: 'offline' }, options);
  assert.doesNotMatch(texts(offline), /12.0 GiB/);
});
test('unknown dynamic resources never display as zero capacity', () => {
  assert.equal(context.window.EverSparkNodeCard.bytes(null), '—');
  assert.equal(context.window.EverSparkNodeCard.bytes(0), '0.0 GiB');
});
test('download result uses MB/s and the inclusive 50 MB/s threshold', () => {
  for (const [speed, expected] of [[49.9, /consider replacing/], [50, /qualified/]]) {
    const panel = context.window.EverSparkNodeCard.render({status: 'online', bandwidth: {
      status: 'completed', region: 'AS', server_region: 'AS', download_mb_s: speed, server_name: 'Fixture'
    }}, options);
    assert.match(texts(panel), expected);
    assert.match(texts(panel), /MB\/s/);
    assert.match(texts(panel), /Fixture/);
  }
  const failed = context.window.EverSparkNodeCard.render({status: 'online', bandwidth: {status: 'failed'}}, options);
  assert.match(texts(failed), /Unable to measure/);
  assert.doesNotMatch(texts(failed), /consider replacing/);
});
test('unverified and cross-region speeds never suggest replacing the Pod', () => {
  for (const metadata of [{}, {region: 'AS', server_region: 'NA'}]) {
    const panel = context.window.EverSparkNodeCard.render({status: 'online', bandwidth: {
      status: 'completed', download_mb_s: 1, ...metadata
    }}, options);
    assert.match(texts(panel), /reference only/);
    assert.doesNotMatch(texts(panel), /consider replacing|qualified/);
  }
});


test('Cloudflare samples are assessed without inventing a server region, and disclose their source',()=>{
  for(const speed of [49,50]) {
    const panel=context.window.EverSparkNodeCard.render({status:'online',bandwidth:{
      status:'completed',method:'cloudflare_http',server_url:'https://speed.cloudflare.com/__down',
      server_name:'Cloudflare (ICN)',server_colo:'ICN',download_mb_s:speed
    }},options);
    assert.match(texts(panel),speed>=50 ? /qualified/ : /consider replacing/);
    assert.match(texts(panel),/model sources may have different speeds/);
    assert.match(texts(panel),/Cloudflare edge: ICN/);
    assert.doesNotMatch(texts(panel),/region unverified/);
  }
});

test('default model downloads disclose scope and compare the target without judging the whole Pod', () => {
  for (const [speed, expected] of [[34.88, /below the 50 MB\/s target/], [50, /meets the 50 MB\/s target/]]) {
    const panel = context.window.EverSparkNodeCard.render({status: 'online', bandwidth: {
      status: 'completed', method: 'default_model_http', server_name: 'Hugging Face',
      model_filename: 'Illustrious-XL-v1.0.safetensors', download_mb_s: speed
    }}, options);
    assert.match(texts(panel), /Default model source download speed/);
    assert.match(texts(panel), expected);
    assert.match(texts(panel), /R2 and other sources may have different speeds/);
    assert.match(texts(panel), /Test model: Illustrious-XL-v1.0.safetensors/);
    assert.doesNotMatch(texts(panel), /consider replacing|region unverified/);
  }
});

test('Ookla results show network scope, actual server location, latency and optional loss', () => {
  for (const speed of [.223826, 97.372229]) {
    const panel = context.window.EverSparkNodeCard.render({status:'online',bandwidth:{
      status:'completed',method:'ookla_cli',download_mb_s:speed,upload_mb_s:95.52,
      latency_ms:8.655,packet_loss_percent:0,jitter_ms:.216,server_id:5249,
      server_name:'Fixture',server_location:'Seoul',server_country:'South Korea'
    }}, options);
    assert.match(texts(panel), /Network download speed/);
    assert.match(texts(panel), speed >= 50 ? /meets the 50 MB\/s reference target/ : /below the 50 MB\/s reference target/);
    assert.match(texts(panel), /Seoul \/ South Korea/);
    assert.match(texts(panel), /Latency: 8.65 ms · Packet loss: 0.00%/);
    assert.match(texts(panel), /model and cloud storage download speeds may differ/);
    assert.doesNotMatch(texts(panel), /consider replacing|region unverified|Node egress country/);
  }
  const unknown = context.window.EverSparkNodeCard.render({status:'online',bandwidth:{
    status:'completed',method:'ookla_cli',download_mb_s:1,latency_ms:102
  }}, options);
  assert.match(texts(unknown), /Packet loss: —/);
});

test('new network test states do not promise a 30-second download or label failure as slow', () => {
  const running=context.window.EverSparkNodeCard.render({status:'online',bandwidth:{status:'running',method:'ookla_cli'}}, options);
  assert.match(texts(running), /download and upload/);
  assert.doesNotMatch(texts(running), /30-second/);
  const terms=context.window.EverSparkNodeCard.render({status:'online',bandwidth:{status:'failed',method:'ookla_cli',error_code:'terms_required'}}, options);
  assert.match(texts(terms), /confirm Ookla CLI terms/);
});

test('WebUI confirmation is explicit, per Pod, survives polling and blocks duplicate requests', async () => {
  const nodes = node => [node, ...node.children.flatMap(nodes)];
  const raw = {status:'online',node_id:'consent-pod-a',bandwidth:{status:'failed',method:'ookla_cli',error_code:'terms_required'}};
  const calls=[]; let complete;
  const speedtest=(button, settings)=>{calls.push(settings);return new Promise(resolve=>{complete=resolve;});};
  const render=raw=>context.window.EverSparkNodeCard.render(raw,{...options,speedtest});
  const panel=render(raw);
  const checkbox=nodes(panel).find(node=>node.tag==='input');
  const button=nodes(panel).find(node=>node.tag==='button');
  assert.equal(checkbox.checked,false);assert.equal(button.disabled,true);
  assert.equal(nodes(panel).filter(node=>node.tag==='a').length,3);
  for(const link of nodes(panel).filter(node=>node.tag==='a')) {
    assert.match(link.href,/^https:\/\/www\.speedtest\.net\/about\/(eula|terms|privacy)$/);
    assert.equal(link.rel,'noopener noreferrer');
  }
  await button.listeners.click();assert.equal(calls.length,0);
  checkbox.checked=true;checkbox.listeners.change();assert.equal(button.disabled,false);
  const refreshed=render(raw);
  const refreshedCheckbox=nodes(refreshed).find(node=>node.tag==='input');
  const refreshedButton=nodes(refreshed).find(node=>node.tag==='button');
  assert.equal(refreshedCheckbox.checked,true);
  assert.equal(nodes(render({...raw,node_id:'consent-pod-b'})).find(node=>node.tag==='input').checked,false);
  const pending=refreshedButton.listeners.click();
  await button.listeners.click();assert.equal(calls.length,1);assert.equal(calls[0].acceptTerms,true);
  assert.equal(nodes(render(raw)).find(node=>node.tag==='button').disabled,true);
  complete();await pending;
  const running=render({...raw,bandwidth:{status:'running',method:'ookla_cli'}});
  assert.equal(nodes(running).filter(node=>node.tag==='input').length,0);
  assert.equal(nodes(running).find(node=>node.tag==='button').disabled,true);
});
