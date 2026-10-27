<script setup>
import {computed} from 'vue';
import Icon from './Icon.vue';
import MemoryEditor from './MemoryEditor.vue';
import TimelineRecords from './TimelineRecords.vue';
import TaskRounds from './TaskRounds.vue';
import CronPanel from './CronPanel.vue';
import GoalPanel from './GoalPanel.vue';
import ExperiencePanel from './ExperiencePanel.vue';
import PreviewPanel from './PreviewPanel.vue';
import {fileUrl,formatSize,imageFile} from '../lib/api.js';
const props=defineProps({work:Object,collapsed:Boolean,mobile:Boolean});
defineEmits(['close']);
const metrics=computed(()=>[['历史消息',`${props.work.s.historyCount} 条`],['上下文软预算',`${(props.work.s.status?.context_chars||0).toLocaleString()} 字符`],['整理次数',`${props.work.s.events.filter(event=>event.type==='context_compact').length} 次`],['最近请求大小',props.work.compact.value?`${props.work.compact.value.after_chars.toLocaleString()} 字符（不含系统提示）`:'尚未触发整理']]);
function download(){const link=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify({session:props.work.s.session,events:props.work.s.events},null,2)],{type:'application/json'}));link.href=url;link.download=`ecoder-${props.work.s.session||'session'}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
</script>
<template><aside id="inspector" class="inspector" :class="{collapsed,'mobile-open':mobile}">
<div class="inspector-heading"><strong><Icon name="panel"/>执行面板</strong><span class="badge">{{work.s.runLabel}}</span><button class="inspector-close quiet" aria-label="关闭执行面板" @click="$emit('close')"><Icon name="plus"/></button></div>
<div class="inspector-tabs" role="tablist"><button v-for="[tab,label] in [['timeline','执行记录'],['goal','目标管理'],['experiences','经验总结'],['preview','界面预览'],['tasks','任务管理'],['crons','定时任务'],['files','文件管理'],['context','会话记忆']]" :key="tab" role="tab" :aria-selected="work.s.tab===tab" :class="{active:work.s.tab===tab}" @click="work.s.tab=tab">{{label}}</button></div>

<section v-show="work.s.tab==='timeline'" class="inspector-tab timeline-tab"><div class="session-usage" aria-label="本会话调用与 Token 汇总"><div class="usage-line"><span>本会话模型调用</span><strong>{{work.s.usage.calls.toLocaleString()}} 次</strong></div><div class="usage-line usage-tokens"><span>累计 Token 用量</span><strong>{{work.s.usage.reported?`${work.s.usage.tokens.toLocaleString()} tokens`:'—'}}</strong></div></div><div class="section-note">按轮次汇总，展开查看工具调用与执行结果。</div><TimelineRecords :runs="work.s.runs"/></section>
<section v-show="work.s.tab==='crons'" class="inspector-tab"><CronPanel :work="work"/></section>
<section v-if="work.s.tab==='experiences'" class="inspector-tab"><ExperiencePanel :work="work" view="summary"/></section>
<section v-if="work.s.tab==='preview'" class="inspector-tab"><PreviewPanel :work="work"/></section>
<section v-show="work.s.tab==='goal'" class="inspector-tab"><GoalPanel :work="work"/></section>
<section v-if="work.s.tab==='tasks'" class="inspector-tab"><TaskRounds :work="work"/></section>
<section v-show="work.s.tab==='files'" class="inspector-tab"><div class="section-note">选择文件夹后按层浏览本地目录，Agent 按需读取内容。未选择时使用默认目录或上传文件目录。</div><div class="files-storage-link"><button class="quiet" @click="work.s.page='storage'">管理存储<Icon name="storage"/></button></div><button v-if="work.s.fileDirectory" class="quiet" @click="work.safe(()=>work.refreshFiles(work.s.fileDirectory.split('/').slice(0,-1).join('/')))">← 上一级</button><div v-if="!work.s.files.length" class="empty-state">当前目录暂无文件。可直接开始任务，上传图片或文件，或连接本地文件夹。</div><template v-for="file in work.s.files" :key="file.id||file.path"><button v-if="file.directory" class="workspace-file directory-entry" @click="work.safe(()=>work.refreshFiles(file.path))"><Icon name="folder"/><span>{{file.path.split('/').at(-1)}}</span><span class="directory-arrow">›</span></button><div v-else class="workspace-file"><div class="workspace-file-info"><Icon :name="imageFile(file)?'image':'paperclip'"/><div><span class="file-path">{{file.path}}</span><small>{{file.attachment?'会话附件 · ':''}}{{formatSize(file.size)}}</small></div></div><div class="file-actions"><button class="quiet" :aria-label="`添加到消息：${file.path}`" :disabled="work.busy.value" @click="work.addFile(file)"><Icon name="plus"/></button><a class="quiet" :href="fileUrl(work.s.session,file)" :download="file.path.split('/').at(-1)" :aria-label="`下载：${file.path}`"><Icon name="download"/></a></div></div></template><p v-if="work.s.filesTruncated" class="section-note">仅显示前 2000 个文件。</p></section>
<section v-show="work.s.tab==='context'" class="inspector-tab"><div class="section-note">完整历史持久保存，仅裁剪发给模型的副本。</div><div v-for="[label,value] in metrics" :key="label" class="metric"><span>{{label}}</span><strong>{{value}}</strong></div><MemoryEditor :work="work"/></section>
<div class="inspector-footer"><span>{{work.s.runs.length}} 轮执行记录</span><button class="quiet" title="导出完整原始事件记录" @click="download">导出记录<Icon name="download"/></button></div>
</aside></template>



