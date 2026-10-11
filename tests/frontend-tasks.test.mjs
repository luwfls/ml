import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../frontend/src/App.vue',import.meta.url),'utf8');
const script=source.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/import (\w+) from '[^']+\.vue';/g,'const $1 = {};').replace(/from '\.\/model.js'/g,`from '${new URL('../frontend/src/model.js',import.meta.url)}'`);
const app=(await import('data:text/javascript;base64,'+Buffer.from(script).toString('base64'))).default;
function context() {
  const vm={...app.data(),$message:{success:()=>{}},$confirm:async()=>{}};
  for(const [key,fn] of Object.entries(app.methods))vm[key]=fn.bind(vm);
  for(const [key,fn] of Object.entries(app.computed))Object.defineProperty(vm,key,{get:()=>fn.call(vm)});
  vm.tasks=[{id:'saved-task',name:'Saved',flow_id:'saved-flow'}];vm.task={...vm.tasks[0],name:'Unsaved',flow_id:'different-flow'};
  vm.flows=[{id:'saved-flow',dry_run:true},{id:'different-flow',dry_run:false}];
  vm.startTaskSnapshot=vm.tasks[0];vm.devices=[{serial:'a',status:'device'},{serial:'b',status:'device'}];vm.taskSerials=['a','a','b'];
  return vm;
}
async function withFetch(fn,run){const old=globalThis.fetch;globalThis.fetch=async(path,options)=>({ok:true,json:async()=>fn(path,options?.body?JSON.parse(options.body):null)});try{await run();}finally{globalThis.fetch=old;}}
test('task start sends saved ID and unique devices; partial errors retain independent runs',async()=>{
  const requests=[];await withFetch((path,body)=>{requests.push({path,body});if(path==='/api/tasks/start')return {batch_id:'batch',task_id:'saved-task',results:[{serial:'a',id:'run-a'},{serial:'b',error:'busy'}]};if(path==='/api/runs')return [{id:'run-a',task_id:'saved-task'}];return [];},async()=>{
    const vm=context();await vm.startTask();assert.deepEqual(requests.find(r=>r.path==='/api/tasks/start').body,{id:'saved-task',serials:['a','b']});assert.equal(vm.taskResults[1].error,'busy');assert.equal(vm.runs[0].id,'run-a');
  });
});
test('active device disables itself but does not block starting a free device',async()=>{
  await withFetch(path=>path==='/api/tasks/start'?{results:[{serial:'b',id:'run-b'}]}:[],async()=>{
    const vm=context();vm.runs=[{id:'run-a',serial:'a',live:true,status:'running'}];vm.taskSerials=['b'];assert.equal(vm.locked,true);assert.equal(vm.taskDeviceDisabled(vm.devices[0]),true);assert.equal(vm.taskDeviceDisabled(vm.devices[1]),false);await vm.startTask();assert.equal(vm.taskResults[0].id,'run-b');
  });
});
test('duplicate task start is guarded before awaiting confirmation and uses captured task',async()=>{
  let confirm;const requests=[];await withFetch((path,body)=>{requests.push({path,body});return path==='/api/tasks/start'?{results:[]}:[];},async()=>{
    const vm=context();vm.flows[0].dry_run=false;vm.$confirm=()=>new Promise(r=>confirm=r);const pending=vm.startTask();vm.task={id:'other'};vm.startTaskSnapshot={id:'other',flow_id:'different-flow'};await vm.startTask();assert.equal(requests.length,0);confirm();await pending;assert.equal(requests.filter(r=>r.path==='/api/tasks/start').length,1);assert.equal(requests[0].body.id,'saved-task');assert.equal(vm.taskStarting,false);
  });
});
test('device refresh removes offline or newly occupied selections',async()=>{
  await withFetch(path=>path==='/api/devices'?[{serial:'a',status:'offline'},{serial:'b',status:'device'}]:[{id:'run-b',serial:'b',live:true}],async()=>{
    const vm=context();await vm.refreshTaskDevices();assert.deepEqual(vm.taskSerials,[]);
  });
});
test('pending task save does not overwrite a newly selected task',async()=>{
  let resolve;const old=globalThis.fetch;globalThis.fetch=()=>new Promise(r=>resolve=r);
  try{const vm=context();vm.reloadCatalog=async()=>{};const pending=vm.saveCurrentTask();const other={id:'other',name:'Other',flow_id:'saved-flow'};vm.task=other;resolve({ok:true,json:async()=>({id:'saved-task',name:'Saved edit',flow_id:'different-flow'})});await pending;assert.equal(vm.task,other);assert.equal(vm.busy,false);}finally{globalThis.fetch=old;}
});
test('task page polling refreshes runs even when no previously known run is live',async()=>{
  const requests=[];await withFetch(path=>{requests.push(path);return [];},async()=>{const vm=context();vm.page='tasks';await vm.poll();assert.ok(requests.includes('/api/runs'));});
});
test('cached dry-run flow still requires input confirmation before task start',async()=>{
  const events=[];await withFetch(path=>{if(path==='/api/tasks/start'){events.push('post');return {results:[]};}return [];},async()=>{
    const vm=context();vm.$confirm=async message=>{events.push('confirm');assert.match(message,/以启动时配置为准/);};
    await vm.startTask();assert.deepEqual(events,['confirm','post']);
  });
});
