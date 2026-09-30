const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../Archon/Portal/static/node-connection.js'), 'utf8');
function setup(api, timers = {}) {
  const button = { disabled: false };
  const form = { handlers: {}, querySelector: () => button, addEventListener(name, handler) { this.handlers[name] = handler; } };
  const input = { value: 'tskey-auth-test' }, mode = { value: 'once' }, status = {}, feedback = { classList: { toggle() {} } };
  const fields = { '#nodeConnectionForm': form, '#nodeConnectionKey': input, '#nodeConnectionReusable': mode, '#nodeConnectionStatus': status, '#nodeConnectionFeedback': feedback };
  const context = { window: {}, document: { querySelector: name => fields[name] }, AbortController, setTimeout, clearTimeout, ...timers };
  vm.runInNewContext(source, context);
  const control = context.window.EverSparkNodeConnection.initialize({ api, bind: (node, key) => { node.textContent = key; }, notice() {} });
  return { button, input, mode, status, feedback, control, submit: () => form.handlers.submit({ preventDefault() {} }) };
}
test('failed configuration shows inline error and a second submission succeeds', async () => {
  let attempts = 0;
  const ui = setup(async () => { if (++attempts === 1) throw new Error('This Tailscale key was already used; enter a new key'); return { ready: true }; });
  await ui.submit();
  assert.match(ui.feedback.textContent, /already used/);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.input.value, 'tskey-auth-test');
  ui.input.value = 'tskey-auth-new';
  await ui.submit();
  assert.equal(ui.feedback.textContent, 'Automatic Node connection configured.');
  assert.equal(ui.input.value, '');
  assert.equal(ui.button.disabled, false);
});
test('reusable selection is sent and success does not depend on a subsequent GET', async () => {
  const calls = [];
  const ui = setup(async (url, options) => { calls.push(options); return { ready: true, reusable: true }; });
  ui.mode.value = 'reusable';
  await ui.submit();
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(calls[0].body).reusable, true);
  assert.match(ui.status.textContent, /additional rentals/);
});
test('timeout restores the button and leaves inline retry guidance', async () => {
  const ui = setup(async (url, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error(), { name: 'AbortError' })));
  }), { setTimeout: callback => setTimeout(callback, 1) });
  await ui.submit();
  assert.equal(ui.button.disabled, false);
  assert.match(ui.feedback.textContent, /timed out/);
});
test('concurrent refresh cannot overwrite a newer successful configuration', async () => {
  let resolveGet;
  const ui = setup(async (url, options) => options.method ? { ready: true } : new Promise(resolve => { resolveGet = resolve; }));
  const refresh = ui.control.refresh();
  await ui.submit();
  resolveGet({ ready: false });
  await refresh;
  assert.equal(ui.status.textContent, 'Automatic Node connection is ready for the next rental.');
});
