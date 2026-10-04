const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.dataset={}; this.textContent=''; this.open=false; this.listeners={}; }
  appendChild(child) { this.children.push(child); child.parent=this; return child; }
  append(...children) { children.forEach(child=>this.appendChild(child)); }
  addEventListener(name, fn) { this.listeners[name]=fn; }
  remove() { this.parent.children=this.parent.children.filter(child=>child!==this); }
  get childElementCount() { return this.children.length; }
}
function all(node) { return [node,...node.children.flatMap(all)]; }
function text(node, includeDetails=true) {
  if (!includeDetails && node.tag==='details') return '';
  return [node.textContent,...node.children.map(child=>text(child,includeDetails))].join('\n');
}
function setup(machine) {
  const list=new Element('div'), calls=[];
  const t=(key,args={})=>key.replace(/\{(\w+)\}/g,(_,name)=>args[name]?.i18nKey || args[name]);
  const context={document:{createElement:tag=>new Element(tag)},window:{confirm:()=>true},t,
    uiText(node,key,args){node.textContent=t(key,args);},state:{podJobs:{},destroyedPods:new Set()},
    elements:{vastInstanceList:list},showNotice(){},machineMessage(){},
    api:async(path,options)=>{calls.push([path,JSON.parse(options.body)]);return {job:{status:'completed'}};},
    loadMachines:async()=>{},loadVastBalance:async()=>{},
    runPodAction:async(...args)=>{calls.push(['concept',...args]);},
    deployImageForge:async(...args)=>{calls.push(['image',...args]);},
    forgeNodes:{render(){const selection=new Element('div');selection.textContent='Forge bindings';return selection;}}};
  vm.createContext(context);
  for(const file of ['node-card.js','deployment-progress.js']) vm.runInContext(fs.readFileSync(`Archon/Portal/static/${file}`,'utf8'),context);
  const app=fs.readFileSync('Archon/Portal/static/app.js','utf8');
  vm.runInContext(app.slice(app.indexOf('function renderMachine(machine)'),app.indexOf('const nodeConnection =')),context);
  context.renderMachine(machine);
  return {card:list.children[0],calls};
}
const fixture={id:42,label:'My Pod',actual_status:'running',gpu_name:'RTX 3090',num_gpus:1,geolocation:'JP',dph_total:0.25,
  ssh_host:'ssh.example',ssh_port:1234,forge:{status:'ready',revision:'concept-revision'},image_forge:{status:'ready',revision:'image-revision'},
  audio_forge:{status:'ready'},node:{status:'online',node_id:'internal-node',runtime_id:'internal-runtime',hostname:'internal-host',
    system:{os:'Linux',architecture:'x86_64'},last_seen:'2026-10-04T00:00:00Z',stage:'internal-stage',
    resources:{capacity:{cpu:8,memory:8*1024**3,disk:100*1024**3,gpu:{G1:{vram:24*1024**3}}},
      allocatable:{cpu:4,memory:4*1024**3,disk:50*1024**3,gpu:{G1:{vram:12*1024**3}}}},
    bandwidth:{status:'completed',download_mb_s:60,region:'AS',server_region:'AS',country:'JP',server_name:'test-server',finished_at:'2026-10-04T01:00:00Z'}}};

