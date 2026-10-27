<script setup>
import {computed,ref} from 'vue';
import {scheduleValues,describeSchedule,weekdays} from '../cronSchedule.js';
const props=defineProps({work:Object});
const frequency=ref('daily'),time=ref('09:00'),weekday=ref('1'),interval=ref('15'),cron=ref('0 9 * * *');
const prompt=ref(''),recurring=ref(true),durable=ref(true);
const schedule=computed(()=>scheduleValues({frequency:frequency.value,time:time.value,weekday:weekday.value,interval:interval.value,advanced:cron.value,recurring:recurring.value}));
const preview=computed(()=>{try{return describeSchedule(schedule.value);}catch{return '请选择有效的执行时间';}});
async function submit(){
  await props.work.createCron({...schedule.value,prompt:prompt.value,durable:durable.value});
  prompt.value='';
}
</script>
<template><div class="cron-panel">

<form class="cron-form" @submit.prevent="work.safe(submit)">
  <label>执行频率<select v-model="frequency" aria-label="执行频率"><option value="daily">每天</option><option value="workdays">周一至周五</option><option value="weekly">每周</option><option value="interval">固定间隔</option><option value="once">仅执行一次</option><option value="advanced">高级：自定义 Cron</option></select></label>
  <label v-if="frequency==='weekly'">星期<select v-model="weekday" aria-label="执行星期"><option v-for="(day,index) in weekdays" :key="index" :value="String(index)">{{day}}</option></select></label>
  <label v-if="frequency==='interval'">执行间隔<select v-model="interval" aria-label="执行间隔"><option v-for="minutes in [5,10,15,20,30,60]" :key="minutes" :value="String(minutes)">{{minutes===60?'每小时整点':`每 ${minutes} 分钟`}}</option></select></label>
  <label v-else-if="frequency!=='advanced'">执行时间<input v-model="time" type="time" required aria-label="执行时间"></label>
  <template v-if="frequency==='advanced'"><label>Cron 表达式<input v-model="cron" required maxlength="100" placeholder="0 9 * * *" aria-label="Cron 表达式"></label><small>分钟 小时 日 月 星期（0 为星期日）</small><label class="inline-option"><input v-model="recurring" type="checkbox">周期执行</label></template>
  <p class="schedule-preview" aria-live="polite">{{preview}}（北京时间）</p>
  <small v-if="frequency==='once'">到所选时间执行一次；若今天的时间已过，则在明天执行。</small>
  <small v-if="frequency==='workdays'">仅按星期排期，不包含法定节假日调休判断。</small>
  <label>任务内容<textarea v-model="prompt" required maxlength="12000" rows="3" placeholder="检查项目中的待办事项，并汇总结果" aria-label="定时任务内容"></textarea></label>
  <label class="inline-option"><input v-model="durable" type="checkbox">重启后保留</label>
  <button class="secondary" type="submit" :disabled="work.s.scheduling||work.s.loading||!prompt.trim()">{{work.s.scheduling?'创建中…':'创建定时任务'}}</button>
</form>
<div class="cron-heading"><strong>本会话定时任务</strong><button class="quiet" @click="work.safe(()=>work.refreshCrons())">刷新</button></div>
<p v-if="!work.s.crons.length" class="empty-state">暂无定时任务。也可以在对话中要求 Agent 安排。</p>
<article v-for="job in work.s.crons" :key="job.id" class="task-item">
  <div class="task-title">{{job.prompt}}</div><strong>{{describeSchedule(job)}}</strong>
  <small>{{job.durable?'重启后保留':'仅本次启动有效'}} · {{job.pending_delivery?'等待交付':'等待下次触发'}}</small>
  <small v-if="job.last_fired">最近触发：{{job.last_fired}}（北京时间）</small>
  <details><summary>查看 Cron 规则</summary><code>{{job.cron}}</code></details>
  <button class="quiet" :aria-label="`取消定时任务 ${job.id}`" @click="work.safe(()=>work.cancelCron(job.id))">取消定时任务</button>
</article>
</div></template>
<style scoped>
.cron-panel{display:flex;flex-direction:column;gap:14px}.cron-form{display:flex;flex-direction:column;gap:10px}.cron-form>label{display:flex;flex-direction:column;gap:6px;font-size:13px}.cron-form input:not([type=checkbox]),.cron-form textarea,.cron-form select{width:100%;box-sizing:border-box;padding:9px;border:1px solid #d8dce4;border-radius:8px;background:#fff;color:inherit;font:inherit}.cron-form textarea{resize:vertical}.cron-form>.inline-option{display:flex;flex-direction:row;align-items:center;gap:6px;font-size:12px}.cron-heading{display:flex;justify-content:space-between;gap:12px;font-size:12px}.cron-panel .task-item{display:flex;flex-direction:column;gap:8px;overflow-wrap:anywhere}.cron-panel small,.cron-panel details{color:#667085;font-size:12px}.cron-panel .task-item button{align-self:flex-start}.schedule-preview{margin:0;padding:10px;background:#f0f4ff;border-radius:8px;font-size:13px;line-height:1.5}
</style>
