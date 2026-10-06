const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
const functions = source.slice(source.indexOf('function renderCloudConfiguration('), source.indexOf('async function loadRemoteStorage('));
function node() {
  const classes = new Set();
  return {value:'', disabled:false, textContent:'', children:[], classList:{
    toggle(key,on){on ? classes.add(key) : classes.delete(key);},
    add(key){classes.add(key);}, contains(key){return classes.has(key);}},
    listeners:{}, setAttribute(key,value){this[key]=value;},
    replaceChildren(){this.children=[];}, append(...children){this.children.push(...children);},
    appendChild(child){this.children.push(child);}, addEventListener(event,handler){this.listeners[event]=handler;}};
}
function setup(data) {
  const nodes = {}, panels = [node(),node(),node()];
  let cloudLoads = 0;
  const context = {state:{cloudBrowserPath:'', cloudConfiguration:null, cloudConfigurationEpoch:0},
    $: id => nodes[id] ||= node(), $$: selector => selector === '[data-cloud-storage]' ? panels : [],
    document:{createElement:node}, i18n:{unbind(){}}, t:text=>text,
    uiText(node,text){node.textContent=text;}, uiAttr(node,key,text){node.setAttribute(key,text);}, api:async()=>data,
    loadRemoteStorage:async()=>{cloudLoads++;}, loadBackup:async()=>{cloudLoads++;}, loadRestorePoints:async()=>{cloudLoads++;}, showNotice(){}};
  vm.createContext(context); vm.runInContext(functions,context);
  return {context,nodes,panels,cloudLoads:()=>cloudLoads};
}
test('unconfigured and imported-only storage hides every cloud operation without scanning',async()=>{
  for(const imported of [false,true]) {
    const {context,panels,cloudLoads,nodes} = setup({enabled:false,imported,remotes:[],selection:{image_sources:[],concept_source:''}});
    await context.loadCloudConfiguration();
    assert.ok(panels.every(p=>p.classList.contains('hidden')));
    assert.equal(cloudLoads(),0);
    assert.equal(nodes['#configureCloudButton'].textContent,'Enable cloud storage');
  }
});
test('active cloud configuration reveals operations and refreshes their data',async()=>{
  const {context,panels,cloudLoads,nodes} = setup({enabled:true,imported:true,remotes:[{name:'cloud',type:'s3'}],selection:{image_sources:['cloud:images'],concept_source:'cloud:llm'}});
  await context.loadCloudConfiguration();
  assert.ok(panels.every(p=>!p.classList.contains('hidden')));
  assert.equal(cloudLoads(),3);
  assert.equal(nodes['#saveCloudConfiguration'].disabled,false);
  assert.equal(nodes['#configureCloudButton'].textContent,'Manage cloud configuration');
});
test('failed save leaves the previous configuration and restores retry controls',async()=>{
  const {context,nodes} = setup({});
  const old = {enabled:false,revision:'old',selection:{image_sources:['cloud:images'],concept_source:'cloud:llm'}};
  context.renderCloudConfiguration(old);
  context.api = async()=>{throw new Error('connection failed');};
  await context.saveCloudConfiguration();
  assert.equal(context.state.cloudConfiguration,old);
  assert.equal(nodes['#cloudConfigurationMessage'].textContent,'connection failed');
  assert.equal(nodes['#saveCloudConfiguration'].disabled,false);
  assert.equal(context.state.cloudConfigurationBusy,false);
});
test('direct downloads precede configuration and local ZIP controls stay independent',()=>{
  const html = fs.readFileSync('Archon/Portal/static/index.html','utf8');
  assert.ok(html.indexOf('storage-panel direct-download-panel') < html.indexOf('id="cloudConfigurationPanel"'));
  assert.match(html, /<div class="storage-panel" id="localDataPanel">/);
  assert.match(html, /id="backupPanel" data-cloud-storage/);
  assert.ok(!html.includes('CF_TUNNEL_UUID'));
});

test('a late status response cannot hide a newer active configuration', async()=>{
  const {context,panels} = setup({});
  const replies = [];
  context.api = () => new Promise(resolve => replies.push(resolve));
  const older = context.loadCloudConfiguration();
  const newer = context.loadCloudConfiguration();
  replies[1]({enabled:true,imported:true,remotes:[],selection:{image_sources:['cloud:images'],concept_source:'cloud:llm'}});
  await newer;
  replies[0]({enabled:false,imported:false,remotes:[],selection:{image_sources:[],concept_source:''}});
  await older;
  assert.equal(context.state.cloudConfiguration.enabled,true);
  assert.ok(panels.every(p=>!p.classList.contains('hidden')));
});

test('custom image directories can select a model type, persist it and remove stale selections', async()=>{
  const data={enabled:true,imported:true,remotes:[],revision:'r',selection:{image_sources:['cloud:bucket/custom'],concept_source:'cloud:llm',image_source_types:{'cloud:bucket/custom':'lora'}}};
  const {context,nodes}=setup(data);
  context.renderCloudConfiguration(data);
  let row=nodes['#cloudImageSources'].children[0];
  assert.equal(row.children[1].value,'lora');
  row.children[1].value='checkpoint'; row.children[1].listeners.change();
  assert.equal(context.state.cloudConfiguration.selection.image_source_types['cloud:bucket/custom'],'checkpoint');
  let payload;
  context.api=async(path,options)=>{payload=JSON.parse(options.body);return data;};
  nodes['#configureCloudButton'].setAttribute=()=>{};
  await context.saveCloudConfiguration();
  assert.equal(payload.image_source_types['cloud:bucket/custom'],'checkpoint');
  row=nodes['#cloudImageSources'].children[0];
  row.children[1].value=''; row.children[1].listeners.change();
  assert.equal(Object.keys(context.state.cloudConfiguration.selection.image_source_types).length,0);
  row.children[1].value='vae'; row.children[1].listeners.change();
  row.children[2].listeners.click();
  assert.equal(context.state.cloudConfiguration.selection.image_sources.length,0);
  assert.equal(Object.keys(context.state.cloudConfiguration.selection.image_source_types).length,0);
});

test('either Forge directory alone enables saving, while an empty selection remains disabled', () => {
  for (const selection of [{image_sources:['cloud:images'], concept_source:''},
    {image_sources:[], concept_source:'cloud:concept'}, {image_sources:[], concept_source:''}]) {
    const {context,nodes} = setup({});
    context.renderCloudConfiguration({enabled:false, imported:true, remotes:[], selection});
    assert.equal(nodes['#saveCloudConfiguration'].disabled, !selection.image_sources.length && !selection.concept_source);
  }
});