test('machine card keeps operational information visible and diagnostic fields in one collapsed Details region',()=>{
  const {card}=setup(fixture);
  const details=all(card).filter(node=>node.tag==='details');
  assert.equal(details.length,1);assert.equal(details[0].open,false);
  const primary=text(card,false),full=text(details[0]);
  for(const value of ['My Pod','Vast #42','RTX 3090','JP','$0.250','Node Agent: Online','24.0 GiB','12.0 GiB','Concept Forge','Image Forge','Audio Forge','qualified','Forge bindings']) assert.ok(primary.includes(value),value);
  for(const value of ['internal-node','internal-runtime','internal-host','Linux / x86_64','Last heartbeat','test-server','Node test region','Node egress country','Test time','internal-stage','ssh.example:1234','concept-revision','image-revision']) {
    assert.ok(full.includes(value),value);assert.ok(!primary.includes(value),value);
  }
});
test('only deployment, retest and destruction buttons are exposed; debug entries never enter the DOM',()=>{
  for(const status of ['online','joining','offline','unhealthy']) {
    const {card}=setup({...fixture,node:{...fixture.node,status}});
    const buttons=all(card).filter(node=>node.tag==='button').map(node=>node.textContent);
    for(const label of ['Verify Concept Forge','Verify Image Forge','验证 Audio Forge','Update source','Test discussion','View startup diagnostics']) assert.ok(!buttons.includes(label),label);
    assert.ok(buttons.includes('Destroy Pod'));
    if(status==='online') for(const label of ['Deploy Concept Forge','Deploy Image Forge','部署 Audio Forge','Retest download speed']) assert.ok(buttons.includes(label),label);
  }
});
test('formal action listeners still dispatch original deploy, retest and destroy requests',async()=>{
  const {card,calls}=setup(fixture);
  const click=label=>all(card).find(node=>node.tag==='button' && node.textContent===label).listeners.click();
  click('Deploy Concept Forge');click('Deploy Image Forge');
  await click('部署 Audio Forge');await click('Retest download speed');await click('Destroy Pod');
  assert.ok(calls.some(call=>call[0]==='concept' && call[1]===42 && call[2]==='deploy'));
  assert.ok(calls.some(call=>call[0]==='image' && call[1]===42));
  assert.ok(calls.some(call=>call[0]==='/api/machines/vast/deploy-audio' && call[1].instance_id===42));
  assert.ok(calls.some(call=>call[0]==='/api/nodes/bandwidth' && call[1].node_id==='internal-node'));
  assert.ok(calls.some(call=>call[0]==='/api/machines/vast/destroy' && call[1].instance_id===42));
});
test('offline cards retain all Forge statuses; failures have a short summary and full detail',()=>{
  const longError='failure '.repeat(80)+'\ntraceback-internal';
  const {card}=setup({...fixture,actual_status:'stopped',node:{...fixture.node,status:'offline'},
    audio_forge:{status:'deployment_failed',detail:longError}});
  const primary=text(card,false),details=all(card).find(node=>node.tag==='details');
  for(const name of ['Concept Forge','Image Forge','Audio Forge']) assert.ok(primary.includes(name));
  assert.ok(primary.includes('…'));assert.ok(!primary.includes('traceback-internal'));
  assert.ok(text(details).includes('traceback-internal'));
});
test('active deployment keeps progress visible and disables duplicate deployment actions',()=>{
  const job={status:'running',stage:'installing_runtime'};
  const {card}=setup({...fixture,forge:{status:'deploying',job},image_forge:{status:'deploying',job},audio_forge:{status:'deploying',job}});
  assert.ok(text(card,false).includes('Installing runtime and dependencies'));
  const progress=all(card).find(node=>node.dataset.podProgress==='42');
  assert.ok(progress);
  for(const label of ['Deploy Concept Forge','Deploy Image Forge','部署 Audio Forge']) {
    const button=all(card).find(node=>node.tag==='button' && node.textContent===label);
    assert.equal(button.disabled,true,label);
  }
});
test('four machine groups contain the corresponding information and keep Details separate',()=>{
  const {card}=setup({...fixture,forge:{...fixture.forge,detail:'concept-error',job:{status:'running',stage:'installing_runtime'}}});
  const groups=card.children.filter(node=>node.dataset.machineSection);
  assert.deepEqual(groups.map(node=>node.dataset.machineSection),['overview','resources','forge','operations']);
  const [overview,resources,forge,operations]=groups;
  for(const value of ['My Pod','Vast #42','running','RTX 3090','JP','$0.250']) assert.ok(text(overview).includes(value),value);
  for(const value of ['Node Agent: Online','CPU','Memory','Disk','24.0 GiB','qualified','Retest download speed']) assert.ok(text(resources).includes(value),value);
  for(const value of ['Concept Forge','Image Forge','Audio Forge','Forge bindings','concept-error','Installing runtime and dependencies','Deploy Concept Forge','Deploy Image Forge','部署 Audio Forge']) assert.ok(text(forge).includes(value),value);
  assert.deepEqual(all(operations).filter(node=>node.tag==='button').map(node=>node.textContent),['Destroy Pod']);
  assert.ok(!text(overview).includes('Deploy Concept Forge'));
  assert.ok(!text(resources).includes('Forge bindings'));
  assert.ok(!text(forge).includes('Retest download speed'));
  const details=card.children.find(node=>node.tag==='details');
  assert.ok(details);assert.equal(details.open,false);
  assert.ok(text(details).includes('internal-node'));
  assert.ok(!groups.some(group=>all(group).includes(details)));
});
test('danger styling and status badges retain the underlying machine and Forge states',()=>{
  const {card}=setup({...fixture,forge:{status:'deployment_failed'},image_forge:{status:'deploying'},audio_forge:{status:'not_deployed'}});
  const nodes=all(card);
  const destroy=nodes.find(node=>node.tag==='button' && node.textContent==='Destroy Pod');
  assert.ok(destroy.className.split(' ').includes('danger-button'));
  const badges=nodes.filter(node=>node.className?.split(' ').includes('status-badge'));
  assert.deepEqual(badges.map(node=>node.dataset.status).sort(),['running','online','deployment_failed','deploying','not_deployed'].sort());
  assert.equal(nodes.find(node=>node.tag==='details').open,false);
});
