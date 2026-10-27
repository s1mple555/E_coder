<script setup>
import {taskTime} from '../lib/experienceRuns.js';
import {pretty} from '../lib/api.js';
defineProps({task:Object});
</script>
<template><div class="task-evidence"><div class="task-meta">{{taskTime(task.time)}}（北京时间） · {{task.tools.length}} 次工具调用</div><dl><dt>原始需求</dt><dd class="task-copy">{{task.prompt||'这条历史记录没有保留原始需求。'}}</dd><dt>最终回复</dt><dd class="task-copy">{{task.answer||'这条记录没有文字结论，请核对下方工具证据。'}}</dd></dl><details v-if="task.tools.length"><summary>查看工具证据（{{task.successTools}} 次成功）</summary><div v-for="(tool,index) in task.tools" :key="index" class="task-tool"><strong>{{tool.name}} · {{tool.ok?'成功':'失败 / 拒绝'}}</strong><pre>{{pretty(tool.result).slice(0,3000)}}</pre></div></details><p v-else class="task-meta">没有工具证据，无法从此任务生成方案。请先执行并验证任务。</p></div></template>
<style scoped>.task-evidence{font-size:12px;min-width:0}.task-meta{color:#667085;line-height:1.6}.task-evidence dl{margin:12px 0}.task-evidence dt{font-weight:600;margin-top:12px;color:#344054}.task-evidence dd{margin:5px 0 0}.task-copy{white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto;line-height:1.7}.task-evidence details{margin-top:10px}.task-evidence summary{cursor:pointer;color:#5966b3}.task-tool{padding:10px 0;border-bottom:1px solid #e9edf5}.task-tool pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto;font-size:11px}</style>
