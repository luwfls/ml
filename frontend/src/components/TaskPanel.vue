<template>
  <section class="task-panel flow-layout">
    <el-card><div class="section-heading"><h2>任务</h2><el-button :disabled="locked" @click="$emit('new')">新建任务</el-button></div><el-button size="small" @click="$emit('refresh')">刷新任务</el-button><div v-for="t in tasks" :key="t.id" class="task-card flow-card" :class="{active:t.id===task.id}" @click="$emit('select',t)"><strong>{{ t.name }}</strong><small>{{ t.id }}</small><small>{{ flowName(t.flow_id) }}</small></div><p v-if="!tasks.length" class="hint">保存任务后可手动选择多台设备执行。</p></el-card>
    <el-card><el-form size="small" label-width="105px" :disabled="locked"><el-form-item label="任务 ID"><el-input :value="task.id" readonly placeholder="保存时自动生成" /></el-form-item><el-form-item label="任务名称"><el-input v-model="task.name" /></el-form-item><el-form-item label="关联流程"><el-select v-model="task.flow_id" filterable placeholder="选择已保存流程"><el-option v-for="f in flows" :key="f.id" :label="f.name+' · '+f.id" :value="f.id" /></el-select></el-form-item></el-form>
      <p class="hint">启动使用已保存的任务和流程；未保存的修改不会执行。每台设备独立产生运行记录。</p>
      <div class="button-row"><el-button type="primary" :disabled="locked||!task.name.trim()||!task.flow_id" @click="$emit('save')">保存任务</el-button><el-button type="success" :disabled="busy||!persisted" @click="$emit('start')">手动启动</el-button><el-button type="danger" :disabled="locked||!persisted" @click="$emit('delete')">删除任务</el-button></div>
      <h3>任务运行记录</h3><p v-if="!taskRuns.length" class="hint">暂无运行记录</p><div v-for="r in taskRuns" :key="r.id" class="result-row"><strong>{{ r.serial }}</strong><span>{{ r.status }} · 批次 {{ r.batch_id || '-' }}</span><el-button size="mini" @click="$emit('run',r.id)">查看运行</el-button></div>
    </el-card>
  </section>
</template>
<script>
export default {props:{tasks:Array,task:Object,flows:Array,runs:Array,locked:Boolean,busy:Boolean},computed:{persisted(){return this.tasks.some(t=>t.id===this.task.id);},taskRuns(){return this.runs.filter(r=>this.task.id&&r.task_id===this.task.id);}},methods:{flowName(id){const flow=this.flows.find(f=>f.id===id);return flow?flow.name||id:id;}}};
</script>
