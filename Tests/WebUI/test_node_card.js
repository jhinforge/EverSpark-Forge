const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.textContent = ''; }
  appendChild(child) { this.children.push(child); }
  addEventListener() {}
}
const context = { window: {}, document: { createElement: (tag) => new Element(tag) } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../Archon/Portal/static/node-card.js'), 'utf8'), context);
const options = { t: (key) => key, bind: (node, key, args={}) => { node.textContent = key.replace(/\{(\w+)\}/g, (_, name) => args[name]?.i18nKey || args[name]); } };
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
      status: 'completed', download_mb_s: speed, server_name: 'Fixture'
    }}, options);
    assert.match(texts(panel), expected);
    assert.match(texts(panel), /MB\/s/);
    assert.match(texts(panel), /Fixture/);
  }
  const failed = context.window.EverSparkNodeCard.render({status: 'online', bandwidth: {status: 'failed'}}, options);
  assert.match(texts(failed), /failed/);
  assert.doesNotMatch(texts(failed), /consider replacing/);
});
