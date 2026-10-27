<script setup>
import {computed,ref,watch} from 'vue';
import {taskTime,shortPrompt} from '../lib/experienceRuns.js';
const props=defineProps({work:Object});
const condition=computed({get:()=>props.work.s.goalDraft||'',set:value=>props.work.s.goalDraft=value});
const selected=ref('');
const goals=computed(()=>{
  const snapshots=new Map();
  for(const event of props.work.s.events||[]){if(event.type==='goal_status'&&event.goal?.id)snapshots.set(event.goal.id,{...event.goal});}
  if(props.work.s.goal?.id)snapshots.set(props.work.s.goal.id,{...props.work.s.goal});
  return [...snapshots.values()].sort((a,b)=>(b.started_at||b.updated_at||0)-(a.started_at||a.updated_at||0));
});
const goal=computed(()=>goals.value.find(item=>item.id===selected.value)||null);
const isCurrent=computed(()=>!!goal.value&&goal.value.id===props.work.s.goal?.id);
function displayStatus(item){return item.id!==props.work.s.goal?.id&&item.status==='active'?'replaced':item.status;}
watch(()=>props.work.s.session,()=>{selected.value='';});
watch(()=>props.work.s.goal?.id,id=>{if(id)selected.value=id;},{immediate:true});
watch(goals,items=>{if(!items.some(item=>item.id===selected.value))selected.value=props.work.s.goal?.id||items[0]?.id||'';},{immediate:true});
const terminal=computed(()=>!goal.value||['achieved','impossible','cancelled'].includes(goal.value.status));
const labels={replaced:'已替换',active:'执行中',paused:'已暂停',achieved:'已达成',impossible:'无法完成',limit_reached:'达到上限，未完成',evaluation_failed:'判断失败，待处理',interrupted:'已中断，待恢复',cancelled:'已清除'};
</script>
<template><div class="goal-panel">

<form class="goal-form" @submit.prevent="work.safe(()=>work.startGoal(condition))">
  <p class="section-note">选中输入框的 Goal 后直接发送。验收条件选填，留空则以本次消息为目标。</p>
  <label>目标与验收条件<textarea id="goal-condition" v-model="condition" required maxlength="4000" rows="4" aria-label="Goal 验收条件" placeholder="例如：修复登录模块，直到 pytest tests/auth 退出码为 0，且不修改测试文件。"></textarea></label>
  <button class="secondary" type="submit" :disabled="work.busy.value||!condition.trim()">设置目标并开始</button>
</form>
<label v-if="goals.length" class="goal-history-label">本会话目标（{{goals.length}}）<select v-model="selected" aria-label="选择会话目标" :title="goal?.condition||'选择会话目标'"><option v-for="item in goals" :key="item.id" :value="item.id" :title="item.condition">{{labels[displayStatus(item)]||item.status}} · {{shortPrompt(item.condition)||'未命名目标'}} · {{taskTime(item.started_at||item.updated_at).replace(/:\d{2}$/,'')}}</option></select></label>
<div v-if="goal" class="goal-state" :class="displayStatus(goal)">
  <strong>{{labels[displayStatus(goal)]||goal.status}}<small class="goal-current-tag">{{isCurrent?'当前目标':'历史目标 · 仅查看'}}</small></strong><p>{{goal.condition}}</p>
  <small>已判断 {{goal.evaluations}} 次 · 主 Agent {{goal.agent_calls}} 次 · 判断器 {{goal.judge_calls}} 次</small>
  <small>已报告 Token：{{goal.reported_calls?(goal.agent_tokens+goal.judge_tokens).toLocaleString():'尚未提供'}}<template v-if="goal.reported_calls">（含子 Agent 和判断器）</template></small>
  <p v-if="goal.reason" class="goal-reason">{{goal.reason}}</p>
  <div class="goal-actions">
    <button v-if="isCurrent&&!terminal&&goal.status==='active'&&work.s.running" class="quiet" :disabled="work.s.goalBusy" @click="work.safe(()=>work.controlGoal('pause'))">暂停目标</button>
    <button v-if="isCurrent&&!terminal&&!work.s.running" class="secondary" :disabled="work.busy.value" @click="work.safe(()=>work.controlGoal('resume'))">恢复执行</button>
    <button v-if="isCurrent&&!terminal" class="quiet" :disabled="work.s.goalBusy" @click="work.safe(()=>work.controlGoal('clear'))">清除目标</button>
    <button class="quiet" @click="work.safe(()=>work.refreshGoal())">刷新</button>
  </div>
</div><p v-else class="empty-state">尚未设置目标。也可在对话中输入 /goal 验收条件。</p>
<p class="section-note">本次最多 {{work.s.status?.max_steps||40}} 个主循环步骤，连续未达标上限 {{work.s.status?.goal_block_cap||8}} 次。达到上限保留目标，由你决定是否恢复。</p>
</div></template>
<style scoped>
.goal-panel .section-note{margin:0;font-size:11px;line-height:1.5}.goal-panel .goal-form{gap:8px}
.goal-history-label{min-width:0;max-width:100%;display:flex;flex-direction:column;gap:7px;font-size:13px}.goal-history-label select{box-sizing:border-box;max-width:100%;width:100%;min-width:0;padding:10px;border:1px solid #d8dce4;border-radius:8px;background:#fff;color:inherit;font:inherit;text-overflow:ellipsis}.goal-current-tag{display:block;margin-top:5px;font-weight:400}.goal-panel,.goal-form,.goal-state{min-width:0;display:flex;flex-direction:column;gap:12px}.goal-form label{display:flex;flex-direction:column;gap:7px;font-size:13px}.goal-form textarea{width:100%;box-sizing:border-box;resize:vertical;padding:9px;border:1px solid #d8dce4;border-radius:8px;background:#fff;font:inherit;color:inherit}.goal-state{padding:13px;border:1px solid #e3e7ef;border-radius:10px;overflow-wrap:anywhere}.goal-state p{margin:0;white-space:pre-wrap;font-size:13px;line-height:1.6}.goal-state small{font-size:11px;color:#667085}.goal-state.achieved{border-color:#87cbb4}.goal-actions{display:flex;flex-wrap:wrap;gap:9px}.goal-reason{color:#667085}
</style>
