const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
function extract(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function element(tag) {
  return {tag, children: [], append(...items) {this.children.push(...items);},
    appendChild(item) {this.children.push(item);}, replaceChildren(...items) {this.children = items;}};
}
const stage = element('stage'), audioHistory = element('history'), gallery = element('gallery');
const completedImage = {forge: 'image', status: 'completed', result: {outputs: [{images: [{filename: 'ready.png'}]}]}};
const context = {document: {createElement: element}, elements: {resultStage: stage, galleryGrid: gallery}, uiText: (el, value) => {el.textContent = value;},
  URLSearchParams, encodeURIComponent, t: x => x, setGenerationState() {},
  transientApiError: () => false, setTimeout: fn => fn(),
  imageButton: image => ({tag: 'image', ...image}), $: () => audioHistory};
vm.createContext(context);
vm.runInContext(extract('async function waitForGeneration(', 'async function generate(')
  + extract('function renderCreation(', 'function downloadOutputsArchive('), context);
(async () => {
  context.api = async () => ({job: {status: 'failed', error: 'Audio Forge synthesize failed: backend detail',
    tasks: [completedImage, {forge: 'audio', status: 'failed'}]}});
  await assert.rejects(context.waitForGeneration('job'), /backend detail/);
  assert.equal(stage.children[0].children[0].filename, 'ready.png');
  context.renderCreation({tasks: [{forge: 'audio', status: 'completed', result: {audio: [{filename: 'speech.wav', text: '<hello>', voice_description: 'young female voice'}]}}]});
  const card = stage.children[0].children[0];
  assert.equal(card.children[0].textContent, '<hello>');
  assert.equal(card.children[1].controls, true);
  assert.equal(card.children[2].download, 'speech.wav');
  assert.equal(card.children[3].textContent, '声音要求：young female voice');
  context.api = async path => {
    assert.equal(path, '/api/audio/history?limit=36');
    return {audio: [{filename: 'past.wav'}]};
  };
  await context.loadAudioHistory();
  assert.equal(audioHistory.children[0].children[1].src, '/api/audio/file?filename=past.wav');
  context.api = async () => {throw new Error('Selected Audio node offline');};
  await context.loadAudioHistory();
  assert.equal(audioHistory.children[0].textContent, 'Selected Audio node offline');
  let releaseAudio;
  context.api = path => path.startsWith('/api/audio/')
    ? new Promise(resolve => {releaseAudio = resolve;})
    : Promise.resolve({images: [{filename: 'gallery.png'}]});
  await Promise.race([context.loadHistory(), new Promise((_, reject) => setTimeout(() => reject(new Error('Image history waited for audio')), 100))]);
  assert.equal(gallery.children[0].filename, 'gallery.png');
  releaseAudio({audio: []});
  await new Promise(resolve => setImmediate(resolve));
  context.api = async path => {
    if (path.startsWith('/api/audio/')) return {audio: [{filename: 'independent.wav'}]};
    throw new Error('Image Forge offline');
  };
  await context.loadHistory();
  assert.equal(gallery.children[0].textContent, 'Image Forge offline');
  assert.equal(audioHistory.children[0].children[1].src, '/api/audio/file?filename=independent.wav');
  console.log('Audio results, partial generation and independent histories: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
