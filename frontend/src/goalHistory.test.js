import {it,expect,vi,afterEach} from 'vitest';
import {reactive,nextTick} from 'vue';
import {mount} from '@vue/test-utils';
import GoalPanel from './components/GoalPanel.vue';
let panel;
afterEach(()=>panel?.unmount());
function work(){const old={id:'old',condition:'修复登录模块',status:'achieved',evaluations:1,agent_calls:2,judge_calls:1,started_at:1,reported_calls:0};const current={...old,id:'now',condition:'验证购物车',status:'paused',started_at:2};return {s:reactive({session:'s',goal:current,events:[{type:'goal_status',goal:{...old,status:'active'}},{type:'goal_status',goal:old},{type:'goal_status',goal:current}],running:false}),busy:{value:false},safe:fn=>fn(),controlGoal:vi.fn(),refreshGoal:vi.fn()};}
it('deduplicates snapshots and selects the current goal by default',()=>{
 const w=work();panel=mount(GoalPanel,{props:{work:w}});expect(panel.findAll('select option')).toHaveLength(2);
 expect(panel.find('select').element.value).toBe('now');expect(panel.find('.goal-state').text()).toContain('验证购物车');
 expect(panel.find('select').text()).toContain('已达成 · 修复登录模块');
});
it('shows only selected history and keeps controls restricted to the current goal',async()=>{
 const w=work();panel=mount(GoalPanel,{props:{work:w}});expect(panel.find('.goal-actions').text()).toContain('恢复执行');
 await panel.find('select').setValue('old');expect(panel.find('.goal-state').text()).toContain('修复登录模块');
 expect(panel.find('.goal-state').text()).not.toContain('验证购物车');expect(panel.find('.goal-state').text()).toContain('历史目标');
 expect(panel.find('.goal-actions').text()).not.toContain('恢复执行');expect(panel.find('.goal-actions').text()).not.toContain('清除目标');
 w.s.goal={...w.s.goal,reason:'最新进度'};await nextTick();expect(panel.find('select').element.value).toBe('old');
});
it('resets selection on session change and follows newly created goals',async()=>{
 const w=work();panel=mount(GoalPanel,{props:{work:w}});await panel.find('select').setValue('old');
 w.s.goal={...w.s.goal,id:'new',condition:'新目标',started_at:3};await nextTick();expect(panel.find('select').element.value).toBe('new');
 w.s.session='another';w.s.goal=null;w.s.events=[];await nextTick();expect(panel.find('select').exists()).toBe(false);expect(panel.find('.goal-state').exists()).toBe(false);
});
