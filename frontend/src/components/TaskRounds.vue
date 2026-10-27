<script setup>
import {computed,toRaw} from 'vue';
import {groupTaskRounds} from '../lib/taskRounds.js';
import {taskTime} from '../lib/experienceRuns.js';
const props=defineProps({work:Object});
const groups=computed(()=>{
 // Rebuild on run/task changes, without replaying history for every text token.
 void props.work.s.runs;void props.work.s.session;
 return groupTaskRounds(toRaw(props.work.s.events||[]),props.work.s.tasks||[]);
});
const activeId=computed(()=>props.work.s.running===false?null:groups.value.filter(group=>group.status==='running').at(-1)?.id||null);
const statuses={running:'执行中',completed:'已结束',failed:'失败',cancelled:'已停止',limit_reached:'达到上限',interrupted:'已中断'};
const taskStates={pending:'待开始',in_progress:'进行中',completed:'已完成'};
const actions={created:'本轮创建',updated:'本轮更新',viewed:'本轮查看',recorded:'历史记录'};
</script>
<template><div class="task-rounds"><p v-if="!groups.length" class="empty-state">开始对话后，这里会按每轮用户与 Agent 的交互显示任务。</p><details v-for="group in groups" :key="`${activeId||'idle'}:${group.id}`" class="task-round" :open="group.id===activeId"><summary><div class="task-round-heading"><strong>{{group.index===null?'历史任务':`第${group.index}轮`}}</strong><span>{{statuses[group.status]||'记录'}}</span></div><p class="task-round-prompt" :title="group.prompt">{{group.prompt||'本轮未记录用户需求'}}</p><small>{{group.tasks.length}} 个任务<template v-if="group.time"> · {{taskTime(group.time)}}</template></small></summary><div class="task-round-body"><p v-if="!group.tasks.length" class="empty-state">这一轮没有创建、更新或查看任务。</p><div v-for="task in group.tasks" :key="task.id" class="task-item" :class="task.status"><div class="task-title">{{task.status==='completed'?'✓':task.status==='in_progress'?'◉':'○'}} {{task.title}}</div><small>{{actions[task.action]}} · {{taskStates[task.status]||task.status}}</small><div v-if="task.dependencyTitles.length" class="task-dependency">依赖：{{task.dependencyTitles.join('、')}}</div></div></div></details></div></template>
<style scoped>.task-rounds{display:grid;gap:8px}.task-round{border:1px solid #dfe5f1;border-radius:9px;background:#fff;overflow:hidden}.task-round>summary{padding:8px 10px;cursor:pointer;list-style:none}.task-round>summary::-webkit-details-marker{display:none}.task-round-heading{display:flex;justify-content:space-between;align-items:center;gap:10px}.task-round-heading strong{line-height:1.35;font-size:13px;color:#455574}.task-round-heading span,.task-round summary small{font-size:11px;color:#7a879e}.task-round-prompt{margin:3px 0;line-height:1.4;font-size:12px;color:#667085;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}.task-round-body{border-top:1px solid #edf0f6;padding:10px}.task-round-body .task-item{padding:10px;margin-bottom:8px}.task-round-body .task-item:last-child{margin-bottom:0}.task-round-body .empty-state{margin:0;padding:12px;font-size:12px}.task-round summary:focus-visible{outline:2px solid #6571dd;outline-offset:-2px}.task-round summary small{display:block;line-height:1.35}</style>
