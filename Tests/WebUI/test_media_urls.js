const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("Archon/Portal/static/app.js", "utf8");
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
function element(tag) {
  return {tag, children: [], listeners: {}, complete: false, readyState: 0, paused: true,
    append(...items) {this.children.push(...items);},
    appendChild(item) {this.children.push(item);},
    addEventListener(name, callback) {this.listeners[name] = callback;},
    play() {return Promise.resolve();}};
}
const viewer = element("viewer");
viewer.showModal = () => {};
const context = {
  document: {createElement: element},
  elements: {viewerImage: viewer, imageViewer: viewer},
  window: {location: {protocol: "http:", href: "http://127.0.0.1:8780/"},
           setTimeout() {return 1;}, clearTimeout() {}},
  URL, encodeURIComponent, uiAttr() {}
};
vm.createContext(context);
vm.runInContext(extract("function imageButton(", "function renderResults(")
  + extract("function audioCard(", "async function loadAudioHistory("), context);
const direct = "http://100.66.77.88:1234/file?signature=fixture";
const image = {filename: "render.png", url: direct, fallback_url: "/api/image/view?filename=render.png"};
let card = context.imageButton(image, "result");
assert.equal(card.children[0].src, direct);
card.children[0].listeners.error();
assert.equal(card.children[0].src, image.fallback_url);
card.listeners.click();
assert.equal(viewer.src, image.fallback_url);
const audio = {filename: "speech.wav", url: direct, fallback_url: "/api/audio/file?filename=speech.wav"};
card = context.audioCard(audio);
assert.equal(card.children[1].src, direct);
assert.equal(card.children[2].href, audio.fallback_url);
card.children[1].listeners.error();
assert.equal(card.children[1].src, audio.fallback_url);
context.window.location.protocol = "https:";
assert.equal(context.imageButton(image, "gallery").children[0].src, image.fallback_url);
assert.equal(context.audioCard(audio).children[1].src, audio.fallback_url);
console.log("Direct image/audio URLs, error fallback and HTTPS fallback passed");
