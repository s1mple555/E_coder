<script setup>
import {computed,ref} from 'vue';
const props=defineProps({work:Object});
const condition=ref('');
const goal=computed(()=>props.work.s.goal);
const terminal=computed(()=>!goal.value||['achieved','impossible','cancelled'].includes(goal.value.status));
const labels={active:'执行中',paused:'已暂停',achieved:'已达成',impossible:'无法完成',limit_reached:'达到上限，未完成',evaluation_failed:'判断失败，待处理',interrupted:'已中断，待恢复',cancelled:'已清除'};
</script>
<template><div class="goal-panel">
<p class="section-note">独立判断器检查实际证据，未达标则继续。文件修改与命令仍需审批。</p>
<form class="goal-form" @submit.prevent="work.safe(()=>work.startGoal(condition))">
  <label>目标与验收条件<textarea v-model="condition" required maxlength="4000" rows="4" aria-label="Goal 验收条件" placeholder="例如：修复登录模块，直到 pytest tests/auth 退出码为 0，且不修改测试文件。"></textarea></label>
  <button class="secondary" type="submit" :disabled="work.busy.value||!condition.trim()">设置目标并开始</button>
</form>
<div v-if="goal" class="goal-state" :class="goal.status">
  <strong>{{labels[goal.status]||goal.status}}</strong><p>{{goal.condition}}</p>
  <small>已判断 {{goal.evaluations}} 次 · 主 Agent {{goal.agent_calls}} 次 · 判断器 {{goal.judge_calls}} 次</small>
  <small>已报告 Token：{{goal.reported_calls?(goal.agent_tokens+goal.judge_tokens).toLocaleString():'尚未提供'}}<template v-if="goal.reported_calls">（含子 Agent 和判断器）</template></small>
  <p v-if="goal.reason" class="goal-reason">{{goal.reason}}</p>
  <div class="goal-actions">
    <button v-if="!terminal&&goal.status==='active'&&work.s.running" class="quiet" :disabled="work.s.goalBusy" @click="work.safe(()=>work.controlGoal('pause'))">暂停目标</button>
    <button v-if="!terminal&&!work.s.running" class="secondary" :disabled="work.busy.value" @click="work.safe(()=>work.controlGoal('resume'))">恢复执行</button>
    <button v-if="!terminal" class="quiet" :disabled="work.s.goalBusy" @click="work.safe(()=>work.controlGoal('clear'))">清除目标</button>
    <button class="quiet" @click="work.safe(()=>work.refreshGoal())">刷新</button>
  </div>
</div><p v-else class="empty-state">尚未设置目标。也可在对话中输入 /goal 验收条件。</p>
<p class="section-note">本次最多 {{work.s.status?.max_steps||40}} 个主循环步骤，连续未达标上限 {{work.s.status?.goal_block_cap||8}} 次。达到上限保留目标，由你决定是否恢复。</p>
</div></template>
<style scoped>
.goal-panel,.goal-form,.goal-state{display:flex;flex-direction:column;gap:12px}.goal-form label{display:flex;flex-direction:column;gap:7px;font-size:13px}.goal-form textarea{width:100%;box-sizing:border-box;resize:vertical;padding:9px;border:1px solid #d8dce4;border-radius:8px;background:#fff;font:inherit;color:inherit}.goal-state{padding:13px;border:1px solid #e3e7ef;border-radius:10px;overflow-wrap:anywhere}.goal-state p{margin:0;white-space:pre-wrap;font-size:13px;line-height:1.6}.goal-state small{font-size:11px;color:#667085}.goal-state.achieved{border-color:#87cbb4}.goal-actions{display:flex;flex-wrap:wrap;gap:9px}.goal-reason{color:#667085}
</style>
