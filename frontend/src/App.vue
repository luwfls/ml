<template>
  <el-container class="app-shell">
    <el-aside class="sidebar">
      <div class="brand">
        <h1 class="brand-title">MJ<span> Vue Workbench</span></h1>
        <p class="brand-subtitle">独立前端 · Vite 热加载 · Element UI</p>
      </div>
      <el-menu :default-active="activePage" @select="selectPage">
        <el-menu-item index="dashboard"><i class="el-icon-data-board"></i><span slot="title">总览</span></el-menu-item>
        <el-menu-item index="templates"><i class="el-icon-crop"></i><span slot="title">模板 / 截图</span></el-menu-item>
        <el-menu-item index="flows"><i class="el-icon-connection"></i><span slot="title">状态流程</span></el-menu-item>
        <el-menu-item index="scheduler"><i class="el-icon-time"></i><span slot="title">流程调度</span></el-menu-item>
        <el-menu-item index="window"><i class="el-icon-monitor"></i><span slot="title">窗口工具</span></el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h2 class="page-title">{{ pageTitle }}</h2>
          <p class="page-subtitle">{{ statusText }}</p>
        </div>
        <div class="topbar-actions">
          <el-tag size="small" :type="apiAvailable ? 'success' : 'danger'">API {{ apiAvailable ? '已连接' : '不可用' }}</el-tag>
          <el-tag size="small" type="info">{{ windowSizeText }}</el-tag>
          <el-button size="small" icon="el-icon-refresh" :loading="bootstrapping" @click="bootstrap">刷新数据</el-button>
        </div>
      </el-header>

      <el-main class="main">
        <section v-if="activePage === 'dashboard'">
          <div class="metric-grid">
            <div class="metric-card"><div class="metric-value">{{ templates.length }}</div><div class="metric-label">Templates</div></div>
            <div class="metric-card"><div class="metric-value">{{ templateGroups.length }}</div><div class="metric-label">Groups</div></div>
            <div class="metric-card"><div class="metric-value">{{ flows.length }}</div><div class="metric-label">Template Loops</div></div>
            <div class="metric-card"><div class="metric-value">{{ flows.length }}</div><div class="metric-label">State Flows</div></div>
          </div>
          <div class="content-grid">
            <el-card class="section-card" shadow="never">
              <div slot="header" class="card-title"><h2>独立前端脚手架</h2><el-tag size="small">Vue 2 + Element UI</el-tag></div>
              <el-timeline>
                <el-timeline-item timestamp="启动后端" type="primary">先运行 Python workbench API：<code>tools/window_workbench.py --api-only --port 8765</code></el-timeline-item>
                <el-timeline-item timestamp="启动前端">再运行 <code>corepack yarn dev</code>，Vite 会热加载并代理 <code>/api</code> 到后端。</el-timeline-item>
                <el-timeline-item timestamp="后续迁移">将旧页面的大块原生 DOM 逻辑逐步拆成 Vue 组件。</el-timeline-item>
              </el-timeline>
            </el-card>
            <el-card class="section-card" shadow="never">
              <div slot="header" class="card-title"><h3>启动状态</h3></div>
              <el-descriptions :column="1" size="small" border>
                <el-descriptions-item label="窗口">{{ windowInfo ? windowInfo.title : startupError || '未准备' }}</el-descriptions-item>
                <el-descriptions-item label="模板能力"><el-tag size="mini" :type="capabilities.template ? 'success' : 'info'">{{ capabilities.template ? '可用' : '不可用' }}</el-tag></el-descriptions-item>
                <el-descriptions-item label="截图能力"><el-tag size="mini" :type="capabilities.capture ? 'success' : 'info'">{{ capabilities.capture ? '可用' : '不可用' }}</el-tag></el-descriptions-item>
                <el-descriptions-item label="流程能力"><el-tag size="mini" :type="capabilities.workflow ? 'success' : 'info'">{{ capabilities.workflow ? '可用' : '不可用' }}</el-tag></el-descriptions-item>
              </el-descriptions>
            </el-card>
          </div>
        </section>

        <section v-else-if="activePage === 'templates'" class="template-blank-page">
          <el-card shadow="never" class="template-group-section-card">
            <div slot="header" class="template-card-header">
              <strong>模板分组</strong>
              <el-tag size="small">{{ selectableTemplateGroups.length }}</el-tag>
              <div class="template-group-toolbar">
                <el-button type="primary" size="mini" icon="el-icon-plus" @click="createTemplateGroup">新建分组</el-button>
                <el-button size="mini" icon="el-icon-document-copy" :disabled="!canEditSelectedTemplateGroup" @click="copyTemplateGroup">复制</el-button>
                <el-button size="mini" icon="el-icon-edit" :disabled="!canEditSelectedTemplateGroup" @click="renameTemplateGroup">重命名</el-button>
                <el-button v-if="isSelectedUnrecognizedGroup" size="mini" icon="el-icon-back" @click="returnToParentTemplateGroup">返回上层</el-button>
                <el-button v-if="isSelectedUnrecognizedGroup" size="mini" type="warning" plain icon="el-icon-delete" @click="clearUnrecognizedTemplates">清空未识别</el-button>
                <el-button size="mini" type="warning" plain icon="el-icon-delete" :disabled="!hasUnrecognizedTemplates" @click="clearAllUnrecognizedTemplates">清空全部未识别</el-button>
                <el-button size="mini" type="danger" plain icon="el-icon-delete" :disabled="!canEditSelectedTemplateGroup" @click="deleteTemplateGroup">删除分组</el-button>
              </div>
            </div>
            <div class="flow-card-grid">
              <div
                class="flow-card"
                :class="{ active: selectedGroup === '__all__' }"
                @click="selectedGroup = '__all__'; selectedTemplate = null"
              >
                <div class="flow-card-header">
                  <span class="flow-card-name">全部</span>
                  <el-tag size="mini" type="info">{{ templates.filter(t => !isUnrecognizedTemplate(t)).length }}</el-tag>
                </div>
              </div>
              <div
                class="flow-card"
                :class="{ active: selectedGroup === '' }"
                @click="selectedGroup = ''; selectedTemplate = null"
              >
                <div class="flow-card-header">
                  <span class="flow-card-name">未分组</span>
                  <el-tag size="mini" type="info">{{ templates.filter(t => (t.group || '') === '' && !isUnrecognizedTemplate(t)).length }}</el-tag>
                </div>
              </div>
              <div
                v-if="hasUnrecognizedTemplates"
                class="flow-card"
                :class="{ active: selectedGroup === '__unrecognized__' }"
                @click="selectedGroup = '__unrecognized__'; selectedTemplate = null"
              >
                <div class="flow-card-header">
                  <span class="flow-card-name">未识别</span>
                  <el-tag size="mini" type="warning">{{ unrecognizedTemplateCount }}</el-tag>
                </div>
              </div>
              <div
                v-for="group in selectableTemplateGroups"
                :key="group.name"
                class="flow-card"
                :class="{ active: selectedGroup === group.name }"
                @click="selectedGroup = group.name; selectedTemplate = null"
              >
                <div class="flow-card-header">
                  <span class="flow-card-name">{{ group.name }}</span>
                  <el-tag size="mini" type="info">{{ group.count || 0 }}</el-tag>
                </div>
              </div>
            </div>
          </el-card>

          <template v-if="selectedGroup === '__all__'">
            <el-card
              v-for="section in groupedTemplates"
              :key="section.group"
              class="template-group-template-card"
              shadow="never"
            >
              <div slot="header" class="template-card-header">
                <strong>{{ section.group || '未分组' }}</strong>
                <el-tag size="small">{{ section.items.length }}</el-tag>
              </div>
              <div class="template-card-grid">
                <button
                  v-for="template in section.items"
                  :key="template.relative_path || template.path"
                  type="button"
                  class="template-card-item"
                  :class="{ active: selectedTemplate && (selectedTemplate.relative_path || selectedTemplate.path) === (template.relative_path || template.path) }"
                  @click="openTemplateCard(template)"
                >
                  <span class="template-card-thumb-wrap">
                    <img class="template-card-thumb" :src="templatePreviewUrl(template.relative_path || template.path)" :alt="templateName(template)" loading="lazy" decoding="async">
                  </span>
                  <span class="template-card-name">{{ templateName(template) }}</span>
                  <span v-if="templateIsEnd(template) || templateIsSuccess(template) || templateIsNonStandalone(template) || templateIsFallback(template) || templateAvoidSamePosition(template)" class="template-flag-row">
                    <el-tag v-if="templateIsEnd(template)" size="mini" type="warning">结束</el-tag>
                    <el-tag v-if="templateIsSuccess(template)" size="mini" type="success">成功</el-tag>
                    <el-tag v-if="templateIsNonStandalone(template)" size="mini" type="info">非单独</el-tag>
                    <el-tag v-if="templateIsFallback(template)" size="mini" type="danger">兜底</el-tag>
                    <el-tag v-if="templateAvoidSamePosition(template)" size="mini" type="primary">避同位</el-tag>
                  </span>
                  <span class="template-card-meta">优先级 {{ templatePriority(template) }} · {{ template.width || '?' }}×{{ template.height || '?' }}</span>
                </button>
              </div>
            </el-card>
            <el-empty v-if="!groupedTemplates.length" description="没有模板"></el-empty>
          </template>
          <el-card v-else class="template-group-template-card" shadow="never">
            <div slot="header" class="template-card-header">
              <strong>当前分组模板</strong>
              <el-tag size="small">{{ filteredTemplates.length }}</el-tag>
            </div>
            <div v-if="visibleChildTemplateGroups.length" class="template-folder-grid">
              <button
                v-for="group in visibleChildTemplateGroups"
                :key="group.name"
                type="button"
                class="template-folder-button"
                @click="enterTemplateGroup(group.name)"
              >
                <i class="el-icon-folder"></i>
                <span>{{ childTemplateGroupLabel(group) }}</span>
                <el-tag size="mini">{{ group.count || 0 }}</el-tag>
              </button>
            </div>
            <div v-if="filteredTemplates.length" class="template-card-grid">
              <button
                v-for="template in filteredTemplates"
                :key="template.relative_path || template.path"
                type="button"
                class="template-card-item"
                :class="{ active: selectedTemplate && (selectedTemplate.relative_path || selectedTemplate.path) === (template.relative_path || template.path) }"
                @click="openTemplateCard(template)"
              >
                <span class="template-card-thumb-wrap">
                  <img class="template-card-thumb" :src="templatePreviewUrl(template.relative_path || template.path)" :alt="templateName(template)" loading="lazy" decoding="async">
                </span>
                <span class="template-card-name">{{ templateName(template) }}</span>
                <span v-if="templateIsEnd(template) || templateIsSuccess(template) || templateIsNonStandalone(template) || templateIsFallback(template) || templateAvoidSamePosition(template)" class="template-flag-row">
                  <el-tag v-if="templateIsEnd(template)" size="mini" type="warning">结束</el-tag>
                  <el-tag v-if="templateIsSuccess(template)" size="mini" type="success">成功</el-tag>
                  <el-tag v-if="templateIsNonStandalone(template)" size="mini" type="info">非单独</el-tag>
                  <el-tag v-if="templateIsFallback(template)" size="mini" type="danger">兜底</el-tag>
                  <el-tag v-if="templateAvoidSamePosition(template)" size="mini" type="primary">避同位</el-tag>
                </span>
                <span class="template-card-meta">优先级 {{ templatePriority(template) }} · {{ template.width || '?' }}×{{ template.height || '?' }}</span>
              </button>
            </div>
            <el-empty v-else-if="!visibleChildTemplateGroups.length" description="当前分组下没有模板"></el-empty>
          </el-card>

          <el-card class="capture-workbench-card" shadow="never">
            <div slot="header" class="template-card-header">
              <strong>当前游戏窗口截图</strong>
              <el-tag size="small" type="info">F1 截图 · F2 识别区 · F3 点击区 · F4 保存模板 · F5 识别执行 · F6 分组识别执行</el-tag>
            </div>
            <div class="capture-hotkey-status">{{ screenshotHotkeyStatus }}</div>
            <div class="capture-canvas-stage">
              <div v-if="capturePreviewUrlValue" ref="capturePreviewWrap" class="capture-preview-wrap">
                <img
                  ref="capturePreviewImage"
                  class="capture-canvas-image"
                  :src="capturePreviewUrlValue"
                  alt="当前游戏窗口截图"
                  @load="updateCaptureOverlay"
                  @mousedown="beginCaptureSelection"
                >
                <div v-if="captureRegion" class="capture-selection-box" :style="regionBoxStyle(captureRegion)"></div>
                <div
                  v-for="(region, index) in clickCaptureRegions"
                  :key="`click-${index}`"
                  class="click-selection-box"
                  :style="regionBoxStyle(region)"
                >
                  <span class="region-index">{{ index + 1 }}</span>
                </div>
                <div v-if="clickCaptureRegion" class="click-selection-box active" :style="regionBoxStyle(clickCaptureRegion)"></div>
              </div>
              <el-empty v-else description="按 F1 截取当前游戏窗口"></el-empty>
            </div>
          </el-card>

          <el-card v-if="groupActionMatches.length" class="template-group-template-card" shadow="never">
            <div slot="header" class="template-card-header">
              <strong>F6 命中结果</strong>
              <el-tag size="small">{{ groupActionMatches.length }}</el-tag>
            </div>
            <div class="group-action-results">
              <div
                v-for="match in groupActionMatches"
                :key="match.template.relative_path || match.template_path"
                class="group-action-result"
                :class="{ selected: selectedGroupActionMatch && (selectedGroupActionMatch.template.relative_path || selectedGroupActionMatch.template_path) === (match.template.relative_path || match.template_path) }"
              >
                <img :src="templatePreviewUrl(match.template.relative_path || match.template_path)" :alt="templateName(match.template)" loading="lazy" decoding="async">
                <div class="group-action-result-main">
                  <strong>{{ templateName(match.template) }}</strong>
                  <span>优先级 {{ match.priority || 0 }} · score {{ Number(match.score || 0).toFixed(4) }}</span>
                </div>
              </div>
            </div>
          </el-card>
        </section>

        <section v-else-if="activePage === 'flows'" class="flow-page">
          <div class="toolbar-row">
            <el-button type="primary" size="small" icon="el-icon-plus" @click="newFlowDraft">新建配置</el-button>
            <el-button size="small" icon="el-icon-refresh" @click="refreshFlows">刷新</el-button>
            <el-checkbox v-model="flowDryRun">dry run</el-checkbox>
            <el-checkbox v-model="flowPreferLoopFirst">优先执行 loop</el-checkbox>
          </div>
          <div class="flow-layout">
            <el-card shadow="never" class="section-card flow-grid-card">
              <div slot="header" class="card-title"><h3>状态流程</h3><el-tag size="mini">{{ filteredFlows.length }} / {{ flows.length }}</el-tag>
                <el-input v-model="flowFilter" size="small" clearable prefix-icon="el-icon-search" placeholder="筛选流程" class="flow-filter-inline"></el-input>
              </div>
              <div class="flow-card-grid">
                <div v-for="flow in filteredFlows" :key="flow.filename" class="flow-card" :class="{ active: selectedFlowFilename === flow.filename, running: flow.running }" @click="selectFlow(flow.filename)">
                  <div class="flow-card-header">
                    <span class="flow-card-name">{{ flowDisplayName(flow.filename) }}</span>
                    <el-tag size="mini" :type="flow.running ? (flow.paused ? 'warning' : 'success') : 'info'">{{ flow.running ? (flow.paused ? '已暂停' : '运行中') : '停止' }}</el-tag>
                  </div>
                  <div class="flow-card-meta">{{ (flow.loop_dirs || flow.loopDir || []).join(', ') || '未设置循环目录' }}</div>
                  <div class="flow-card-actions" @click.stop>
                    <el-button v-if="!flow.running" type="success" size="mini" plain @click="selectAndStartFlow(flow.filename)">启动</el-button>
                    <template v-else>
                      <el-button v-if="!flow.paused" type="warning" size="mini" plain @click="selectAndPauseFlow(flow.filename)">暂停</el-button>
                      <el-button v-else type="success" size="mini" plain @click="selectAndResumeFlow(flow.filename)">继续</el-button>
                      <el-button type="danger" size="mini" plain @click="selectAndStopFlow(flow.filename)">停止</el-button>
                    </template>
                  </div>
                </div>
                <el-empty v-if="!flows.length" description="没有状态流程"></el-empty>
                <el-empty v-else-if="!filteredFlows.length" description="没有匹配的状态流程"></el-empty>
              </div>
            </el-card>

            <el-card v-if="selectedFlowFilename || isNewFlowDraft" shadow="never" class="section-card">
              <div slot="header" class="card-title"><h3>流程表单</h3><span class="hint">保存到 state_scripts/*.yaml</span></div>
              <el-form label-position="top" size="small">
                <el-form-item label="文件名">
                  <el-input v-model="flowDraft.filename" placeholder="如 world_boss"></el-input>
                  <div class="hint">保存时自动添加 .yaml 后缀。</div>
                </el-form-item>
                <el-form-item label="入口状态流程">
                  <el-select v-model="flowDraft.start" multiple filterable class="full-width" placeholder="可选">
                    <el-option v-for="flow in flowOptionsForDraft" :key="flow.filename" :label="flowLabel(flow)" :value="flow.id || flowDisplayName(flow.filename)"></el-option>
                  </el-select>
                </el-form-item>
                <el-form-item label="循环模板目录">
                  <el-select v-model="flowDraft.loopDir" multiple filterable class="full-width" placeholder="选择模板分组">
                    <el-option v-for="group in templateGroups" :key="group.name" :label="group.name || '未分组 / root'" :value="group.name"></el-option>
                  </el-select>
                </el-form-item>
                <el-form-item label="参考模板">
                  <div class="flow-template-preview-header">
                    <span class="hint">展示选中的循环模板目录下的模板，排序与模板页一致。结束 {{ flowEndTemplateCount }} / 成功 {{ flowSuccessTemplateCount }} / 兜底 {{ flowFallbackTemplateCount }}</span>
                    <el-tag size="mini">{{ flowLoopTemplates.length }}</el-tag>
                  </div>
                  <div v-if="flowLoopTemplates.length" class="flow-template-preview-grid">
                    <button
                      v-for="template in flowLoopTemplates"
                      :key="template.relative_path || template.path"
                      type="button"
                      class="flow-template-preview-card"
                      :class="{ active: selectedTemplate && (selectedTemplate.relative_path || selectedTemplate.path) === (template.relative_path || template.path) }"
                      :title="template.relative_path || template.path"
                      @click="openTemplateCard(template)"
                    >
                      <span class="flow-template-preview-thumb-wrap">
                        <img class="flow-template-preview-thumb" :src="templatePreviewUrl(template.relative_path || template.path)" :alt="templateName(template)" loading="lazy" decoding="async">
                      </span>
                      <span class="flow-template-preview-name">{{ templateName(template) }}</span>
                      <span v-if="templateIsEnd(template) || templateIsSuccess(template) || templateIsNonStandalone(template) || templateIsFallback(template) || templateAvoidSamePosition(template)" class="template-flag-row">
                        <el-tag v-if="templateIsEnd(template)" size="mini" type="warning">结束</el-tag>
                        <el-tag v-if="templateIsSuccess(template)" size="mini" type="success">成功</el-tag>
                        <el-tag v-if="templateIsNonStandalone(template)" size="mini" type="info">非单独</el-tag>
                        <el-tag v-if="templateIsFallback(template)" size="mini" type="danger">兜底</el-tag>
                        <el-tag v-if="templateAvoidSamePosition(template)" size="mini" type="primary">避同位</el-tag>
                      </span>
                      <span class="flow-template-preview-meta">{{ template.group || '未分组 / root' }} · 优先级 {{ templatePriority(template) }} · {{ template.width || '?' }}×{{ template.height || '?' }}</span>
                    </button>
                  </div>
                  <el-empty v-else :description="flowLoopTemplateEmptyText"></el-empty>
                </el-form-item>
                <el-form-item label="完成次数">
                  <el-input-number v-model="flowDraft.completionCount" :min="1" :step="1"></el-input-number>
                  <div class="hint">成功标识模板累计命中达到该次数时，流程按成功完成。</div>
                </el-form-item>
                <div class="toolbar-row">
                  <el-button type="primary" :loading="flowSaving" @click="saveFlow">保存</el-button>
                  <el-button type="success" :loading="flowStarting" @click="startFlow">保存并启动</el-button>
                  <el-button v-if="selectedFlowRunning && !selectedFlowPaused" type="warning" plain @click="pauseFlow">暂停</el-button>
                  <el-button v-if="selectedFlowRunning && selectedFlowPaused" type="success" plain @click="resumeFlow">继续</el-button>
                  <el-button type="danger" plain @click="stopFlow">强杀停止</el-button>
                  <el-button type="danger" plain :loading="flowDeleting" @click="deleteFlow">删除</el-button>
                </div>
              </el-form>
            </el-card>

            <el-card v-if="selectedFlowFilename" shadow="never" class="section-card flow-detail-yaml">
              <div slot="header" class="card-title"><h3>YAML 预览</h3></div>
              <pre class="yaml-preview mono">{{ flowYamlPreview }}</pre>
            </el-card>
          </div>
        </section>

        <section v-else-if="activePage === 'scheduler'" class="scheduler-page">
          <div class="scheduler-command">
            <div>
              <p class="scheduler-kicker">FLOW SCHEDULER</p>
              <h2 class="scheduler-title">顺序执行状态流程</h2>
            </div>
            <div class="scheduler-stats">
              <div><strong>{{ scheduleItems.length }}</strong><span>队列流程</span></div>
              <div><strong>{{ schedulerTotalRuns }}</strong><span>计划次数</span></div>
              <div><strong>{{ schedulerFinishedRuns }}</strong><span>已处理</span></div>
              <div><strong>{{ schedulerSuccessRuns }}</strong><span>正常结束</span></div>
            </div>
            <div class="scheduler-actions">
              <el-button type="primary" icon="el-icon-video-play" :disabled="!schedulerCanStart" @click="startScheduler({ scheduled: false })">手动启动</el-button>
              <el-button type="success" icon="el-icon-time" :disabled="!schedulerCanStart" @click="startScheduler({ scheduled: true })">定时启动</el-button>
              <el-button type="warning" plain icon="el-icon-close" :disabled="!schedulerCanTerminateTask" :loading="schedulerTerminatingTask" @click="terminateCurrentScheduleTask">终止当前任务</el-button>
              <el-button type="warning" icon="el-icon-video-pause" :disabled="!schedulerCanPause" @click="pauseScheduler">暂停调度</el-button>
              <el-button type="success" plain icon="el-icon-video-play" :disabled="!schedulerCanResume" @click="resumeScheduler">恢复调度</el-button>
              <el-button type="danger" plain icon="el-icon-switch-button" :disabled="!schedulerCanStop" @click="stopScheduler">强杀调度</el-button>
            </div>
          </div>

          <div class="scheduler-layout">
            <el-card shadow="never" class="section-card scheduler-config-card">
              <div slot="header" class="card-title"><h3>调度设置</h3><el-tag size="mini" :type="schedulerStatusType">{{ schedulerStatusText }}</el-tag></div>
              <el-form label-position="top" size="small">
                <el-form-item label="选择流程">
                  <el-select v-model="schedulerFlowSelection" multiple filterable class="full-width" placeholder="选择一个或多个状态流程">
                    <el-option
                      v-for="flow in flows"
                      :key="flow.filename"
                      :label="flowDisplayName(flow.filename)"
                      :value="flow.filename"
                    ></el-option>
                  </el-select>
                </el-form-item>
                <div class="scheduler-inline-fields">
                  <el-form-item label="执行次数">
                    <el-input-number v-model="schedulerDefaults.repeatCount" :min="1" :step="1" class="full-width"></el-input-number>
                  </el-form-item>
                  <el-form-item label="失败重试">
                    <el-input-number v-model="schedulerDefaults.retryCount" :min="0" :step="1" class="full-width"></el-input-number>
                  </el-form-item>
                </div>
                <el-form-item label="执行周序">
                  <el-select v-model="schedulerDefaults.weekdays" multiple collapse-tags class="full-width" placeholder="留空表示每天执行">
                    <el-option v-for="weekday in schedulerWeekdayOptions" :key="weekday.value" :label="weekday.label" :value="weekday.value"></el-option>
                  </el-select>
                  <div class="hint">加入队列时使用此默认周序；队列中每个流程仍可单独调整。</div>
                </el-form-item>
                <el-form-item label="开始时间">
                  <el-date-picker
                    v-model="scheduler.startAt"
                    type="datetime"
                    value-format="yyyy-MM-dd HH:mm:ss"
                    class="full-width"
                    placeholder="定时启动时必填；手动启动会忽略"
                  ></el-date-picker>
                </el-form-item>
                <div class="scheduler-option-row">
                  <el-checkbox v-model="scheduler.dryRun">dry run</el-checkbox>
                  <el-checkbox v-model="scheduler.continueOnError">失败后继续后续流程</el-checkbox>
                </div>
                <div class="toolbar-row">
                  <el-button type="primary" icon="el-icon-plus" @click="addScheduleFlows">加入队列</el-button>
                  <el-button icon="el-icon-refresh" @click="refreshFlows">刷新流程</el-button>
                  <el-button plain icon="el-icon-delete" :disabled="schedulerIsActive || !scheduleItems.length" @click="clearScheduleQueue">清空队列</el-button>
                  <el-button type="success" plain icon="el-icon-upload2" :disabled="schedulerIsActive" @click="saveSchedulerConfig">保存配置</el-button>
                </div>
              </el-form>
              <el-divider></el-divider>
              <div class="scheduler-message">
                <strong>{{ scheduler.message || '等待配置调度队列。' }}</strong>
                <span v-if="schedulerWaitingText">{{ schedulerWaitingText }}</span>
              </div>
              <el-progress :percentage="schedulerProgressPercent" :status="schedulerProgressStatus"></el-progress>
            </el-card>

            <el-card shadow="never" class="section-card scheduler-queue-card">
              <div slot="header" class="card-title"><h3>执行队列</h3><el-tag size="mini">{{ scheduleItems.length }}</el-tag></div>
              <el-table :data="scheduleItems" size="small" border empty-text="还没有加入流程" class="scheduler-table">
                <el-table-column label="#" width="48">
                  <template slot-scope="scope">{{ scope.$index + 1 }}</template>
                </el-table-column>
                <el-table-column label="流程" min-width="180">
                  <template slot-scope="scope">
                    <div class="scheduler-flow-cell">
                      <strong>{{ flowDisplayName(scope.row.filename) }}</strong>
                      <span>{{ scope.row.filename }}</span>
                      <span>{{ scheduleWeekdayText(scope.row.weekdays) }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="执行次数" width="128">
                  <template slot-scope="scope">
                    <el-input-number v-model="scope.row.repeatCount" :min="1" :step="1" size="mini" :disabled="schedulerIsActive"></el-input-number>
                  </template>
                </el-table-column>
                <el-table-column label="重试" width="112">
                  <template slot-scope="scope">
                    <el-input-number v-model="scope.row.retryCount" :min="0" :step="1" size="mini" :disabled="schedulerIsActive"></el-input-number>
                  </template>
                </el-table-column>
                <el-table-column label="执行周序" min-width="170">
                  <template slot-scope="scope">
                    <el-select
                      v-model="scope.row.weekdays"
                      multiple
                      collapse-tags
                      size="mini"
                      class="scheduler-weekday-select"
                      placeholder="每天"
                      :disabled="schedulerIsActive"
                    >
                      <el-option v-for="weekday in schedulerWeekdayOptions" :key="weekday.value" :label="weekday.label" :value="weekday.value"></el-option>
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="进度" width="120">
                  <template slot-scope="scope">
                    <span v-if="scope.row.status === 'skipped'">跳过 {{ scope.row.skippedRuns || scope.row.repeatCount || 1 }}</span>
                    <span v-else>{{ scope.row.completedRuns || 0 }} / {{ scope.row.repeatCount || 1 }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="116">
                  <template slot-scope="scope">
                    <el-tag size="mini" :type="scheduleItemStatusType(scope.row.status)">{{ scheduleItemStatusText(scope.row.status) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="202">
                  <template slot-scope="scope">
                    <el-button-group>
                      <el-button size="mini" icon="el-icon-arrow-up" :disabled="schedulerIsActive || scope.$index === 0" @click="moveScheduleItem(scope.$index, -1)"></el-button>
                      <el-button size="mini" icon="el-icon-arrow-down" :disabled="schedulerIsActive || scope.$index === scheduleItems.length - 1" @click="moveScheduleItem(scope.$index, 1)"></el-button>
                      <el-button size="mini" icon="el-icon-delete" :disabled="schedulerIsActive" @click="removeScheduleItem(scope.$index)"></el-button>
                      <el-button
                        v-if="scope.row.status === 'running'"
                        size="mini"
                        type="danger"
                        icon="el-icon-close"
                        :loading="schedulerTerminatingTask"
                        @click="terminateScheduleTask(scope.$index)"
                      ></el-button>
                    </el-button-group>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </div>

          <el-card shadow="never" class="section-card scheduler-results-card">
            <div slot="header" class="card-title">
              <h3>执行结果</h3>
              <div class="toolbar-row right">
                <span class="hint">记录每次执行与每次重试</span>
                <el-button size="mini" icon="el-icon-delete" :disabled="schedulerIsActive || !scheduleResults.length" @click="clearScheduleResults">清空结果</el-button>
              </div>
            </div>
            <el-table ref="scheduleResultsTable" :data="scheduleResults" size="small" border empty-text="尚未执行" class="scheduler-table">
              <el-table-column label="时间" width="152">
                <template slot-scope="scope">
                  <div class="scheduler-time-cell">
                    <span>{{ compactDateTime(scope.row.startedAt) }}</span>
                    <span>{{ scope.row.durationText || '-' }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="流程" min-width="160">
                <template slot-scope="scope">{{ flowDisplayName(scope.row.filename) }}</template>
              </el-table-column>
              <el-table-column label="轮次" width="92">
                <template slot-scope="scope">{{ scope.row.status === 'skipped' ? '-' : `${scope.row.runNumber} / ${scope.row.totalRuns}` }}</template>
              </el-table-column>
              <el-table-column label="尝试" width="92">
                <template slot-scope="scope">{{ scope.row.status === 'skipped' ? '-' : `${scope.row.attemptNumber} / ${scope.row.maxAttempts}` }}</template>
              </el-table-column>
              <el-table-column label="正常结束" width="108">
                <template slot-scope="scope">
                  <el-tag v-if="scope.row.status === 'skipped'" size="mini" type="info">-</el-tag>
                  <el-tag v-else size="mini" :type="scope.row.normalEnd ? 'success' : resultStatusType(scope.row.status)">
                    {{ scope.row.normalEnd ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="112">
                <template slot-scope="scope">
                  <el-tag size="mini" :type="resultStatusType(scope.row.status)">{{ resultStatusText(scope.row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="退出码" width="86" prop="exitCode"></el-table-column>
              <el-table-column label="结果信息" min-width="260">
                <template slot-scope="scope">
                  <span class="scheduler-result-message">{{ scope.row.message || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90">
                <template slot-scope="scope">
                  <el-button
                    v-if="scope.row.status === 'running'"
                    size="mini"
                    type="danger"
                    plain
                    :loading="schedulerTerminatingTask"
                    @click="terminateCurrentScheduleTask"
                  >终止</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

        </section>

        <section v-else-if="activePage === 'window'">
          <div class="content-grid">
            <el-card shadow="never" class="section-card">
              <div slot="header" class="card-title"><h3>窗口查找</h3></div>
              <el-form label-position="top" size="small">
                <el-form-item label="窗口标题包含"><el-input v-model="windowFind.title" placeholder="留空则使用配置"></el-input></el-form-item>
                <el-form-item label="进程名"><el-input v-model="windowFind.process_name" placeholder="可选"></el-input></el-form-item>
                <div class="toolbar-row">
                  <el-button type="primary" @click="findWindow">查找窗口</el-button>
                  <el-button @click="focusWindow">激活</el-button>
                  <el-button @click="setTopmost(true)">置顶</el-button>
                  <el-button @click="setTopmost(false)">取消置顶</el-button>
                  <el-button type="warning" plain @click="toggleFullscreen">全屏切换</el-button>
                  <el-button type="info" plain @click="rememberWindowSize">记录大小及位置</el-button>
                </div>
              </el-form>
            </el-card>
            <el-card shadow="never" class="section-card">
              <div slot="header" class="card-title"><h3>窗口信息</h3></div>
              <pre class="mono">{{ windowInfoText }}</pre>
            </el-card>
          </div>
        </section>
      </el-main>
    </el-container>

    <el-drawer
      :title="templateEditorMode === 'create' ? '保存新模板' : '模板编辑'"
      :visible.sync="templateEditorVisible"
      direction="rtl"
      size="420px"
      custom-class="template-editor-drawer"
    >
      <div v-if="templateEditorMode === 'create' || selectedTemplate" class="template-editor-body">
        <div class="template-editor-preview">
          <img v-if="templateEditorMode === 'edit'" :src="templatePreviewUrl(selectedTemplate.relative_path || selectedTemplate.path)" :alt="templateName(selectedTemplate)">
          <img v-else-if="capturePreviewUrlValue" :src="capturePreviewUrlValue" alt="新模板来源截图">
        </div>
        <el-form label-position="top" size="small">
          <el-form-item label="模板名称">
            <el-input v-model="templateEditor.name" placeholder="模板名称，可省略 .png"></el-input>
          </el-form-item>
          <el-form-item label="优先级">
            <el-input-number v-model="templateEditor.priority" :step="0.1" class="full-width"></el-input-number>
          </el-form-item>
          <el-form-item label="匹配阈值">
            <el-input-number v-model="templateEditor.threshold" :min="0.01" :max="1" :step="0.01" class="full-width"></el-input-number>
            <div class="hint">默认 0.85；loop_template 按每个模板自己的阈值判断。</div>
          </el-form-item>
          <el-form-item label="最多匹配次数">
            <el-input-number v-model="templateEditor.groupMatchLimit" :min="0" :step="1" class="full-width"></el-input-number>
            <div class="hint">0 表示不限制。</div>
          </el-form-item>
          <el-form-item label="流程标识">
            <div class="template-flag-editor">
              <el-switch v-model="templateEditor.isEndTemplate" active-text="结束标识"></el-switch>
              <el-switch v-model="templateEditor.isSuccessTemplate" active-text="成功标识"></el-switch>
              <el-checkbox v-model="templateEditor.isNonStandalone">非单独触发</el-checkbox>
              <el-checkbox v-model="templateEditor.isFallbackTemplate">兜底模板</el-checkbox>
              <el-checkbox v-model="templateEditor.avoidSamePosition">不匹配相同位置</el-checkbox>
            </div>
            <div class="hint">状态流程会自动使用选中循环目录中的结束/成功标识模板。非单独触发不参与 loop/F6 整组扫描；兜底模板只在整轮都未命中时按优先级执行 action。不匹配相同位置启用后，loop 中同一模板会避开已执行过的位置并尝试其它命中点。</div>
          </el-form-item>
          <el-form-item label="后置模板">
            <el-select v-model="templateEditor.postconditionTemplates" multiple filterable clearable class="full-width" placeholder="可选：当前模板命中后，这些模板也命中才生效">
              <el-option
                v-for="template in templateConditionOptions"
                :key="template.relative_path || template.path"
                :label="template.relative_path || template.path"
                :value="template.relative_path || template.path"
              ></el-option>
            </el-select>
            <div class="hint">当前模板先匹配；若配置了后置模板，必须在同一截图中全部命中，当前模板才生效。</div>
          </el-form-item>
          <el-form-item label="后置非模板">
            <el-select v-model="templateEditor.postconditionNotTemplates" multiple filterable clearable class="full-width" placeholder="可选：当前模板命中后，这些模板不能命中">
              <el-option
                v-for="template in templateConditionOptions"
                :key="template.relative_path || template.path"
                :label="template.relative_path || template.path"
                :value="template.relative_path || template.path"
              ></el-option>
            </el-select>
            <div class="hint">当前模板先匹配；若这些后置非模板任一命中，当前模板不生效。</div>
          </el-form-item>
          <el-divider content-position="left">匹配成功后 action</el-divider>
          <el-form-item label="动作类型">
            <el-select v-model="templateEditor.successAction.type" class="full-width">
              <el-option label="点击匹配位置" value="click_match"></el-option>
              <el-option label="无动作" value="none"></el-option>
              <el-option label="按键" value="key"></el-option>
              <el-option label="拖拽匹配位置" value="drag_match"></el-option>
              <el-option label="触发状态流程" value="flow"></el-option>
            </el-select>
          </el-form-item>
          <template v-if="templateEditor.successAction.type === 'click_match'">
            <el-form-item label="动作后等待(ms)"><el-input-number v-model="templateEditor.successAction.delay_after_ms" :min="0" :step="100" class="full-width"></el-input-number></el-form-item>
          </template>
          <template v-else-if="templateEditor.successAction.type === 'none'">
            <el-form-item label="等待时间(ms)"><el-input-number v-model="templateEditor.successAction.delay_after_ms" :min="0" :step="100" class="full-width"></el-input-number></el-form-item>
          </template>
          <template v-else-if="templateEditor.successAction.type === 'key'">
            <el-form-item label="按键"><el-select v-model="templateEditor.successAction.key" filterable allow-create class="full-width"><el-option label="ESC" value="esc"></el-option><el-option label="空格" value="space"></el-option></el-select></el-form-item>
            <el-form-item label="循环次数"><el-input-number v-model="templateEditor.successAction.loop_count" :min="1" :step="1" class="full-width"></el-input-number></el-form-item>
            <el-form-item label="按下时长(ms)"><el-input-number v-model="templateEditor.successAction.duration_ms" :min="0" :step="10" class="full-width"></el-input-number></el-form-item>
            <el-form-item label="动作后等待 / 循环间隔(ms)"><el-input-number v-model="templateEditor.successAction.delay_after_ms" :min="0" :step="100" class="full-width"></el-input-number></el-form-item>
          </template>
          <template v-else-if="templateEditor.successAction.type === 'drag_match'">
            <el-form-item label="方向"><el-select v-model="templateEditor.successAction.direction" class="full-width"><el-option label="向上" value="up"></el-option><el-option label="向下" value="down"></el-option><el-option label="向左" value="left"></el-option><el-option label="向右" value="right"></el-option></el-select></el-form-item>
            <el-form-item label="距离（屏幕百分比）"><el-input-number v-model="templateEditor.successAction.distancePercent" :min="1" :max="100" :step="1" class="full-width"></el-input-number></el-form-item>
            <el-form-item label="拖拽耗时(ms)"><el-input-number v-model="templateEditor.successAction.duration_ms" :min="0" :step="50" class="full-width"></el-input-number></el-form-item>
            <el-form-item label="动作后等待(ms)"><el-input-number v-model="templateEditor.successAction.delay_after_ms" :min="0" :step="100" class="full-width"></el-input-number></el-form-item>
          </template>
          <template v-else-if="templateEditor.successAction.type === 'flow'">
            <el-form-item label="状态流程"><el-select v-model="templateEditor.successAction.flow" filterable class="full-width"><el-option v-for="flow in flows" :key="flow.filename" :label="flowLabel(flow)" :value="flow.id || flowDisplayName(flow.filename)"></el-option></el-select></el-form-item>
          </template>
          <el-form-item label="动作说明">
            <el-input v-model="templateEditor.successAction.note" placeholder="可选"></el-input>
          </el-form-item>
          <el-divider content-position="left">动作后指定模板</el-divider>
          <el-form-item label="目标模板">
            <el-select v-model="templateEditor.postActionTemplate" filterable clearable class="full-width" placeholder="可选：本模板 action 完成后再匹配并执行目标模板">
              <el-option v-for="template in sameGroupTemplates" :key="template.relative_path || template.path" :label="template.relative_path || template.path" :value="template.relative_path || template.path"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="目标模板阈值">
            <el-input-number v-model="templateEditor.postActionTemplateThreshold" :min="0" :max="1" :step="0.01" class="full-width"></el-input-number>
            <div class="hint">默认 0.85。</div>
          </el-form-item>
          <el-form-item label="目标模板执行后等待(ms)">
            <el-input-number v-model="templateEditor.postActionTemplateDelayMs" :min="0" :step="100" class="full-width"></el-input-number>
          </el-form-item>
          <div class="template-editor-actions">
            <el-button @click="templateEditorVisible = false">取消</el-button>
            <el-button
              v-if="templateEditorMode === 'edit'"
              icon="el-icon-document-copy"
              :loading="templateCopySaving"
              :disabled="!selectedTemplate || templateEditorSaving"
              @click="openTemplateCopyDialog"
            >复制</el-button>
            <el-button type="primary" :loading="templateEditorSaving" @click="saveTemplateEditor">保存</el-button>
          </div>
        </el-form>
      </div>
    </el-drawer>

    <el-dialog title="复制模板" :visible.sync="templateCopyDialogVisible" width="420px" append-to-body>
      <el-form label-position="top" size="small">
        <el-form-item label="目标分组">
          <el-select v-model="templateCopyTargetGroup" filterable class="full-width" placeholder="请选择模板分组">
            <el-option
              v-for="group in templateCopyGroupOptions"
              :key="group.name || '__root__'"
              :label="group.label"
              :value="group.name"
              :disabled="group.name === ((selectedTemplate && selectedTemplate.group) || '')"
            ></el-option>
          </el-select>
          <div class="hint">复制当前已保存的模板图片及配置 JSON。若目标分组已有同名模板，将提示失败。</div>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="templateCopyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="templateCopySaving" @click="copySelectedTemplate">复制</el-button>
      </span>
    </el-dialog>
  </el-container>
</template>

<script>
export default {
  name: 'App',
  data() {
    return {
      activePage: 'dashboard',
      apiAvailable: true,
      bootstrapping: false,
      statusText: '正在连接工作台 API 服务...',
      lastAction: '',
      capabilities: { window: false, workflow: false, capture: false, template: false },
      settings: {},
      templates: [],
      templateGroups: [],
      templateAssetVersion: Date.now(),
      flows: [],
      windowInfo: null,
      startupError: '',
      selectedGroup: '__all__',
      selectedTemplate: null,
      templateEditorVisible: false,
      templateEditorSaving: false,
      templateCopyDialogVisible: false,
      templateCopySaving: false,
      templateCopyTargetGroup: '',
      templateEditorMode: 'edit',
      templateEditor: this.defaultTemplateEditor(),
      captureLoading: false,
      captureForm: { bring_to_front: false, backend: 'auto' },
      capture: {},
      captureSourceTemplate: null,
      capturePreviewUrlValue: '',
      captureImageSize: { width: 0, height: 0 },
      captureDisplaySize: { width: 0, height: 0 },
      browserPixelRatio: typeof window !== 'undefined' && window.devicePixelRatio ? window.devicePixelRatio : 1,
      captureRegion: null,
      clickCaptureRegion: null,
      clickCaptureRegions: [],
      captureSelectionMode: '',
      captureSelectionDrag: null,
      groupActionMatches: [],
      selectedGroupActionMatch: null,
      screenshotHotkeyStatus: '按 F1 截图。',
      selectedFlowFilename: '',
      isNewFlowDraft: false,
      flowDryRun: false,
      flowPreferLoopFirst: true,
      flowFilter: '',
      flowSaving: false,
      flowStarting: false,
      flowDeleting: false,
      flowFailureEntries: [],
      flowUnrecognizedTemplate: null,
      flowLastUnrecognizedPath: '',
      flowDraft: { filename: '', start: [], loopDir: [], completionCount: 1 },
      scheduler: {
        status: 'idle',
        startAt: '',
        dryRun: false,
        continueOnError: true,
        currentFilename: '',
        message: '',
        waitUntil: null,
      },
      schedulerDefaults: { repeatCount: 1, retryCount: 0, weekdays: [] },
      schedulerWeekdayOptions: [
        { value: 1, label: '周一' },
        { value: 2, label: '周二' },
        { value: 3, label: '周三' },
        { value: 4, label: '周四' },
        { value: 5, label: '周五' },
        { value: 6, label: '周六' },
        { value: 0, label: '周日' },
      ],
      schedulerFlowSelection: [],
      schedulerRunToken: 0,
      schedulerPaused: false,
      schedulerTerminatingTask: false,
      schedulerClockTimer: null,
      schedulerNow: Date.now(),
      scheduleItems: [],
      scheduleResults: [],
      windowFind: { title: '', process_name: '' },
    };
  },
  computed: {
    pageTitle() {
      return { dashboard: '新版工作台总览', templates: '模板 / 截图', flows: '状态流程', scheduler: '流程调度', window: '窗口工具' }[this.activePage] || 'Monster Job';
    },
    windowSizeText() {
      const liveSize = this.windowInfo && this.windowInfo.client_size ? this.windowInfo.client_size : null;
      const game = this.settings.game || {};
      const size = liveSize || game.window_size || {};
      if (size.width && size.height) {
        const sourceText = liveSize ? '窗口' : '配置窗口';
        const pixelSizeText = `${size.width}x${size.height}`;
        const displaySizeText = this.displayWindowSizeText;
        const displaySuffix = displaySizeText && displaySizeText !== pixelSizeText ? ` · 页面 ${displaySizeText}` : '';
        return `${sourceText} ${pixelSizeText}${displaySuffix}`;
      }
      return '窗口尺寸读取中';
    },
    selectableTemplateGroups() {
      return this.templateGroups.filter(group => group && group.name && !String(group.name).endsWith('/未识别'));
    },
    templateCopyGroupOptions() {
      return (this.templateGroups || [])
        .filter(group => group && !String(group.name || '').endsWith('/未识别'))
        .map(group => ({
          name: group.name || '',
          label: group.name || '未分组 / root',
        }));
    },
    unrecognizedTemplates() {
      return this.templates.filter(template => this.isUnrecognizedTemplate(template));
    },
    unrecognizedTemplateCount() {
      return this.unrecognizedTemplates.length;
    },
    hasUnrecognizedTemplates() {
      return this.unrecognizedTemplateCount > 0;
    },
    filteredTemplates() {
      if (this.selectedGroup === '__unrecognized__') {
        return this.sortedTemplates(this.unrecognizedTemplates);
      }
      const templates = this.selectedGroup === '__all__'
        ? this.templates
        : this.templates.filter(item => (item.group || '') === this.selectedGroup);
      return this.sortedTemplates(templates.filter(t => !this.isUnrecognizedTemplate(t)));
    },
    groupedTemplates() {
      const map = new Map();
      for (const t of this.filteredTemplates) {
        const key = t.group || '';
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(t);
      }
      const entries = [];
      map.forEach((items, group) => entries.push({ group, items }));
      entries.sort((a, b) => a.group.localeCompare(b.group));
      return entries;
    },
    sameGroupTemplates() {
      const group = (this.templateEditor && this.templateEditor._group) || '';
      return this.templates.filter(t => (t.group || '') === group && !this.isUnrecognizedTemplate(t));
    },
    visibleChildTemplateGroups() {
      const current = String(this.selectedGroup || '').replace(/\\/g, '/').replace(/\/$/, '');
      const browsingRoot = !current || current === '__all__';
      const prefix = browsingRoot ? '' : `${current}/`;
      return this.templateGroups
        .filter(group => {
          const name = String(group.name || '').replace(/\\/g, '/');
          if (!name || (!browsingRoot && (name === current || !name.startsWith(prefix)))) return false;
          return !name.slice(prefix.length).includes('/');
        })
        .sort((left, right) => String(left.name || '').localeCompare(String(right.name || '')));
    },
    filteredFlows() {
      const query = String(this.flowFilter || '').trim().toLowerCase();
      if (!query) return this.flows;
      return this.flows.filter(flow => {
        const filename = String(flow.filename || '').toLowerCase();
        const displayName = this.flowDisplayName(filename).toLowerCase();
        const loopDirs = (flow.loop_dirs || []).join(' ').toLowerCase();
        return filename.includes(query) || displayName.includes(query) || loopDirs.includes(query);
      });
    },
    flowOptionsForDraft() {
      const current = this.flowDraftFilename();
      return this.flows.filter(flow => flow.filename !== current);
    },
    flowLoopTemplates() {
      const selectedGroups = new Set(this.flowDraft.loopDir || []);
      if (!selectedGroups.size) return [];
      const templates = this.templates.filter(item => selectedGroups.has(item.group || ''));
      return this.sortedTemplates(templates);
    },
    flowLoopTemplateEmptyText() {
      return (this.flowDraft.loopDir || []).length ? '选中的循环模板目录下没有模板' : '请先选择循环模板目录';
    },
    flowEndTemplateCount() {
      return this.flowLoopTemplates.filter(template => this.templateIsEnd(template)).length;
    },
    flowSuccessTemplateCount() {
      return this.flowLoopTemplates.filter(template => this.templateIsSuccess(template)).length;
    },
    flowFallbackTemplateCount() {
      return this.flowLoopTemplates.filter(template => this.templateIsFallback(template)).length;
    },
    schedulerIsActive() {
      return ['scheduled', 'running', 'stopping'].includes(this.scheduler.status);
    },
    schedulerCanStart() {
      return !this.schedulerIsActive && this.scheduleItems.length > 0;
    },
    schedulerCanStop() {
      return this.schedulerIsActive || this.hasRunningTemplateLoopFlow;
    },
    hasRunningTemplateLoopFlow() {
      return (this.flows || []).some(flow => flow && flow.running);
    },
    selectedFlowRunning() {
      const flow = (this.flows || []).find(f => f && f.filename === this.selectedFlowFilename);
      return flow ? Boolean(flow.running) : false;
    },
    selectedFlowPaused() {
      const flow = (this.flows || []).find(f => f && f.filename === this.selectedFlowFilename);
      return flow ? Boolean(flow.paused) : false;
    },
    currentSchedulerFilename() {
      if (this.scheduler.currentFilename) return this.scheduler.currentFilename;
      const activeItem = (this.scheduleItems || []).find(item => item && item.status === 'running' && item.filename);
      if (activeItem) return activeItem.filename;
      const runningFlow = (this.flows || []).find(flow => flow && flow.running && flow.filename);
      return runningFlow ? runningFlow.filename : '';
    },
    schedulerCanTerminateTask() {
      return Boolean(this.currentSchedulerFilename) && !this.schedulerTerminatingTask;
    },
    schedulerCanPause() {
      return this.scheduler.status === 'running' && !this.schedulerPaused;
    },
    schedulerCanResume() {
      return this.schedulerPaused && this.schedulerIsActive;
    },
    schedulerFailureFilename() {
      if (this.scheduler.currentFilename) return this.scheduler.currentFilename;
      const recentResult = (this.scheduleResults || []).find(result => result && result.filename);
      if (recentResult) return recentResult.filename;
      const activeItem = (this.scheduleItems || []).find(item => item && item.status === 'running' && item.filename);
      if (activeItem) return activeItem.filename;
      const firstItem = (this.scheduleItems || []).find(item => item && item.filename);
      return firstItem ? firstItem.filename : '';
    },
    schedulerTotalRuns() {
      return this.scheduleItems.reduce((total, item) => total + Math.max(1, Math.floor(Number(item.repeatCount || 1))), 0);
    },
    schedulerFinishedRuns() {
      return this.scheduleItems.reduce((total, item) => {
        const completed = Math.max(0, Math.floor(Number(item.completedRuns || 0)));
        const skipped = Math.max(0, Math.floor(Number(item.skippedRuns || 0)));
        return total + completed + skipped;
      }, 0);
    },
    schedulerSuccessRuns() {
      return this.scheduleResults.filter(result => result.normalEnd).length;
    },
    schedulerProgressPercent() {
      if (!this.schedulerTotalRuns) return 0;
      return Math.min(100, Math.floor((this.schedulerFinishedRuns / this.schedulerTotalRuns) * 100));
    },
    schedulerProgressStatus() {
      if (this.scheduler.status === 'failed') return 'exception';
      if (this.scheduler.status === 'completed') return 'success';
      return undefined;
    },
    schedulerStatusText() {
      const map = {
        idle: '待启动',
        scheduled: '等待开始',
        running: '执行中',
        stopping: '停止中',
        completed: '已完成',
        failed: '失败',
        stopped: '已停止',
      };
      return map[this.scheduler.status] || this.scheduler.status;
    },
    schedulerStatusType() {
      const map = {
        scheduled: 'warning',
        running: 'success',
        completed: 'success',
        failed: 'danger',
        stopped: 'info',
        stopping: 'warning',
      };
      return map[this.scheduler.status] || 'info';
    },
    schedulerWaitingText() {
      const waitUntil = this.scheduler.waitUntil ? new Date(this.scheduler.waitUntil).getTime() : 0;
      if (!waitUntil || waitUntil <= this.schedulerNow) return '';
      const remaining = Math.max(0, Math.ceil((waitUntil - this.schedulerNow) / 1000));
      const minutes = Math.floor(remaining / 60);
      const seconds = remaining % 60;
      return `距离开始 ${minutes}分${String(seconds).padStart(2, '0')}秒`;
    },
    selectedGroupLabel() {
      if (this.selectedGroup === '__all__') return 'All';
      return this.selectedGroup || 'root';
    },
    canEditSelectedTemplateGroup() {
      return Boolean(this.selectedGroup && this.selectedGroup !== '__all__');
    },
    isSelectedUnrecognizedGroup() {
      return String(this.selectedGroup || '').replace(/\\/g, '/').endsWith('/未识别');
    },
    selectedUnrecognizedParentGroup() {
      const group = String(this.selectedGroup || '').replace(/\\/g, '/');
      return group.endsWith('/未识别') ? group.slice(0, -'/未识别'.length) : group;
    },
    selectedTemplateText() {
      return JSON.stringify(this.selectedTemplate || {}, null, 2);
    },
    templateConditionOptions() {
      const selectedPath = this.selectedTemplate ? (this.selectedTemplate.relative_path || this.selectedTemplate.path) : '';
      return this.sortedTemplates(this.templates).filter(template => (template.relative_path || template.path) !== selectedPath);
    },
    flowYamlPreview() {
      const lines = [];
      lines.push(`completion_count: ${Math.max(1, Math.floor(Number(this.flowDraft.completionCount || 1)))}`);
      lines.push('start_flows:');
      if (this.flowDraft.start.length) this.flowDraft.start.forEach(name => lines.push(`  - ${name}`));
      else lines.push('  []');
      lines.push('loop_dirs:');
      if (this.flowDraft.loopDir.length) this.flowDraft.loopDir.forEach(name => lines.push(`  - ${name}`));
      else lines.push('  []');
      return lines.join('\n');
    },
    windowInfoText() {
      return this.windowInfo ? JSON.stringify(this.windowInfo, null, 2) : '尚未选择窗口。';
    },
    targetGameImageSize() {
      const liveSize = this.windowInfo && this.windowInfo.client_size ? this.windowInfo.client_size : null;
      const game = this.settings.game || {};
      const configuredSize = game.window_size || null;
      return liveSize || configuredSize || null;
    },
    displayWindowSizeText() {
      const size = this.targetGameImageSize;
      const displaySize = this.imageDisplaySize(size && size.width, size && size.height);
      if (displaySize.width && displaySize.height) return `${displaySize.width}x${displaySize.height}`;
      return '';
    },
  },
  watch: {
    scheduler: {
      deep: true,
      handler() {
        this.saveSchedulerState();
      },
    },
    schedulerDefaults: {
      deep: true,
      handler() {
        this.saveSchedulerState();
      },
    },
    scheduleItems: {
      deep: true,
      handler() {
        this.saveSchedulerState();
      },
    },
    scheduleResults: {
      deep: true,
      handler() {
        this.saveSchedulerState();
      },
    },
  },
  mounted() {
    this.loadSchedulerState();
    this.startSchedulerClock();
    this.bootstrap();
    window.addEventListener('keydown', this.handleTemplateHotkey);
    window.addEventListener('mousemove', this.updateCaptureSelectionDrag);
    window.addEventListener('mouseup', this.finishCaptureSelection);
    window.addEventListener('resize', this.updateBrowserPixelRatio);
  },
  beforeDestroy() {
    this.schedulerRunToken += 1;
    this.clearSchedulerClock();
    window.removeEventListener('keydown', this.handleTemplateHotkey);
    window.removeEventListener('mousemove', this.updateCaptureSelectionDrag);
    window.removeEventListener('mouseup', this.finishCaptureSelection);
    window.removeEventListener('resize', this.updateBrowserPixelRatio);
  },
  methods: {
    selectPage(page) {
      this.activePage = page;
    },
    updateBrowserPixelRatio() {
      this.browserPixelRatio = typeof window !== 'undefined' && window.devicePixelRatio ? window.devicePixelRatio : 1;
      this.$nextTick(this.updateCaptureOverlay);
    },
    gameDisplayScale() {
      const ratio = Number(this.browserPixelRatio || 1);
      return Number.isFinite(ratio) && ratio > 0 ? 1 / ratio : 1;
    },
    imageDisplaySize(width, height) {
      const naturalWidth = Math.max(0, Number(width || 0));
      const naturalHeight = Math.max(0, Number(height || 0));
      if (!naturalWidth || !naturalHeight) return { width: 0, height: 0 };
      const scale = this.gameDisplayScale();
      return {
        width: Math.max(1, Math.round(naturalWidth * scale)),
        height: Math.max(1, Math.round(naturalHeight * scale)),
      };
    },
    templateImageDisplayStyle(template) {
      const displaySize = this.imageDisplaySize(template && template.width, template && template.height);
      if (!displaySize.width || !displaySize.height) return {};
      return {
        width: `${displaySize.width}px`,
        height: `${displaySize.height}px`,
      };
    },
    async apiGet(path) {
      const response = await fetch(path, { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      return payload;
    },
    async apiPost(path, body = {}) {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      return payload;
    },
    async apiDelete(path) {
      const response = await fetch(path, { method: 'DELETE' });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      return payload;
    },
    async bootstrap() {
      this.bootstrapping = true;
      try {
        const payload = await this.apiGet('/api/bootstrap');
        this.apiAvailable = true;
        this.capabilities = payload.capabilities || this.capabilities;
        this.settings = payload.settings || {};
        this.templates = payload.templates || [];
        this.templateGroups = payload.template_groups || [];
        this.templateAssetVersion = Date.now();
        this.flows = payload.template_loop_flows || [];
        this.windowInfo = payload.window || null;
        this.startupError = payload.startup && payload.startup.error ? payload.startup.error : '';
        this.statusText = this.windowInfo ? `已连接，游戏窗口：${this.windowInfo.title}` : (this.startupError ? `已连接，但窗口未准备：${this.startupError}` : '已连接本地工作台 API。');
        await this.loadSchedulerConfig();
      } catch (error) {
        this.apiAvailable = false;
        this.notifyError(error);
        this.statusText = `连接失败：${error.message || error}。请确认 Python API 后端运行在 Vite 代理目标端口。`;
      } finally {
        this.bootstrapping = false;
      }
    },
    async refreshTemplates() {
      const payload = await this.apiGet('/api/templates');
      this.templates = payload.templates || [];
      this.templateGroups = payload.template_groups || [];
      this.templateAssetVersion = Date.now();
      this.lastAction = '刷新模板';
    },
    async refreshFlows() {
      const payload = await this.apiGet('/api/template-loop-flows');
      this.flows = payload.flows || [];
      this.lastAction = '刷新流程';
    },
    async createTemplateGroup() {
      try {
        const name = await this.$prompt('请输入新分组名', '新建分组', {
          confirmButtonText: '新建',
          cancelButtonText: '取消',
          inputPattern: /\S/,
          inputErrorMessage: '分组名不能为空',
        });
        const groupName = name.value.trim();
        const payload = await this.apiPost('/api/template-groups', { name: groupName });
        this.templateGroups = payload.groups || this.templateGroups;
        this.selectedGroup = payload.group && payload.group.name ? payload.group.name : groupName;
        this.selectedTemplate = null;
        await this.refreshTemplates();
        this.lastAction = '新建分组';
        this.$message.success('分组已新建');
      } catch (error) {
        if (error !== 'cancel') this.notifyError(error);
      }
    },
    async copyTemplateGroup() {
      if (!this.canEditSelectedTemplateGroup) return;
      try {
        const name = await this.$prompt('请输入复制后的新分组名', '复制分组', {
          confirmButtonText: '复制',
          cancelButtonText: '取消',
          inputValue: `${this.selectedGroup}_copy`,
          inputPattern: /\S/,
          inputErrorMessage: '分组名不能为空',
        });
        const targetName = name.value.trim();
        const payload = await this.apiPost('/api/template-group-copy', { source_name: this.selectedGroup, target_name: targetName });
        this.templates = payload.templates || this.templates;
        this.templateGroups = payload.groups || this.templateGroups;
        this.templateAssetVersion = Date.now();
        this.selectedGroup = targetName;
        this.selectedTemplate = null;
        this.lastAction = '复制分组';
        this.$message.success('分组已复制');
      } catch (error) {
        if (error !== 'cancel') this.notifyError(error);
      }
    },
    async renameTemplateGroup() {
      if (!this.canEditSelectedTemplateGroup) return;
      try {
        const name = await this.$prompt('请输入新的分组名', '重命名分组', {
          confirmButtonText: '重命名',
          cancelButtonText: '取消',
          inputValue: this.selectedGroup,
          inputPattern: /\S/,
          inputErrorMessage: '分组名不能为空',
        });
        const newName = name.value.trim();
        const payload = await this.apiPost('/api/template-group-rename', { old_name: this.selectedGroup, new_name: newName });
        this.templates = payload.templates || this.templates;
        this.templateGroups = payload.groups || this.templateGroups;
        this.templateAssetVersion = Date.now();
        this.selectedGroup = newName;
        this.selectedTemplate = null;
        this.lastAction = '重命名分组';
        this.$message.success('分组已重命名');
      } catch (error) {
        if (error !== 'cancel') this.notifyError(error);
      }
    },
    async deleteTemplateGroup() {
      if (!this.canEditSelectedTemplateGroup) return;
      try {
        await this.$confirm(`确认删除分组「${this.selectedGroup}」？仅空分组可删除。`, '删除分组', {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning',
        });
        const payload = await this.apiPost('/api/template-group-delete', { name: this.selectedGroup });
        this.templateGroups = payload.groups || this.templateGroups;
        this.selectedGroup = '__all__';
        this.selectedTemplate = null;
        await this.refreshTemplates();
        this.lastAction = '删除分组';
        this.$message.success('分组已删除');
      } catch (error) {
        if (error !== 'cancel') this.notifyError(error);
      }
    },
    async clearUnrecognizedTemplates() {
      if (!this.isSelectedUnrecognizedGroup) return;
      try {
        await this.$confirm(`确认清空「${this.selectedGroup}」下的未识别截图？`, '清空未识别', {
          confirmButtonText: '清空',
          cancelButtonText: '取消',
          type: 'warning',
        });
        const payload = await this.apiPost('/api/template-unrecognized-clear', { name: this.selectedGroup });
        const clearedGroup = this.selectedGroup;
        this.templates = payload.templates || this.templates;
        this.templateGroups = payload.groups || this.templateGroups;
        this.templateAssetVersion = Date.now();
        this.selectedTemplate = null;
        this.flowUnrecognizedTemplate = null;
        if (this.capture.path && String(this.capture.path).replace(/\\/g, '/').includes(`/${clearedGroup}/`)) {
          this.capture = {};
          this.capturePreviewUrlValue = '';
          this.captureRegion = null;
          this.clickCaptureRegion = null;
          this.clickCaptureRegions = [];
        }
        this.lastAction = '清空未识别';
        this.$message.success(`已清空 ${payload.deleted || 0} 张未识别截图`);
      } catch (error) {
        if (error !== 'cancel') this.notifyError(error);
      }
    },
    async clearAllUnrecognizedTemplates() {
      if (!this.hasUnrecognizedTemplates) return;
      try {
        await this.$confirm(`确认清空所有分组下的 ${this.unrecognizedTemplateCount} 张未识别截图？`, '清空全部未识别', {
          confirmButtonText: '全部清空',
          cancelButtonText: '取消',
          type: 'warning',
        });
        const shouldResetCapture = this.isUnrecognizedTemplate(this.captureSourceTemplate)
          || String((this.capture && this.capture.path) || '').replace(/\\/g, '/').includes('/未识别/');
        const payload = await this.apiPost('/api/template-unrecognized-clear', { all: true });
        this.templates = payload.templates || this.templates;
        this.templateGroups = payload.groups || this.templateGroups;
        this.templateAssetVersion = Date.now();
        this.selectedTemplate = null;
        this.flowUnrecognizedTemplate = null;
        this.captureSourceTemplate = null;
        if (shouldResetCapture) {
          this.capture = {};
          this.capturePreviewUrlValue = '';
          this.captureRegion = null;
          this.clickCaptureRegion = null;
          this.clickCaptureRegions = [];
        }
        if (this.isSelectedUnrecognizedGroup) {
          this.selectedGroup = this.selectedUnrecognizedParentGroup || '__all__';
        }
        this.lastAction = '清空全部未识别';
        this.$message.success(`已清空 ${payload.deleted || 0} 张未识别截图`);
      } catch (error) {
        if (error !== 'cancel') this.notifyError(error);
      }
    },
    defaultTemplateEditor() {
      return {
        name: '',
        threshold: 0.85,
        priority: 0,
        groupMatchLimit: 0,
        isEndTemplate: false,
        isSuccessTemplate: false,
        isNonStandalone: false,
        isFallbackTemplate: false,
        avoidSamePosition: false,
        postconditionTemplates: [],
        postconditionNotTemplates: [],
        postActionTemplate: '',
        postActionTemplateThreshold: 0.85,
        postActionTemplateDelayMs: 500,
        successAction: { type: 'click_match', delay_after_ms: 500, loop_count: 1, distancePercent: 30, note: '' },
      };
    },
    normalizeTemplateReferences(value) {
      const values = Array.isArray(value) ? value : [value];
      return values.map(item => String(item || '').trim()).filter(Boolean);
    },
    normalizePostconditionTemplates(metadata = {}) {
      return this.normalizeTemplateReferences(
        metadata.postcondition_templates
        || metadata.postcondition_template
        || metadata.precondition_templates
        || metadata.precondition_template
        || metadata.requires_templates
        || metadata.requires_template
        || []
      );
    },
    normalizePostconditionNotTemplates(metadata = {}) {
      return this.normalizeTemplateReferences(
        metadata.postcondition_not_templates
        || metadata.postcondition_not_template
        || metadata.excludes_templates
        || metadata.excludes_template
        || []
      );
    },
    normalizeTemplateAction(action = {}, allowedTypes = ['click_match', 'none', 'key', 'drag_match', 'flow'], fallbackType = 'click_match') {
      const type = allowedTypes.includes(action.type) ? action.type : fallbackType;
      return {
        type,
        key: action.key || 'esc',
        direction: action.direction || 'up',
        template: action.template || '',
        flow: action.flow || action.name || '',
        threshold: Number(action.threshold || 0),
        distancePercent: Number(action.distance_percent ?? action.distancePercent ?? 30),
        distance: Number(action.distance || 300),
        duration_ms: Number(action.duration_ms ?? (type === 'key' ? 50 : 300)),
        delay_after_ms: Number(action.delay_after_ms ?? (type === 'click_match' || type === 'drag_match' ? 500 : 0)),
        loop_count: Math.max(1, Math.floor(Number(action.loop_count || action.loopCount || 1))),
        note: action.note || '',
      };
    },
    openTemplateCard(template) {
      if (this.isUnrecognizedTemplate(template)) {
        this.useUnrecognizedTemplateAsCapture(template);
        return;
      }
      this.openTemplateEditor(template);
    },
    openTemplateEditor(template) {
      if (!template) return;
      this.selectedGroup = template.group || '';
      this.selectedTemplate = template;
      const metadata = template.metadata || {};
      const actions = Array.isArray(metadata.actions) ? metadata.actions : [];
      const templateAction = actions.find(action => action && action.type === 'template') || null;
      const nonTemplateAction = actions.find(action => action && action.type !== 'wait' && action.type !== 'template') || null;
      const successAction = nonTemplateAction || (templateAction ? { type: 'none', delay_after_ms: 0 } : { type: 'click_match', delay_after_ms: 500 });
      this.templateEditorMode = 'edit';
      this.templateEditor = {
        _group: template.group || '',
        name: this.templateName(template).replace(/\.png$/i, ''),
        threshold: Number.isFinite(Number(metadata.threshold)) ? Number(metadata.threshold) : 0.85,
        priority: Number.isFinite(Number(metadata.priority)) ? Number(metadata.priority) : 0,
        groupMatchLimit: Number(metadata.group_match_limit || 0) >= 1 ? Math.floor(Number(metadata.group_match_limit)) : 0,
        isEndTemplate: Boolean(metadata.is_end_template),
        isSuccessTemplate: Boolean(metadata.is_success_template),
        isNonStandalone: Boolean(metadata.is_non_standalone || metadata.non_standalone),
        isFallbackTemplate: Boolean(metadata.is_fallback_template || metadata.fallback_template),
        avoidSamePosition: Boolean(metadata.avoid_same_position || metadata.not_match_same_position),
        postconditionTemplates: this.normalizePostconditionTemplates(metadata),
        postconditionNotTemplates: this.normalizePostconditionNotTemplates(metadata),
        postActionTemplate: metadata.post_action_template || metadata.next_template || (templateAction && templateAction.template) || '',
        postActionTemplateThreshold: Number(metadata.post_action_template_threshold || metadata.next_template_threshold || (templateAction && templateAction.threshold) || 0.85),
        postActionTemplateDelayMs: Number(metadata.post_action_template_delay_ms || metadata.next_template_delay_ms || (templateAction && templateAction.delay_after_ms) || 500),
        successAction: this.normalizeTemplateAction(successAction),
      };
      this.templateEditorVisible = true;
    },
    openFlowTemplateEditor(template) {
      this.openTemplateEditor(template);
    },
    openTemplateCopyDialog() {
      if (this.templateEditorMode !== 'edit' || !this.selectedTemplate) {
        this.$message.warning('请先选择一个模板。');
        return;
      }
      const currentGroup = (this.selectedTemplate && this.selectedTemplate.group) || '';
      const firstOtherGroup = this.templateCopyGroupOptions.find(group => group.name !== currentGroup);
      this.templateCopyTargetGroup = firstOtherGroup ? firstOtherGroup.name : '';
      this.templateCopyDialogVisible = true;
    },
    async copySelectedTemplate() {
      if (!this.selectedTemplate) return;
      const sourcePath = this.selectedTemplate.relative_path || this.selectedTemplate.path;
      const currentGroup = this.selectedTemplate.group || '';
      const targetGroup = this.templateCopyTargetGroup || '';
      if (targetGroup === currentGroup) {
        this.$message.warning('请选择不同的目标分组。');
        return;
      }

      this.templateCopySaving = true;
      try {
        const payload = await this.apiPost('/api/template-copy', {
          path: sourcePath,
          target_group: targetGroup,
          filename: this.templateName(this.selectedTemplate),
          replace: false,
        });
        this.templates = payload.templates || this.templates;
        this.templateGroups = payload.groups || this.templateGroups;
        this.templateAssetVersion = Date.now();
        const copiedPath = payload.template && (payload.template.relative_path || payload.template.path);
        const copiedTemplate = this.templates.find(item => (item.relative_path || item.path) === copiedPath) || payload.template || null;
        if (copiedTemplate) {
          this.openTemplateEditor(copiedTemplate);
        } else {
          this.selectedGroup = targetGroup;
          this.selectedTemplate = null;
        }
        this.templateCopyDialogVisible = false;
        this.lastAction = '复制模板';
        this.$message.success('模板已复制');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.templateCopySaving = false;
      }
    },
    isUnrecognizedTemplate(template) {
      if (!template) return false;
      const metadata = template.metadata || {};
      const value = `${template.relative_path || template.path || ''}`.replace(/\\/g, '/');
      return metadata.source === 'template_loop_unrecognized' || value.includes('/未识别/');
    },
    unrecognizedTemplateTargetGroup(template) {
      const group = String((template && template.group) || '');
      return group.endsWith('/未识别') ? group.slice(0, -'/未识别'.length) : group;
    },
    useUnrecognizedTemplateAsCapture(template = this.flowUnrecognizedTemplate) {
      if (!template) return;
      const path = template.path || template.relative_path;
      if (!path) return;
      this.capture = {
        path,
        size: { width: template.width || 0, height: template.height || 0 },
      };
      this.captureSourceTemplate = template;
      this.captureRegion = null;
      this.clickCaptureRegion = null;
      this.clickCaptureRegions = [];
      this.captureSelectionMode = '';
      this.capturePreviewUrlValue = this.imagePreviewUrl(path);
      this.selectedGroup = template.group || this.selectedGroup;
      this.selectedTemplate = null;
      this.activePage = 'templates';
      this.screenshotHotkeyStatus = '已载入未识别截图。按 F2 圈选识别区，按 F3 圈选点击区，按 F4 保存模板。';
      this.$nextTick(this.updateCaptureOverlay);
    },
    returnToParentTemplateGroup() {
      if (!this.isSelectedUnrecognizedGroup) return;
      this.selectedGroup = this.selectedUnrecognizedParentGroup || '';
      this.selectedTemplate = null;
    },
    async deleteCaptureSourceTemplateIfUnrecognized() {
      const source = this.captureSourceTemplate;
      if (!this.isUnrecognizedTemplate(source)) return;
      const sourcePath = source.path || source.relative_path;
      if (!sourcePath) return;
      try {
        const payload = await this.apiPost('/api/template-unrecognized-delete', { path: sourcePath });
        this.templates = payload.templates || this.templates;
        this.templateGroups = payload.groups || this.templateGroups;
        this.templateAssetVersion = Date.now();
        if (this.flowUnrecognizedTemplate && (this.flowUnrecognizedTemplate.path || this.flowUnrecognizedTemplate.relative_path) === sourcePath) {
          this.flowUnrecognizedTemplate = null;
        }
        this.captureSourceTemplate = null;
        if ((this.capture.path || '') === sourcePath) {
          this.capture = {};
          this.capturePreviewUrlValue = '';
          this.captureRegion = null;
          this.clickCaptureRegion = null;
          this.clickCaptureRegions = [];
        }
      } catch (error) {
        this.notifyError(error);
      }
    },
    openTemplateCreateDrawer() {
      if (!this.capture.path) {
        this.$message.warning('请先按 F1 截图。');
        return;
      }
      if (!this.captureRegion) {
        this.$message.warning('请先按 F2 圈选识别区。');
        return;
      }
      this.selectedTemplate = null;
      this.templateEditorMode = 'create';
      this.templateEditor = this.defaultTemplateEditor();
      this.templateEditorVisible = true;
      this.screenshotHotkeyStatus = '正在保存新模板。';
    },
    compactTemplateAction(action) {
      const output = {};
      for (const [key, value] of Object.entries(action)) {
        if (value === '' || value === null || value === undefined) continue;
        if (typeof value === 'number' && !Number.isFinite(value)) continue;
        output[key] = value;
      }
      return output;
    },
    templateActionPayload(action = {}, fallbackType = 'click_match') {
      const type = action.type || fallbackType;
      if (type === 'none') return this.compactTemplateAction({
        type: 'none',
        delay_after_ms: Math.max(0, Number(action.delay_after_ms || 0)),
        note: action.note || '',
      });
      if (type === 'key') return this.compactTemplateAction({
        type: 'key',
        key: action.key || 'esc',
        duration_ms: Math.max(0, Number(action.duration_ms || 50)),
        delay_after_ms: Math.max(0, Number(action.delay_after_ms || 0)),
        loop_count: Math.max(1, Math.floor(Number(action.loop_count || 1))),
        note: action.note || '',
      });
      if (type === 'drag_match') return this.compactTemplateAction({
        type: 'drag_match',
        direction: action.direction || 'up',
        distance_percent: Math.max(1, Math.min(100, Number(action.distancePercent || action.distance_percent || 30))),
        duration_ms: Math.max(0, Number(action.duration_ms || 300)),
        delay_after_ms: Math.max(0, Number(action.delay_after_ms || 500)),
        note: action.note || '',
      });
      if (type === 'drag_point') return this.compactTemplateAction({
        type: 'drag_point',
        start_from: 'window_center',
        direction: action.direction || 'up',
        distance_percent: Math.max(1, Math.min(100, Number(action.distancePercent || action.distance_percent || 30))),
        duration_ms: Math.max(0, Number(action.duration_ms || 300)),
        delay_after_ms: Math.max(0, Number(action.delay_after_ms || 300)),
        note: action.note || '',
      });
      if (type === 'flow') return this.compactTemplateAction({ type: 'flow', flow: action.flow || action.name || '', note: action.note || '' });
      return this.compactTemplateAction({
        type: 'click_match',
        delay_after_ms: Math.max(0, Number(action.delay_after_ms || 500)),
        note: action.note || '',
      });
    },
    templateEditorMetadata(base = {}) {
      const metadata = { ...base };
      metadata.actions = [this.templateActionPayload(this.templateEditor.successAction, 'click_match')];
      delete metadata.not_found_actions;
      const matchThreshold = Number(this.templateEditor.threshold || 0.85);
      metadata.threshold = Number.isFinite(matchThreshold) && matchThreshold > 0 ? Math.min(1, matchThreshold) : 0.85;
      metadata.priority = Number.isFinite(Number(this.templateEditor.priority)) ? Number(this.templateEditor.priority) : 0;
      metadata.is_end_template = Boolean(this.templateEditor.isEndTemplate);
      metadata.is_success_template = Boolean(this.templateEditor.isSuccessTemplate);
      metadata.is_non_standalone = Boolean(this.templateEditor.isNonStandalone);
      metadata.is_fallback_template = Boolean(this.templateEditor.isFallbackTemplate);
      metadata.avoid_same_position = Boolean(this.templateEditor.avoidSamePosition);
      const groupMatchLimit = Number(this.templateEditor.groupMatchLimit || 0);
      if (Number.isFinite(groupMatchLimit) && groupMatchLimit >= 1) metadata.group_match_limit = Math.floor(groupMatchLimit);
      else delete metadata.group_match_limit;
      const postconditions = Array.isArray(this.templateEditor.postconditionTemplates) ? this.templateEditor.postconditionTemplates.map(value => String(value || '').trim()).filter(Boolean) : [];
      if (postconditions.length) metadata.postcondition_templates = postconditions;
      else delete metadata.postcondition_templates;
      const postconditionNots = Array.isArray(this.templateEditor.postconditionNotTemplates) ? this.templateEditor.postconditionNotTemplates.map(value => String(value || '').trim()).filter(Boolean) : [];
      if (postconditionNots.length) metadata.postcondition_not_templates = postconditionNots;
      else delete metadata.postcondition_not_templates;
      const postActionTemplate = String(this.templateEditor.postActionTemplate || '').trim();
      if (postActionTemplate) {
        metadata.post_action_template = postActionTemplate;
        const threshold = Number(this.templateEditor.postActionTemplateThreshold || 0);
        if (Number.isFinite(threshold) && threshold > 0) metadata.post_action_template_threshold = threshold;
        else delete metadata.post_action_template_threshold;
        metadata.post_action_template_delay_ms = Math.max(0, Math.floor(Number(this.templateEditor.postActionTemplateDelayMs || 0)));
      } else {
        delete metadata.post_action_template;
        delete metadata.post_action_template_threshold;
        delete metadata.post_action_template_delay_ms;
      }
      delete metadata.precondition_templates;
      delete metadata.precondition_template;
      delete metadata.requires_templates;
      delete metadata.requires_template;
      delete metadata.postcondition_template;
      delete metadata.postcondition_not_template;
      delete metadata.excludes_templates;
      delete metadata.excludes_template;
      delete metadata.non_standalone;
      delete metadata.fallback_template;
      delete metadata.not_match_same_position;
      delete metadata.next_template;
      delete metadata.next_template_threshold;
      delete metadata.next_template_delay_ms;
      return metadata;
    },
    clickRegionsForNewTemplate() {
      if (!this.captureRegion) return [];
      const regions = this.clickCaptureRegions.length ? this.clickCaptureRegions : [this.captureRegion];
      return regions.map(region => [
        Math.max(0, Math.round(region.left - this.captureRegion.left)),
        Math.max(0, Math.round(region.top - this.captureRegion.top)),
        Math.max(1, Math.round(region.width)),
        Math.max(1, Math.round(region.height)),
      ]);
    },
    async saveTemplateEditor() {
      this.templateEditorSaving = true;
      try {
        const nextName = (this.templateEditor.name || '').trim();
        if (!nextName) throw new Error('请输入模板名称。');

        if (this.templateEditorMode === 'create') {
          if (!this.capture.path || !this.captureRegion) throw new Error('请先截图并圈选识别区。');
          const group = this.selectedGroup && this.selectedGroup !== '__all__'
            ? (this.isSelectedUnrecognizedGroup ? this.selectedUnrecognizedParentGroup : this.selectedGroup)
            : '';
          const payload = await this.apiPost('/api/template-crop', {
            image_path: this.capture.path,
            region: this.captureRegion,
            filename: nextName,
            group: group || undefined,
            replace: true,
            click_regions: this.clickCaptureRegions.length ? this.clickCaptureRegions : [this.captureRegion],
            metadata: this.templateEditorMetadata({}),
          });
          await this.refreshTemplates();
          const savedPath = payload.template && (payload.template.relative_path || payload.template.path);
          this.selectedTemplate = this.templates.find(item => (item.relative_path || item.path) === savedPath) || payload.template || null;
          await this.deleteCaptureSourceTemplateIfUnrecognized();
          this.templateEditorVisible = false;
          this.lastAction = '保存新模板';
          this.$message.success('新模板已保存');
          return;
        }

        if (!this.selectedTemplate) return;
        let template = this.selectedTemplate;
        const originalName = this.templateName(template).replace(/\.png$/i, '');
        if (nextName !== originalName) {
          const renamePayload = await this.apiPost('/api/template-rename', {
            path: template.relative_path || template.path,
            filename: nextName,
            group: template.group || '',
          });
          template = renamePayload.template || template;
        }

        const saved = await this.apiPost('/api/template-metadata', {
          path: template.relative_path || template.path,
          metadata: this.templateEditorMetadata(template.metadata || {}),
        });
        await this.refreshTemplates();
        const savedPath = (saved.template && (saved.template.relative_path || saved.template.path)) || (template.relative_path || template.path);
        this.selectedTemplate = this.templates.find(item => (item.relative_path || item.path) === savedPath) || saved.template || template;
        this.templateEditorVisible = false;
        this.lastAction = '保存模板';
        this.$message.success('模板配置已保存');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.templateEditorSaving = false;
      }
    },
    async captureWindow() {
      this.captureLoading = true;
      try {
        const payload = await this.apiPost('/api/capture', this.captureForm);
        this.capture = payload.capture || {};
        this.windowInfo = payload.window || this.windowInfo;
        this.captureSourceTemplate = null;
        this.captureRegion = null;
        this.clickCaptureRegion = null;
        this.clickCaptureRegions = [];
        this.captureSelectionMode = '';
        this.capturePreviewUrlValue = this.capture.path ? this.imagePreviewUrl(this.capture.path) : '';
        this.screenshotHotkeyStatus = '截图完成。按 F2 圈选识别区，按 F3 圈选点击区，按 F4 保存模板。';
        this.lastAction = '截图';
        this.$message.success('截图完成');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.captureLoading = false;
      }
    },
    imagePreviewUrl(path) {
      return `/api/image-preview?path=${encodeURIComponent(path)}&t=${Date.now()}`;
    },
    handleTemplateHotkey(event) {
      if (this.activePage !== 'templates') return;
      if (['INPUT', 'TEXTAREA'].includes(event.target && event.target.tagName)) return;
      if (event.key === 'F1') {
        event.preventDefault();
        this.captureWindow();
      } else if (event.key === 'F2') {
        event.preventDefault();
        this.startCaptureRegionSelection();
      } else if (event.key === 'F3') {
        event.preventDefault();
        this.startClickRegionSelection();
      } else if (event.key === 'F4') {
        event.preventDefault();
        this.openTemplateCreateDrawer();
      } else if (event.key === 'F5') {
        event.preventDefault();
        this.recognizeSelectedTemplateAndRunAction();
      } else if (event.key === 'F6') {
        event.preventDefault();
        this.recognizeCurrentGroupAndRunTopAction();
      } else if (event.key === 'Backspace') {
        event.preventDefault();
        this.deleteSelectedTemplateImmediately();
      }
    },
    startCaptureRegionSelection() {
      if (!this.capture.path) {
        this.screenshotHotkeyStatus = '请先按 F1 截图。';
        this.$message.warning('请先按 F1 截图。');
        return;
      }
      this.captureSelectionMode = 'recognition';
      this.captureSelectionDrag = null;
      this.clickCaptureRegion = null;
      this.clickCaptureRegions = [];
      this.screenshotHotkeyStatus = '请在截图上拖拽圈选识别区。';
    },
    startClickRegionSelection() {
      if (!this.capture.path) {
        this.screenshotHotkeyStatus = '请先按 F1 截图。';
        this.$message.warning('请先按 F1 截图。');
        return;
      }
      if (!this.captureRegion) {
        this.screenshotHotkeyStatus = '请先按 F2 圈选识别区。';
        this.$message.warning('请先按 F2 圈选识别区。');
        return;
      }
      this.captureSelectionMode = 'click';
      this.captureSelectionDrag = null;
      this.clickCaptureRegion = null;
      this.screenshotHotkeyStatus = `请拖拽添加第 ${this.clickCaptureRegions.length + 1} 个点击区。`;
    },
    captureImagePoint(event) {
      const image = this.$refs.capturePreviewImage;
      if (!image) return null;
      const rect = image.getBoundingClientRect();
      const width = image.naturalWidth || image.clientWidth;
      const height = image.naturalHeight || image.clientHeight;
      const x = Math.round((event.clientX - rect.left) * width / image.clientWidth);
      const y = Math.round((event.clientY - rect.top) * height / image.clientHeight);
      return {
        x: Math.max(0, Math.min(width, x)),
        y: Math.max(0, Math.min(height, y)),
      };
    },
    rectFromPoints(start, end) {
      const left = Math.min(start.x, end.x);
      const top = Math.min(start.y, end.y);
      const right = Math.max(start.x, end.x);
      const bottom = Math.max(start.y, end.y);
      return { left, top, right, bottom, width: right - left, height: bottom - top };
    },
    beginCaptureSelection(event) {
      if (!this.captureSelectionMode) return;
      const point = this.captureImagePoint(event);
      if (!point) return;
      event.preventDefault();
      this.captureSelectionDrag = { mode: this.captureSelectionMode, start: point, end: point };
      const region = this.rectFromPoints(point, point);
      if (this.captureSelectionMode === 'recognition') this.captureRegion = region;
      else this.clickCaptureRegion = region;
    },
    updateCaptureSelectionDrag(event) {
      if (!this.captureSelectionDrag) return;
      const point = this.captureImagePoint(event);
      if (!point) return;
      this.captureSelectionDrag.end = point;
      const region = this.rectFromPoints(this.captureSelectionDrag.start, this.captureSelectionDrag.end);
      if (this.captureSelectionDrag.mode === 'recognition') this.captureRegion = region;
      else this.clickCaptureRegion = region;
    },
    finishCaptureSelection() {
      if (!this.captureSelectionDrag) return;
      const drag = this.captureSelectionDrag;
      this.captureSelectionDrag = null;
      this.captureSelectionMode = '';
      if (drag.mode === 'recognition') {
        this.screenshotHotkeyStatus = '识别区已记录。按 F3 可继续圈选点击区，按 F4 保存模板。';
      } else if (this.clickCaptureRegion) {
        const region = this.clickCaptureRegion;
        if (region.width > 0 && region.height > 0) {
          this.clickCaptureRegions.push(region);
          const spaceText = this.clickRegionCoordinateSpace(region) === 'template' ? '模板相对' : '窗口相对';
          this.screenshotHotkeyStatus = `已记录 ${this.clickCaptureRegions.length} 个点击区（${spaceText}）。按 F4 保存模板。`;
        } else {
          this.screenshotHotkeyStatus = `点击区过小，未记录。已记录 ${this.clickCaptureRegions.length} 个点击区。`;
        }
        this.clickCaptureRegion = null;
      }
    },
    clickRegionCoordinateSpace(region) {
      if (!this.captureRegion || !region) return 'window';
      return region.left >= this.captureRegion.left
        && region.top >= this.captureRegion.top
        && region.right <= this.captureRegion.right
        && region.bottom <= this.captureRegion.bottom
        ? 'template'
        : 'window';
    },
    updateCaptureOverlay() {
      const image = this.$refs.capturePreviewImage;
      if (!image) return;
      this.captureImageSize = { width: image.naturalWidth || 0, height: image.naturalHeight || 0 };
      const displaySize = this.imageDisplaySize(image.naturalWidth, image.naturalHeight);
      this.captureDisplaySize = displaySize;
      if (displaySize.width && displaySize.height) {
        image.style.width = `${displaySize.width}px`;
        image.style.height = `${displaySize.height}px`;
      }
    },
    regionBoxStyle(region) {
      const image = this.$refs.capturePreviewImage;
      if (!region || !image || !image.naturalWidth || !image.naturalHeight) return {};
      const scaleX = image.clientWidth / image.naturalWidth;
      const scaleY = image.clientHeight / image.naturalHeight;
      return {
        left: `${region.left * scaleX}px`,
        top: `${region.top * scaleY}px`,
        width: `${Math.max(1, region.width * scaleX)}px`,
        height: `${Math.max(1, region.height * scaleY)}px`,
      };
    },
    async recognizeSelectedTemplateAndRunAction() {
      if (!this.selectedTemplate) {
        this.$message.warning('请先选中一个模板。');
        return;
      }
      const templatePath = this.selectedTemplate.relative_path || this.selectedTemplate.path;
      try {
        this.screenshotHotkeyStatus = `正在识别并执行：${this.templateName(this.selectedTemplate)}`;
        const payload = await this.apiPost('/api/template-action', {
          template_path: templatePath,
          backend: this.captureForm.backend,
          bring_to_front: false,
        });
        this.capture = payload.capture || this.capture;
        this.capturePreviewUrlValue = this.capture.path ? this.imagePreviewUrl(this.capture.path) : this.capturePreviewUrlValue;
        const match = payload.match || {};
        if (payload.action_executed) {
          const point = payload.action && payload.action.last_match_click_point;
          const pointText = point ? `，点击=(${point.x},${point.y})` : '';
          this.screenshotHotkeyStatus = `F5 命中并已执行 action：score=${Number(match.score || 0).toFixed(4)}${pointText}`;
          this.$message.success('模板命中，action 已执行');
        } else {
          this.screenshotHotkeyStatus = `F5 未命中：score=${Number(match.score || 0).toFixed(4)}`;
          this.$message.warning('模板未命中，未执行 action');
        }
      } catch (error) {
        this.notifyError(error);
      }
    },
    async recognizeCurrentGroupAndRunTopAction() {
      if (!this.canEditSelectedTemplateGroup) {
        this.$message.warning('请先选择一个具体模板分组。');
        return;
      }
      try {
        this.screenshotHotkeyStatus = `正在识别分组：${this.selectedGroup}`;
        const payload = await this.apiPost('/api/template-group-action', {
          group: this.selectedGroup,
          backend: this.captureForm.backend,
          bring_to_front: false,
        });
        this.capture = payload.capture || this.capture;
        this.capturePreviewUrlValue = this.capture.path ? this.imagePreviewUrl(this.capture.path) : this.capturePreviewUrlValue;
        this.groupActionMatches = payload.matches || [];
        this.selectedGroupActionMatch = payload.selected_match || null;
        if (payload.action_executed && this.selectedGroupActionMatch) {
          const template = this.selectedGroupActionMatch.template || {};
          const point = payload.action && payload.action.last_match_click_point;
          const pointText = point ? `，点击=(${point.x},${point.y})` : '';
          this.screenshotHotkeyStatus = `F6 已执行：${this.templateName(template)} · 优先级 ${this.selectedGroupActionMatch.priority || 0} · score=${Number(this.selectedGroupActionMatch.score || 0).toFixed(4)}${pointText}`;
          this.$message.success('分组识别命中，已执行最高优先级 action');
        } else {
          this.screenshotHotkeyStatus = 'F6 未找到超过阈值的模板。';
          this.$message.warning('分组内没有模板超过匹配阈值');
        }
      } catch (error) {
        this.notifyError(error);
      }
    },
    async deleteSelectedTemplateImmediately() {
      if (!this.selectedTemplate) return;
      const templatePath = this.selectedTemplate.relative_path || this.selectedTemplate.path;
      try {
        await this.apiPost('/api/template-delete', { path: templatePath });
        const deletedName = this.templateName(this.selectedTemplate);
        this.selectedTemplate = null;
        this.templateEditorVisible = false;
        await this.refreshTemplates();
        this.lastAction = '删除模板';
        this.$message.success(`已删除模板：${deletedName}`);
      } catch (error) {
        this.notifyError(error);
      }
    },
    templatePreviewUrl(path) {
      return `/api/template-preview?path=${encodeURIComponent(path)}&v=${this.templateAssetVersion}`;
    },
    templateName(template) {
      const value = template.relative_path || template.path || '';
      return value.split(/[\\/]/).pop() || value || '(unknown)';
    },
    templatePriority(template) {
      const value = template && template.metadata ? Number(template.metadata.priority) : 0;
      return Number.isFinite(value) ? value : 0;
    },
    templateIsEnd(template) {
      return Boolean(template && template.metadata && template.metadata.is_end_template);
    },
    templateIsSuccess(template) {
      return Boolean(template && template.metadata && template.metadata.is_success_template);
    },
    templateIsNonStandalone(template) {
      const metadata = template && template.metadata ? template.metadata : {};
      return Boolean(metadata.is_non_standalone || metadata.non_standalone);
    },
    templateIsFallback(template) {
      const metadata = template && template.metadata ? template.metadata : {};
      return Boolean(metadata.is_fallback_template || metadata.fallback_template);
    },
    templateAvoidSamePosition(template) {
      const metadata = template && template.metadata ? template.metadata : {};
      return Boolean(metadata.avoid_same_position || metadata.not_match_same_position);
    },
    sortedTemplates(templates) {
      return [...(templates || [])].sort((left, right) => {
        const priority = this.templatePriority(left) - this.templatePriority(right);
        if (priority) return priority;
        const leftPath = left.relative_path || left.path || '';
        const rightPath = right.relative_path || right.path || '';
        return leftPath.localeCompare(rightPath);
      });
    },
    childTemplateGroupLabel(group) {
      const current = String(this.selectedGroup || '').replace(/\\/g, '/').replace(/\/$/, '');
      const name = String((group && group.name) || '').replace(/\\/g, '/');
      return current ? name.slice(current.length + 1) : name;
    },
    enterTemplateGroup(name) {
      this.selectedGroup = name || '';
      this.selectedTemplate = null;
    },
    flowDisplayName(filename) {
      return String(filename || '').replace(/\.(ya?ml)$/i, '');
    },
    flowLabel(flow) {
      if (typeof flow === 'string') return this.flowDisplayName(flow);
      return flow.id || this.flowDisplayName(flow.filename) || JSON.stringify(flow);
    },
    flowActualFilename(name) {
      const trimmed = String(name || '').trim();
      if (!trimmed) return '';
      return /\.(ya?ml)$/i.test(trimmed) ? trimmed : `${trimmed}.yaml`;
    },
    currentFlowFilename() {
      return this.selectedFlowFilename || this.flowActualFilename(this.flowDraft.filename);
    },
    flowDraftFilename() {
      const draftName = String(this.flowDraft.filename || '').trim();
      if (this.selectedFlowFilename && draftName === this.flowDisplayName(this.selectedFlowFilename)) {
        return this.selectedFlowFilename;
      }
      return this.flowActualFilename(draftName);
    },
    newFlowDraft() {
      this.selectedFlowFilename = '';
      this.isNewFlowDraft = true;
      this.flowFailureEntries = [];
      this.flowUnrecognizedTemplate = null;
      this.flowLastUnrecognizedPath = '';
      this.flowDraft = { filename: '', start: [], loopDir: [], completionCount: 1 };
    },
    async selectFlow(filename) {
      this.selectedFlowFilename = filename;
      this.isNewFlowDraft = false;
      this.flowFailureEntries = [];
      this.flowUnrecognizedTemplate = null;
      this.flowLastUnrecognizedPath = '';
      try {
        const payload = await this.apiGet(`/api/template-loop-flows/${encodeURIComponent(filename)}`);
        const flow = payload.flow || {};
        this.flowDraft = {
          filename: this.flowDisplayName(flow.filename || filename),
          start: flow.start_flows || flow.start || [],
          loopDir: flow.loop_dirs || flow.loopDir || [],
          completionCount: Math.max(1, Math.floor(Number(flow.completion_count || flow.completionCount || 1))),
        };
        await this.loadFlowFailures({ silent: true });
      } catch (error) {
        this.notifyError(error);
      }
    },
    async saveFlow() {
      if (!String(this.flowDraft.filename || '').trim()) {
        this.$message.warning('请填写流程文件名。');
        return null;
      }
      this.flowSaving = true;
      try {
        const payload = await this.apiPost('/api/template-loop-flows', this.flowDraftPayload());
        this.flows = payload.flows || this.flows;
        this.selectedFlowFilename = payload.flow && payload.flow.filename ? payload.flow.filename : this.flowActualFilename(this.flowDraft.filename);
        this.isNewFlowDraft = false;
        this.flowDraft.filename = this.flowDisplayName(this.selectedFlowFilename);
        this.lastAction = '保存流程';
        this.$message.success('流程已保存');
        return payload.flow;
      } catch (error) {
        this.notifyError(error);
        return null;
      } finally {
        this.flowSaving = false;
      }
    },
    async startFlow() {
      const flow = await this.saveFlow();
      if (!flow) return;
      this.flowStarting = true;
      try {
        const filename = flow.filename || this.currentFlowFilename();
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/start`, {
          dry_run: this.flowDryRun,
          background_mode: true,
          run_start_flows_first: !this.flowPreferLoopFirst,
        });
        this.flows = payload.flows || this.flows;
        this.lastAction = '启动流程';
        await this.loadFlowFailures({ silent: true });
        this.$message.success('流程已启动');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.flowStarting = false;
      }
    },
    async stopFlow() {
      const filename = this.currentFlowFilename();
      if (!filename) {
        this.$message.warning('请先选择流程。');
        return;
      }
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/stop`, { force: true });
        this.flows = payload.flows || this.flows;
        this.lastAction = '强杀停止流程';
        await this.loadFlowFailures({ silent: true });
        this.$message.success('流程已强杀停止');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async selectAndStartFlow(filename) {
      await this.selectFlow(filename);
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/start`, {
          dry_run: this.flowDryRun,
          background_mode: true,
          run_start_flows_first: !this.flowPreferLoopFirst,
        });
        this.flows = payload.flows || this.flows;
        this.$message.success('流程已启动');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async selectAndStopFlow(filename) {
      await this.selectFlow(filename);
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/stop`, { force: true });
        this.flows = payload.flows || this.flows;
        this.$message.success('流程已强杀停止');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async pauseFlow() {
      const filename = this.currentFlowFilename();
      if (!filename) { this.$message.warning('请先选择流程。'); return; }
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/pause`, {});
        this.flows = payload.flows || this.flows;
        this.$message.success('流程已暂停');
      } catch (error) { this.notifyError(error); }
    },
    async resumeFlow() {
      const filename = this.currentFlowFilename();
      if (!filename) { this.$message.warning('请先选择流程。'); return; }
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/resume`, {});
        this.flows = payload.flows || this.flows;
        this.$message.success('流程已继续');
      } catch (error) { this.notifyError(error); }
    },
    async selectAndPauseFlow(filename) {
      await this.selectFlow(filename);
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/pause`, {});
        this.flows = payload.flows || this.flows;
        this.$message.success('流程已暂停');
      } catch (error) { this.notifyError(error); }
    },
    async selectAndResumeFlow(filename) {
      await this.selectFlow(filename);
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/resume`, {});
        this.flows = payload.flows || this.flows;
        this.$message.success('流程已继续');
      } catch (error) { this.notifyError(error); }
    },
    async deleteFlow() {
      const filename = this.currentFlowFilename();
      if (!filename) {
        this.$message.warning('请先选择流程。');
        return;
      }
      try {
        await this.$confirm(`确定删除状态流程“${this.flowDisplayName(filename)}”吗？`, '删除确认', {
          confirmButtonText: '删除',
          cancelButtonText: '取消',
          type: 'warning',
        });
      } catch (_cancelled) {
        return;
      }
      this.flowDeleting = true;
      try {
        const payload = await this.apiDelete(`/api/template-loop-flows/${encodeURIComponent(filename)}`);
        this.flows = payload.flows || this.flows;
        this.newFlowDraft();
        this.lastAction = '删除流程';
        this.$message.success('流程已删除');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.flowDeleting = false;
      }
    },
    async loadFlowFailures({ silent = false, filename = '' } = {}) {
      const targetFilename = filename || this.currentFlowFilename();
      if (!targetFilename) {
        if (!silent) this.$message.warning('请先选择流程。');
        return null;
      }
      try {
        const payload = await this.apiGet(`/api/template-loop-flows/${encodeURIComponent(targetFilename)}/failures?limit=20`);
        this.flowFailureEntries = payload.failures || [];
        const nextUnrecognized = payload.latest_unrecognized_template || payload.unrecognized_template || null;
        const nextPath = nextUnrecognized ? (nextUnrecognized.relative_path || nextUnrecognized.path || '') : '';
        this.flowUnrecognizedTemplate = nextUnrecognized;
        if (nextPath && nextPath !== this.flowLastUnrecognizedPath) {
          this.flowLastUnrecognizedPath = nextPath;
          await this.refreshTemplates();
        }
        return payload;
      } catch (error) {
        if (!silent) this.notifyError(error);
        return null;
      }
    },
    async loadSchedulerFlowFailures({ silent = false } = {}) {
      const filename = this.schedulerFailureFilename;
      if (!filename) {
        if (!silent) this.$message.warning('当前没有可读取失败信息的调度流程。');
        return null;
      }
      return this.loadFlowFailures({ silent, filename });
    },
    flowDraftPayload() {
      return {
        filename: this.flowDraftFilename(),
        start_flows: this.flowDraft.start || [],
        loopDir: this.flowDraft.loopDir || [],
        completionCount: Math.max(1, Math.floor(Number(this.flowDraft.completionCount || 1))),
      };
    },
    loadSchedulerState() {
      try {
        const raw = localStorage.getItem('monster-job32.scheduler.v1');
        if (!raw) return;
        const saved = JSON.parse(raw);
        const scheduler = saved.scheduler || {};
        this.scheduler.startAt = scheduler.startAt || '';
        this.scheduler.dryRun = Boolean(scheduler.dryRun);
        this.scheduler.continueOnError = scheduler.continueOnError !== false;
        this.scheduler.status = ['scheduled', 'running', 'stopping'].includes(scheduler.status) ? 'stopped' : (scheduler.status || 'idle');
        this.scheduler.message = ['scheduled', 'running', 'stopping'].includes(scheduler.status) ? '上次调度未在当前页面内继续，已置为停止。' : (scheduler.message || '');
        this.schedulerDefaults = {
          repeatCount: Math.max(1, Math.floor(Number(saved.defaults && saved.defaults.repeatCount || 1))),
          retryCount: Math.max(0, Math.floor(Number(saved.defaults && saved.defaults.retryCount || 0))),
          weekdays: this.normalizeWeekdays(saved.defaults && saved.defaults.weekdays),
        };
        this.scheduleItems = (saved.items || []).map(this.normalizeScheduleItem).filter(item => item.filename);
        this.scheduleResults = (saved.results || []).slice(0, 200);
      } catch (error) {
        console.warn('load scheduler state failed', error);
      }
    },
    saveSchedulerState() {
      try {
        localStorage.setItem('monster-job32.scheduler.v1', JSON.stringify({
          scheduler: {
            status: this.scheduler.status,
            startAt: this.scheduler.startAt,
            dryRun: this.scheduler.dryRun,
            continueOnError: this.scheduler.continueOnError,
            message: this.scheduler.message,
          },
          defaults: this.schedulerDefaults,
          items: this.scheduleItems,
          results: this.scheduleResults.slice(0, 200),
        }));
      } catch (error) {
        console.warn('save scheduler state failed', error);
      }
    },
    async loadSchedulerConfig() {
      try {
        const result = await this.apiGet('/api/scheduler-config');
        if (!result || !result.ok || !result.config) return;
        const { config } = result;
        const scheduler = config.scheduler || {};
        if (scheduler.startAt !== undefined) this.scheduler.startAt = scheduler.startAt || '';
        if (scheduler.dryRun !== undefined) this.scheduler.dryRun = Boolean(scheduler.dryRun);
        if (scheduler.continueOnError !== undefined) this.scheduler.continueOnError = scheduler.continueOnError !== false;
        if (config.defaults) {
          this.schedulerDefaults = {
            repeatCount: Math.max(1, Math.floor(Number(config.defaults.repeatCount || 1))),
            retryCount: Math.max(0, Math.floor(Number(config.defaults.retryCount || 0))),
            weekdays: this.normalizeWeekdays(config.defaults.weekdays),
          };
        }
        if (Array.isArray(config.items)) {
          this.scheduleItems = config.items.map(this.normalizeScheduleItem).filter(item => item.filename);
        }
      } catch (error) {
        console.warn('load scheduler config from server failed', error);
      }
    },
    async saveSchedulerConfig() {
      try {
        await this.apiPost('/api/scheduler-config', {
          config: {
            scheduler: {
              startAt: this.scheduler.startAt,
              dryRun: this.scheduler.dryRun,
              continueOnError: this.scheduler.continueOnError,
            },
            defaults: this.schedulerDefaults,
            items: this.scheduleItems.map(item => ({
              filename: item.filename,
              repeatCount: item.repeatCount,
              retryCount: item.retryCount,
              weekdays: item.weekdays || [],
            })),
          },
        });
        this.$message({ message: '调度配置已保存', type: 'success', duration: 1500 });
      } catch (error) {
        this.$message({ message: `保存失败: ${error.message || error}`, type: 'error' });
      }
    },
    startSchedulerClock() {
      this.clearSchedulerClock();
      this.schedulerClockTimer = setInterval(() => {
        this.schedulerNow = Date.now();
      }, 1000);
    },
    clearSchedulerClock() {
      if (this.schedulerClockTimer) {
        clearInterval(this.schedulerClockTimer);
        this.schedulerClockTimer = null;
      }
    },
    normalizeScheduleItem(item = {}) {
      return {
        id: item.id || `schedule_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        filename: item.filename || '',
        repeatCount: Math.max(1, Math.floor(Number(item.repeatCount || 1))),
        retryCount: Math.max(0, Math.floor(Number(item.retryCount || 0))),
        weekdays: this.normalizeWeekdays(item.weekdays),
        completedRuns: Math.max(0, Math.floor(Number(item.completedRuns || 0))),
        failedRuns: Math.max(0, Math.floor(Number(item.failedRuns || 0))),
        skippedRuns: Math.max(0, Math.floor(Number(item.skippedRuns || 0))),
        status: item.status || 'pending',
        message: item.message || '',
      };
    },
    addScheduleFlows() {
      const selected = [...(this.schedulerFlowSelection || [])];
      if (!selected.length) {
        this.$message.warning('请先选择状态流程。');
        return;
      }
      const known = new Set(this.flows.map(flow => flow.filename));
      selected
        .filter(filename => known.has(filename))
        .forEach(filename => {
          this.scheduleItems.push(this.normalizeScheduleItem({
            filename,
            repeatCount: this.schedulerDefaults.repeatCount,
            retryCount: this.schedulerDefaults.retryCount,
            weekdays: this.schedulerDefaults.weekdays,
          }));
        });
      this.schedulerFlowSelection = [];
      this.saveSchedulerState();
    },
    moveScheduleItem(index, direction) {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= this.scheduleItems.length) return;
      const items = [...this.scheduleItems];
      const [item] = items.splice(index, 1);
      items.splice(nextIndex, 0, item);
      this.scheduleItems = items;
      this.saveSchedulerState();
    },
    removeScheduleItem(index) {
      this.scheduleItems.splice(index, 1);
      this.saveSchedulerState();
    },
    clearScheduleQueue() {
      this.scheduleItems = [];
      this.saveSchedulerState();
    },
    clearScheduleResults() {
      const count = this.scheduleResults.length;
      this.scheduleResults.splice(0, this.scheduleResults.length);
      this.scheduler.message = count ? `已清空 ${count} 条执行结果。` : '当前没有可清空的执行结果。';
      this.saveSchedulerState();
      this.$nextTick(() => {
        if (this.$refs.scheduleResultsTable) this.$refs.scheduleResultsTable.doLayout();
      });
      if (count) this.$message.success(`已清空 ${count} 条执行结果`);
    },
    scheduleItemStatusText(status) {
      const map = {
        pending: '待执行',
        running: '执行中',
        completed: '已完成',
        failed: '失败',
        stopped: '已停止',
        skipped: '已跳过',
      };
      return map[status] || status || '待执行';
    },
    scheduleItemStatusType(status) {
      const map = {
        running: 'success',
        completed: 'success',
        failed: 'danger',
        stopped: 'info',
        skipped: 'info',
      };
      return map[status] || 'info';
    },
    resultStatusText(status) {
      const map = {
        running: '执行中',
        completed: '完成',
        failed: '失败',
        stopped: '停止',
        retrying: '待重试',
        skipped: '跳过',
      };
      return map[status] || status || '-';
    },
    resultStatusType(status) {
      const map = {
        running: 'warning',
        completed: 'success',
        failed: 'danger',
        stopped: 'info',
        retrying: 'warning',
        skipped: 'info',
      };
      return map[status] || 'info';
    },
    normalizeWeekdays(value) {
      const values = Array.isArray(value) ? value : [];
      return [...new Set(values
        .map(item => Number(item))
        .filter(item => Number.isInteger(item) && item >= 0 && item <= 6))]
        .sort((left, right) => {
          const normalizedLeft = left === 0 ? 7 : left;
          const normalizedRight = right === 0 ? 7 : right;
          return normalizedLeft - normalizedRight;
        });
    },
    weekdayLabel(value) {
      const option = this.schedulerWeekdayOptions.find(item => item.value === Number(value));
      return option ? option.label : String(value);
    },
    scheduleWeekdayText(weekdays) {
      const normalized = this.normalizeWeekdays(weekdays);
      return normalized.length ? normalized.map(this.weekdayLabel).join('、') : '每天';
    },
    isScheduleItemAllowedToday(item, date = new Date()) {
      const weekdays = this.normalizeWeekdays(item && item.weekdays);
      return !weekdays.length || weekdays.includes(date.getDay());
    },
    compactDateTime(value) {
      if (!value) return '-';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      const pad = number => String(number).padStart(2, '0');
      return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    },
    durationText(startedAt, finishedAt) {
      const start = new Date(startedAt).getTime();
      const finish = new Date(finishedAt).getTime();
      if (!start || !finish || Number.isNaN(start) || Number.isNaN(finish)) return '';
      const seconds = Math.max(0, Math.round((finish - start) / 1000));
      const minutes = Math.floor(seconds / 60);
      return minutes ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`;
    },
    async startScheduler({ scheduled = false } = {}) {
      if (!this.scheduleItems.length) {
        this.$message.warning('请先把状态流程加入队列。');
        return;
      }
      const waitUntil = scheduled ? this.parseSchedulerStartAt() : null;
      if (scheduled && !waitUntil) {
        this.$message.warning('请先设置有效的开始时间。');
        return;
      }
      if (scheduled && waitUntil <= Date.now()) {
        this.$message.warning('定时启动的开始时间必须晚于当前时间。');
        return;
      }
      const token = this.schedulerRunToken + 1;
      this.schedulerRunToken = token;
      this.schedulerPaused = false;
      this.scheduleItems = this.scheduleItems.map(item => ({
        ...this.normalizeScheduleItem(item),
        completedRuns: 0,
        failedRuns: 0,
        skippedRuns: 0,
        status: 'pending',
        message: '',
      }));
      this.scheduler.currentFilename = '';
      this.scheduler.waitUntil = waitUntil;
      this.scheduler.status = scheduled ? 'scheduled' : 'running';
      this.scheduler.message = scheduled ? `等待开始时间：${this.scheduler.startAt}` : '手动启动，立即执行调度。';
      this.saveSchedulerState();
      try {
        await this.waitForSchedulerStart(token);
        if (!this.schedulerTokenActive(token)) return;
        this.scheduler.status = 'running';
        this.scheduler.message = '正在顺序执行队列。';
        this.saveSchedulerState();

        for (let itemIndex = 0; itemIndex < this.scheduleItems.length; itemIndex += 1) {
          if (!this.schedulerTokenActive(token)) return;
          const item = this.scheduleItems[itemIndex];
          if (!this.isScheduleItemAllowedToday(item)) {
            this.skipScheduleItemForWeekday(itemIndex);
            continue;
          }
          item.status = 'running';
          item.message = '执行中';
          this.$set(this.scheduleItems, itemIndex, { ...item });
          this.saveSchedulerState();
          const itemOk = await this.runScheduleItem(itemIndex, token);
          if (!itemOk && !this.scheduler.continueOnError) {
            this.scheduler.status = 'failed';
            this.scheduler.message = `流程 ${this.flowDisplayName(this.scheduleItems[itemIndex].filename)} 失败，调度已停止。`;
            this.saveSchedulerState();
            return;
          }
        }
        if (!this.schedulerTokenActive(token)) return;
        this.scheduler.status = 'completed';
        this.scheduler.currentFilename = '';
        this.scheduler.message = '调度队列已执行完成。';
        this.scheduler.waitUntil = null;
        this.saveSchedulerState();
        this.$message.success('流程调度已完成');
      } catch (error) {
        if (!this.schedulerTokenActive(token)) return;
        this.scheduler.status = 'failed';
        this.scheduler.message = error && error.message ? error.message : String(error);
        this.saveSchedulerState();
        this.notifyError(error);
      }
    },
    async waitForSchedulerStart(token) {
      const waitUntil = this.scheduler.waitUntil;
      if (!waitUntil || waitUntil <= Date.now()) return;
      while (this.schedulerTokenActive(token) && Date.now() < waitUntil) {
        this.schedulerNow = Date.now();
        await this.sleep(500);
      }
    },
    parseSchedulerStartAt() {
      if (!this.scheduler.startAt) return null;
      const timestamp = new Date(this.scheduler.startAt.replace(/-/g, '/')).getTime();
      return Number.isNaN(timestamp) ? null : timestamp;
    },
    schedulerTokenActive(token) {
      return this.schedulerRunToken === token && !['stopping', 'stopped'].includes(this.scheduler.status);
    },
    async runScheduleItem(itemIndex, token) {
      const item = this.scheduleItems[itemIndex];
      const totalRuns = Math.max(1, Math.floor(Number(item.repeatCount || 1)));
      const maxAttempts = Math.max(1, Math.floor(Number(item.retryCount || 0)) + 1);
      let itemOk = true;
      let itemStopped = false;
      for (let runNumber = 1; runNumber <= totalRuns; runNumber += 1) {
        let runOk = false;
        for (let attemptNumber = 1; attemptNumber <= maxAttempts; attemptNumber += 1) {
          await this.waitWhilePaused(token);
          if (!this.schedulerTokenActive(token)) return false;
          const result = this.createScheduleResult(item.filename, runNumber, totalRuns, attemptNumber, maxAttempts);
          this.scheduleResults.unshift(result);
          this.scheduler.currentFilename = item.filename;
          this.scheduler.message = `执行 ${this.flowDisplayName(item.filename)}：第 ${runNumber}/${totalRuns} 次，尝试 ${attemptNumber}/${maxAttempts}。`;
          this.saveSchedulerState();
          try {
            const finalFlow = await this.startAndWaitScheduleFlow(item.filename, token, result);
            const finishedAt = new Date().toISOString();
            await this.loadFlowFailures({ silent: true, filename: item.filename });
            const normalEnd = finalFlow.status === 'completed' && Number(finalFlow.exit_code || 0) === 0;
            Object.assign(result, {
              status: normalEnd ? 'completed' : (finalFlow.status || 'failed'),
              normalEnd,
              exitCode: finalFlow.exit_code,
              finishedAt,
              durationText: this.durationText(result.startedAt, finishedAt),
              message: this.flowStatusMessage(finalFlow),
            });
          } catch (error) {
            const finishedAt = new Date().toISOString();
            Object.assign(result, {
              status: this.scheduler.status === 'stopping' ? 'stopped' : 'failed',
              normalEnd: false,
              finishedAt,
              durationText: this.durationText(result.startedAt, finishedAt),
              message: error && error.message ? error.message : String(error),
            });
          }
          this.scheduleResults = [...this.scheduleResults];
          this.saveSchedulerState();
          if (result.normalEnd) {
            runOk = true;
            break;
          }
          if (result.status === 'stopped') {
            itemStopped = true;
            break;
          }
          if (attemptNumber < maxAttempts && this.schedulerTokenActive(token)) {
            result.status = 'retrying';
            result.message = `${result.message || '执行失败'}；准备重试。`;
            this.scheduleResults = [...this.scheduleResults];
            this.saveSchedulerState();
            await this.sleep(1000);
          }
        }
        const current = this.scheduleItems[itemIndex];
        if (runOk) current.completedRuns = Math.max(0, Number(current.completedRuns || 0)) + 1;
        else if (itemStopped) {
          current.failedRuns = Math.max(0, Number(current.failedRuns || 0)) + 1;
          itemOk = false;
        }
        else {
          current.failedRuns = Math.max(0, Number(current.failedRuns || 0)) + 1;
          itemOk = false;
        }
        current.status = itemStopped ? 'stopped' : (itemOk ? (runNumber >= totalRuns ? 'completed' : 'running') : 'failed');
        current.message = runOk ? '正常结束' : (itemStopped ? '任务已手动终止' : '重试用尽后失败');
        this.$set(this.scheduleItems, itemIndex, { ...current });
        this.saveSchedulerState();
        if (!runOk || itemStopped) break;
      }
      return itemOk;
    },
    skipScheduleItemForWeekday(itemIndex) {
      const item = this.scheduleItems[itemIndex];
      const totalRuns = Math.max(1, Math.floor(Number(item.repeatCount || 1)));
      const now = new Date();
      const today = this.weekdayLabel(now.getDay());
      const allowed = this.scheduleWeekdayText(item.weekdays);
      const message = `今天是${today}，该流程仅在${allowed}执行。`;
      const skippedAt = now.toISOString();
      const result = {
        id: `result_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        filename: item.filename,
        runNumber: 0,
        totalRuns,
        attemptNumber: 0,
        maxAttempts: Math.max(1, Math.floor(Number(item.retryCount || 0)) + 1),
        status: 'skipped',
        normalEnd: false,
        exitCode: null,
        startedAt: skippedAt,
        finishedAt: skippedAt,
        durationText: '-',
        message,
      };
      this.scheduleResults.unshift(result);
      item.skippedRuns = totalRuns;
      item.status = 'skipped';
      item.message = message;
      this.$set(this.scheduleItems, itemIndex, { ...item });
      this.scheduler.message = `跳过 ${this.flowDisplayName(item.filename)}：${message}`;
      this.saveSchedulerState();
    },
    createScheduleResult(filename, runNumber, totalRuns, attemptNumber, maxAttempts) {
      return {
        id: `result_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        filename,
        runNumber,
        totalRuns,
        attemptNumber,
        maxAttempts,
        status: 'running',
        normalEnd: false,
        exitCode: null,
        startedAt: new Date().toISOString(),
        finishedAt: '',
        durationText: '',
        message: '执行中',
      };
    },
    async refreshScheduleFlowProgress(filename, flow = {}, result = null) {
      const message = this.flowStatusMessage(flow) || '执行中';
      if (result && !this.isTerminalFlowStatus(result.status)) {
        Object.assign(result, {
          message,
          exitCode: flow.exit_code,
        });
        this.scheduleResults = [...this.scheduleResults];
      }
      if (this.scheduler.currentFilename === filename && this.scheduler.status === 'running') {
        this.scheduler.message = `执行 ${this.flowDisplayName(filename)}：${message}`;
      }
      this.saveSchedulerState();
      return { failures: this.flowFailureEntries };
    },
    async startAndWaitScheduleFlow(filename, token, result = null) {
      const startPayload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/start`, {
        dry_run: this.scheduler.dryRun,
        background_mode: true,
        run_start_flows_first: true,
      });
      this.flows = startPayload.flows || this.flows;
      let flow = startPayload.flow || {};
      while (this.schedulerTokenActive(token)) {
        if (this.schedulerPaused) { await this.sleep(300); continue; }
        if (this.isTerminalFlowStatus(flow.status)) return flow;
        await this.refreshScheduleFlowProgress(filename, flow, result);
        await this.sleep(1000);
        const payload = await this.apiGet('/api/template-loop-flows');
        this.flows = payload.flows || this.flows;
        flow = (this.flows || []).find(item => item.filename === filename) || flow;
        if (this.isTerminalFlowStatus(flow.status)) return flow;
      }
      throw new Error('调度已停止。');
    },
    async terminateCurrentScheduleTask() {
      const filename = this.currentSchedulerFilename;
      const index = this.scheduleItems.findIndex(item => item.status === 'running' && item.filename === filename);
      if (index >= 0) {
        await this.terminateScheduleTask(index);
        return;
      }
      if (!filename) {
        this.$message.warning('当前没有正在执行的任务。');
        return;
      }
      this.schedulerTerminatingTask = true;
      this.scheduler.currentFilename = filename;
      this.scheduler.message = `正在终止 ${this.flowDisplayName(filename)}。`;
      this.saveSchedulerState();
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/stop`, { force: true });
        this.flows = payload.flows || this.flows;
        this.$message.success('已发送终止任务请求');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.schedulerTerminatingTask = false;
      }
    },
    async terminateScheduleTask(itemIndex) {
      const item = this.scheduleItems[itemIndex];
      const filename = item && item.filename ? item.filename : this.scheduler.currentFilename;
      if (!filename || item.status !== 'running') {
        this.$message.warning('当前行没有正在执行的任务。');
        return;
      }
      this.schedulerTerminatingTask = true;
      this.scheduler.message = `正在终止 ${this.flowDisplayName(filename)}。`;
      this.saveSchedulerState();
      try {
        const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/stop`, { force: true });
        this.flows = payload.flows || this.flows;
        this.$message.success('已发送终止任务请求');
      } catch (error) {
        this.notifyError(error);
      } finally {
        this.schedulerTerminatingTask = false;
      }
    },
    isTerminalFlowStatus(status) {
      return ['completed', 'failed', 'stopped'].includes(status);
    },
    flowFailureKey(entry, index = 0) {
      return [entry.timestamp, entry.kind, entry.round, entry.message, index].filter(value => value !== undefined && value !== '').join('|');
    },
    flowStatusMessage(flow = {}) {
      return flow.process_message || flow.message || flow.status || '';
    },
    async stopScheduler() {
      this.schedulerRunToken += 1;
      this.schedulerPaused = false;
      this.scheduler.status = 'stopping';
      this.scheduler.message = '正在强杀调度中的状态流程。';
      this.saveSchedulerState();
      try {
        const payload = await this.apiPost('/api/template-loop-flows/stop-all', { force: true });
        this.flows = payload.flows || this.flows;
      } catch (error) {
        this.notifyError(error);
      }
      this.scheduleItems = this.scheduleItems.map(item => ['pending', 'running'].includes(item.status) ? { ...item, status: 'stopped', message: '调度强杀停止' } : item);
      const stoppedAt = new Date().toISOString();
      this.scheduleResults = this.scheduleResults.map(result => ['running', 'retrying'].includes(result.status) ? {
        ...result,
        status: 'stopped',
        finishedAt: stoppedAt,
        durationText: this.durationText(result.startedAt, stoppedAt),
        normalEnd: false,
        message: '调度强杀停止',
      } : result);
      this.scheduler.status = 'stopped';
      this.scheduler.currentFilename = '';
      this.scheduler.waitUntil = null;
      this.scheduler.message = '调度已强杀停止。';
      this.saveSchedulerState();
    },
    sleep(ms) {
      return new Promise(resolve => setTimeout(resolve, ms));
    },
    async waitWhilePaused(token) {
      while (this.schedulerPaused && this.schedulerTokenActive(token)) {
        await this.sleep(300);
      }
    },
    async pauseScheduler() {
      this.schedulerPaused = true;
      this.scheduler.message = '调度已暂停。';
      this.saveSchedulerState();
      const filename = this.currentSchedulerFilename;
      if (filename) {
        try {
          const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/pause`);
          this.flows = payload.flows || this.flows;
        } catch (error) {
          this.notifyError(error);
        }
      }
    },
    async resumeScheduler() {
      const filename = this.currentSchedulerFilename;
      if (filename) {
        try {
          const payload = await this.apiPost(`/api/template-loop-flows/${encodeURIComponent(filename)}/resume`);
          this.flows = payload.flows || this.flows;
        } catch (error) {
          this.notifyError(error);
        }
      }
      this.schedulerPaused = false;
      this.scheduler.message = '调度已恢复。';
      this.saveSchedulerState();
    },
    async findWindow() {
      try {
        const payload = await this.apiPost('/api/window/find', this.windowFind);
        this.windowInfo = payload.window || null;
        this.$message.success('已找到窗口');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async focusWindow() {
      try {
        const payload = await this.apiPost('/api/window/focus', {});
        this.windowInfo = payload.window || this.windowInfo;
        this.$message.success('已激活窗口');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async setTopmost(enabled) {
      try {
        const payload = await this.apiPost('/api/window/topmost', { enabled });
        this.windowInfo = payload.window || this.windowInfo;
        this.$message.success(enabled ? '已置顶' : '已取消置顶');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async toggleFullscreen() {
      try {
        const payload = await this.apiPost('/api/window/fullscreen', {});
        this.windowInfo = payload.window || this.windowInfo;
        this.$message.success(payload.fullscreen ? '已切换到全屏' : '已退出全屏');
      } catch (error) {
        this.notifyError(error);
      }
    },
    async rememberWindowSize() {
      try {
        const payload = await this.apiPost('/api/window/remember-size', {});
        this.windowInfo = payload.window || this.windowInfo;
        const size = payload.window_size;
        this.$message.success(size ? `已记录窗口大小 ${size.width}×${size.height}` : '已记录窗口大小');
      } catch (error) {
        this.notifyError(error);
      }
    },
    notifyError(error) {
      const message = error && error.message ? error.message : String(error);
      this.$message.error(message);
      console.error(error);
    },
  },
};
</script>
