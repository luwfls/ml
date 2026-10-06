export const clone = value => JSON.parse(JSON.stringify(value));
export function editState(state = {}) {
  const original = clone(state), r = state.recognition || {};
  return {...clone(state), original, id:state.id || '', name:state.name || '', group:state.group || '', role:state.role || 'normal', priority:state.priority || 0,
    kind:r.type || 'image', asset:r.asset || '', texts:(r.texts || []).join('\n'), mode:r.mode || 'exact', threshold:r.threshold ?? .85,
    min_confidence:r.min_confidence ?? .8, similarity_threshold:r.similarity_threshold ?? .85, region:clone(r.region || [0,0,1,1]),
    actions:clone(state.actions || []), conditions:{...clone(state.conditions || {}),required_states:clone(state.conditions?.required_states || []),excluded_states:clone(state.conditions?.excluded_states || [])}};
}
export function saveState(editor) {
  const old = editor.original || {}, previous = old.recognition?.type === editor.kind ? clone(old.recognition) : {};
  const recognition = {...previous,type:editor.kind,region:clone(editor.region)};
  if(editor.kind === 'image') {delete recognition.texts; Object.assign(recognition,{asset:editor.asset,threshold:editor.threshold});}
  else {delete recognition.asset; Object.assign(recognition,{texts:editor.texts.split('\n').map(s=>s.trim()).filter(Boolean),mode:editor.mode,min_confidence:editor.min_confidence,similarity_threshold:editor.similarity_threshold});}
  return {...clone(old),id:editor.id,name:editor.name,group:editor.group,role:editor.role,priority:editor.priority,recognition,actions:clone(editor.actions),conditions:clone(editor.conditions)};
}
export function pixelPoint(x,y,bounds,size) {return [x-bounds.left,y-bounds.top].map((value,i)=>Math.max(0,Math.min(size[i],Math.round(value*size[i]/[bounds.width,bounds.height][i]))));}
export function rectangle(a,b) {return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];}
export function normalizedRegion(box,size) {return box.map((v,i)=>v/size[i%2]);}
export function relativeTarget(box,click) {
  const width=box[2]-box[0],height=box[3]-box[1];
  if(width<=0||height<=0||click[2]<=click[0]||click[3]<=click[1]) throw new Error('识别区与点击区不能为空');
  const target=click.map((v,i)=>(v-box[i%2])/[width,height][i%2]);
  if(target.some(v=>!Number.isFinite(v)||Math.abs(v)>100)) throw new Error('点击区距离识别区过远');
  return target;
}
export async function api(path,body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok) throw new Error(data.error||'请求失败'); return data;
}
export const liveStatuses=['running','pausing','paused','cancelling'];
export function conditionLabel(match) {
  return match.eligible === true ? '条件通过' : match.eligible === false ? '条件未满足' : '条件未检查（可用分组预览）';
}
