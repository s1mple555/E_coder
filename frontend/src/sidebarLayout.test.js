import {it,expect,vi,afterEach} from 'vitest';
import {reactive,nextTick} from 'vue';
import {mount,shallowMount,flushPromises} from '@vue/test-utils';
import ExecutionPanel from './components/ExecutionPanel.vue';
import ExperiencePanel from './components/ExperiencePanel.vue';
let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
it('shows usage totals only in the execution records tab',async()=>{
 const work={s:reactive({tab:'timeline',usage:{calls:3,tokens:10,reported:1},status:null,events:[],runs:[],runLabel:'就绪',tasks:[],files:[],goal:null,crons:[],memory:'',historyCount:0}),compact:{value:null},busy:{value:false}};
 panel=shallowMount(ExecutionPanel,{props:{work}});
 expect(panel.find('[aria-label="本会话调用与 Token 汇总"]').isVisible()).toBe(true);
 work.s.tab='goal';await nextTick();expect(panel.find('[aria-label="本会话调用与 Token 汇总"]').element.closest('section').style.display).toBe('none');
 work.s.tab='experiences';await nextTick();expect(panel.find('[aria-label="本会话调用与 Token 汇总"]').element.closest('section').style.display).toBe('none');
});
it('keeps completed summaries out of the sidebar and uses a compact focus input',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({experiences:[],jobs:[{id:'done',run_id:'r',title:'已经完成的总结',status:'completed',result_count:2}]})})));
 const work={s:{session:'s',events:[],running:false},safe:fn=>fn()};
 panel=mount(ExperiencePanel,{props:{work,view:'summary'}});await flushPromises();
 expect(panel.text()).not.toContain('已经完成的总结');expect(panel.findAll('.learning-job')).toHaveLength(0);
 expect(panel.find('[aria-label="经验总结方向"]').attributes('rows')).toBe('3');
 expect(panel.findAll('button').some(button=>button.text()==='打开经验管理')).toBe(true);
});
