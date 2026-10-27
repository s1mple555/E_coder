import {it,expect,vi,afterEach} from 'vitest';
import {reactive} from 'vue';
import {mount,flushPromises} from '@vue/test-utils';
import MemoryEditor from './components/MemoryEditor.vue';
let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function work(){return {s:reactive({session:'s',memory:'已有约束',running:false,loading:false}),notify:vi.fn()};}
it('saves a user edit with the original text as its version check',async()=>{
 const fetch=vi.fn(async()=>({ok:true,json:async()=>({saved:true,memory:'手动更新'})}));vi.stubGlobal('fetch',fetch);
 const w=work();panel=mount(MemoryEditor,{props:{work:w}});await panel.find('button').trigger('click');await panel.find('textarea').setValue('手动更新');await panel.find('form').trigger('submit');await flushPromises();
 expect(fetch).toHaveBeenCalledWith('/api/sessions/s/memory',expect.objectContaining({method:'PUT',body:JSON.stringify({content:'手动更新',expected:'已有约束'})}));
 expect(w.s.memory).toBe('手动更新');expect(panel.find('textarea').exists()).toBe(false);expect(w.notify).toHaveBeenCalledWith('备忘录已保存。');
});
it('cancels without writing and allows saving empty content to clear memory',async()=>{
 const fetch=vi.fn(async()=>({ok:true,json:async()=>({saved:true,memory:''})}));vi.stubGlobal('fetch',fetch);const w=work();panel=mount(MemoryEditor,{props:{work:w}});
 await panel.find('button').trigger('click');await panel.find('textarea').setValue('放弃的修改');await panel.findAll('button').find(b=>b.text()==='取消').trigger('click');expect(fetch).not.toHaveBeenCalled();expect(w.s.memory).toBe('已有约束');
 await panel.find('button').trigger('click');await panel.find('textarea').setValue('');await panel.find('form').trigger('submit');await flushPromises();expect(w.s.memory).toBe('');
});
it('keeps a rejected draft until the user chooses to reload the latest content',async()=>{
 const fetch=vi.fn(async(url,options)=>options?.method==='PUT'?{ok:false,status:409,json:async()=>({detail:'备忘录已被更新，请重新载入。'})}:{ok:true,json:async()=>({memory:'Agent 的最新记录'})});vi.stubGlobal('fetch',fetch);
 const w=work();panel=mount(MemoryEditor,{props:{work:w}});await panel.find('button').trigger('click');await panel.find('textarea').setValue('保留的草稿');await panel.find('form').trigger('submit');await flushPromises();
 expect(panel.find('[role=alert]').text()).toContain('已被更新');expect(panel.find('textarea').element.value).toBe('保留的草稿');
 await panel.findAll('button').find(b=>b.text()==='重新载入').trigger('click');await flushPromises();expect(panel.find('textarea').element.value).toBe('Agent 的最新记录');expect(w.s.memory).toBe('Agent 的最新记录');
});
