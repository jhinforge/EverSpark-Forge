const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../Archon/Portal/static/forge-node-selection.js'), 'utf8');
function setup(api, changed = async () => {}) {
  const summary = {};
  function element() { return { children: [], handlers: {}, appendChild(child) { this.children.push(child); }, addEventListener(name, handler) { this.handlers[name] = handler; } }; }
  const context = { window: {}, document: { querySelector: () => summary, createElement: element } };
  vm.runInNewContext(source, context);
  const control = context.window.EverSparkForgeNodes.initialize({ api, changed,
    bind: (node, value) => { node.textContent = value; }, notice() {} });
  return { control, summary };
}
const machine = { id: 99, actual_status: 'running', node: { node_id: 'a'.repeat(32), status: 'online' },
  forge: { status: 'ready' }, image_forge: { status: 'ready' } };
test('Image choice posts Node identity and refreshes generation only after success', async () => {
  const calls = [], changes = [];
  const ui = setup(async (url, options) => { calls.push([url, JSON.parse(options.body)]); return { bindings: { image: machine.node.node_id }, ready: false }; }, async state => changes.push(state));
  const panel = ui.control.render(machine);
  await panel.children[1].handlers.click();
  assert.deepEqual(calls, [['/api/forge-bindings', { forge: 'image', node_id: machine.node.node_id }]]);
  assert.equal(changes.length, 1);
  assert.match(ui.summary.textContent, /Select a ready Concept/);
});
test('offline or unready Forge buttons are disabled', () => {
  const ui = setup(async () => ({}));
  const panel = ui.control.render({ ...machine, forge: { status: 'verification_required' }, node: { ...machine.node, status: 'offline' } });
  assert.ok(panel.children.every(button => button.disabled));
  const online = ui.control.render({ ...machine, image_forge: { status: 'deploying' } });
  assert.equal(online.children[0].disabled, false);
  assert.equal(online.children[1].disabled, true);
});
test('persisted selections mark current Nodes and show generation readiness', async () => {
  const ui = setup(async () => ({ bindings: { concept: machine.node.node_id, image: machine.node.node_id }, ready: true }));
  await ui.control.refresh();
  const panel = ui.control.render(machine);
  assert.equal(panel.children[0].textContent, 'Selected Concept Node');
  assert.equal(panel.children[1].textContent, 'Selected Image Node');
  assert.ok(panel.children.every(button => button.disabled));
  assert.match(ui.summary.textContent, /Open Create/);
});
test('failed binding remains retryable and shows its error beside the connection area', async () => {
  let attempts = 0, changed = 0;
  const ui = setup(async () => { if (++attempts === 1) throw new Error('Select an online Node'); return { bindings: { image: machine.node.node_id }, ready: false }; }, async () => changed++);
  const button = ui.control.render(machine).children[1];
  await button.handlers.click();
  assert.equal(button.disabled, false);
  assert.equal(changed, 0);
  assert.equal(ui.summary.textContent, 'Select an online Node');
  await button.handlers.click();
  assert.equal(changed, 1);
});
