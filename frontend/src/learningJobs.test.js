import {it,expect,vi,afterEach} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import ExperiencePanel from './components/ExperiencePanel.vue';
let panel;
afterEach(()=>{panel?.unmount();vi.useRealTimers();vi.unstubAllGlobals();});
const ok=value=>({ok:true,json:async()=>value});
const lesson={id:'lesson',title:'修复解析错误',when:'解析响应时',strategy:'检查格式并验证',enabled:true,confirmations:1,source_session:'s',source_run:'r',evidence:[3]};
function work(){return {s:{session:'s',running:false,events:[]},safe:fn=>Promise.resolve().then(fn),notify:vi.fn()};}
it('recovers pending work after remount and refreshes results without another model submission',async()=>{
 vi.useFakeTimers();let completed=false;
 const fetch=vi.fn(async()=>ok({experiences:completed?[lesson]:[],jobs:[{id:'job',run_id:'r',title:'修复解析错误',status:completed?'completed':'running',result_count:completed?1:0}]}));vi.stubGlobal('fetch',fetch);
 panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();expect(panel.text()).toContain('后台总结中');panel.unmount();
 panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();expect(panel.text()).toContain('离开页面不影响保存');
 completed=true;await vi.advanceTimersByTimeAsync(2000);await flushPromises();expect(panel.text()).toContain('已保存或更新 1 条经验');expect(panel.findAll('.solution-card')).toHaveLength(1);
 expect(fetch.mock.calls.every(([,options])=>!options?.method)).toBe(true);
});
it('requires per-item confirmation then deletes only that experience',async()=>{
 let removed=false;
 const fetch=vi.fn(async(url,options)=>{if(options?.method==='DELETE'){removed=true;return ok({deleted:true});}return ok({experiences:removed?[]:[lesson,{...lesson,id:'keep',title:'保留的经验'}],jobs:[]});});vi.stubGlobal('fetch',fetch);
 panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();
 await panel.findAll('.solution-card')[0].findAll('button').find(b=>b.text()==='删除经验').trigger('click');expect(fetch.mock.calls.some(([,opts])=>opts?.method==='DELETE')).toBe(false);
 await panel.findAll('button').find(b=>b.text()==='确认删除').trigger('click');await flushPromises();
 expect(fetch).toHaveBeenCalledWith('/api/sessions/s/experiences/lesson',expect.objectContaining({method:'DELETE'}));
});
