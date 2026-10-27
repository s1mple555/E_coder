import {it,expect,vi,afterEach} from 'vitest';
import {reactive} from 'vue';
import {mount,flushPromises} from '@vue/test-utils';
import {completedTasks} from './lib/experienceRuns.js';
import ExperiencePanel from './components/ExperiencePanel.vue';
let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function trace(id,prompt,time=1793000000){return [
 {run_id:id,type:'user_message',content:prompt}, {run_id:id,type:'run_start',time},
 {run_id:id,type:'step_start'}, {run_id:id,type:'text_delta',content:'正在检查'},
 {run_id:id,type:'tool_end',seq:3,name:'run_command',result:{exit_code:0,output:'TEST_OK'}},
 {run_id:id,type:'step_start'}, {run_id:id,type:'subagent_text_delta',content:'private'},
 {run_id:id,type:'text_delta',content:'修复完成，测试通过'}, {run_id:id,type:'run_end',status:'completed'}];}
function work(events){return {s:reactive({session:'s',running:false,events}),safe:fn=>Promise.resolve().then(fn),notify:vi.fn()};}
it('labels tasks by real request and time, keeps evidence and ignores failed runs and child text',()=>{
 const tasks=completedTasks([...trace('first','修复登录错误'),...trace('second','优化计算器布局',1793000001),{run_id:'bad',type:'run_end',status:'failed'}]);
 expect(tasks.map(t=>t.title)).toEqual(['优化计算器布局','修复登录错误']);expect(tasks[0].answer).toBe('修复完成，测试通过');
 expect(tasks[0].successTools).toBe(1);expect(tasks[0].tools[0].result.output).toBe('TEST_OK');
});
it('shows request, result and evidence and requires reconfirmation after changing tasks',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({experiences:[]})})));
 const w=work([...trace('first','修复登录错误'),...trace('second','优化计算器布局')]);panel=mount(ExperiencePanel,{props:{work:w}});await flushPromises();
 expect(panel.find('select').text()).toContain('修复登录错误');expect(panel.find('select').text()).not.toContain('first');
 await panel.find('select').setValue('first');expect(panel.text()).toContain('修复完成，测试通过');expect(panel.text()).toContain('TEST_OK');
 await panel.find('input[type=checkbox]').setValue(true);expect(panel.find('button.secondary').attributes('disabled')).toBeUndefined();
 await panel.find('select').setValue('second');expect(panel.find('input[type=checkbox]').element.checked).toBe(false);
 expect(panel.find('button.secondary').attributes('disabled')).toBeDefined();
});
it('prevents extracting a task with only failed command evidence',async()=>{
 const events=trace('first','修复登录错误');events.find(e=>e.type==='tool_end').result.exit_code=1;
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({experiences:[]})})));
 panel=mount(ExperiencePanel,{props:{work:work(events)}});await flushPromises();await panel.find('select').setValue('first');
 expect(panel.find('input[type=checkbox]').attributes('disabled')).toBeDefined();expect(panel.find('button.secondary').attributes('disabled')).toBeDefined();
});
it('opens the source task from another session without navigating away',async()=>{
 const row={id:'lesson',title:'标准库验证计算结果',when:'修改计算逻辑后',strategy:'先复现，再修复，再断言验证。',source_run:'old-run',source_session:'old-session',evidence:[3],confirmations:1,enabled:true};
 const fetch=vi.fn(async url=>({ok:true,json:async()=>String(url).endsWith('/experiences')?{experiences:[row]}:{events:trace('old-run','修复旧项目的加法错误')}}));vi.stubGlobal('fetch',fetch);
 const w=work([]);panel=mount(ExperiencePanel,{props:{work:w}});await flushPromises();
 await panel.findAll('button').find(b=>b.text()==='查看来源任务').trigger('click');await flushPromises();
 expect(fetch).toHaveBeenCalledWith('/api/sessions/old-session',expect.anything());expect(panel.text()).toContain('修复旧项目的加法错误');expect(w.s.session).toBe('s');
});
