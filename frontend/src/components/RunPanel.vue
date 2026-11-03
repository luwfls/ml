<template>
  <el-card><div class="section-heading"><h2>运行记录与证据</h2><el-button size="small" @click="$emit('refresh')">刷新运行记录</el-button></div><el-select :value="runId" @change="$emit('select',$event)" placeholder="选择已有运行"><el-option v-for="r in runs" :key="r.id" :value="r.id" :label="(r.flow_name||r.flow_id||r.id)+' · '+r.status+' · '+r.id" /></el-select>
    <template v-if="run"><div class="run-summary"><el-tag>{{ run.status }}</el-tag><span>{{ run.id }}</span><span>设备 {{ run.serial }}</span><span>成功 {{ run.success_count || 0 }} 次</span><span>{{ run.reason || '' }}</span><strong v-if="run.dry_run">只识别，未发送输入</strong></div>
    <div class="button-row"><template v-if="run.mode==='step'"><el-button type="primary" :disabled="!live||run.status!=='waiting'" @click="$emit('control','next')">执行下一步</el-button><el-button :disabled="!live||run.status!=='waiting'" @click="$emit('control','auto')">切换自动执行</el-button></template><el-button :disabled="!live||run.status!=='running'" @click="$emit('control','pause')">暂停</el-button><el-button :disabled="!live||run.status!=='paused'||run.reason!=='user_paused'" @click="$emit('control','resume')">继续</el-button><el-button type="danger" :disabled="!live" @click="$emit('control','cancel')">停止</el-button></div>
    <p v-if="run.status==='waiting'" class="hint">步进运行正在等待；点击「执行下一步」只执行一轮，也可切换自动执行。</p>
    <p v-if="run.status==='pausing'" class="hint">等待当前安全边界确认暂停；确认后不再发送新动作。</p><p v-if="currentHit" class="hint">当前命中：{{ currentHit }}</p>
    <div class="evidence"><img v-if="run.frame_url" :src="run.frame_url" alt="最近运行截图证据" /><div><div v-for="(event,index) in (run.events||[]).slice(-30).reverse()" :key="index" class="event"><span>{{ event.type || event.status || '事件' }}</span><pre>{{ JSON.stringify(event,null,2) }}</pre></div></div></div></template><p v-else class="hint">选择运行记录查看状态、事件和截图；页面刷新后可重新查看。</p>
  </el-card>
</template>
<script>
import {liveStatuses} from '../model.js';
export default {props:{runs:Array,run:Object,runId:String},computed:{live(){return this.run&&(this.run.live===true||(this.run.live===undefined&&liveStatuses.includes(this.run.status)));},currentHit(){const event=[...(this.run?.events||[])].reverse().find(e=>e.state_id||e.state);return event?(event.state_id||event.state):'';}}};
</script>
