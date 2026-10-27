import {it,expect,vi,afterEach} from 'vitest';
import {reactive} from 'vue';
import {mount,flushPromises} from '@vue/test-utils';
import SettingsPage from './components/SettingsPage.vue';
import PermissionSelect from './components/PermissionSelect.vue';
let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function work(){return {s:reactive({page:'chat',status:{permission_mode:'approval',configured:true,base_url:'https://example.com/v1',model:'test'},running:false}),loadStatus:vi.fn(),notify:vi.fn()};}
it('saves the composer selection immediately without navigating away',async()=>{
 const fetch=vi.fn(async()=>({ok:true,json:async()=>({permission_mode:'full'})}));vi.stubGlobal('fetch',fetch);
 const w=work();panel=mount(PermissionSelect,{props:{work:w}});
 await panel.find('select').setValue('full');await flushPromises();
 expect(fetch).toHaveBeenCalledWith('/api/permissions',expect.objectContaining({body:JSON.stringify({permission_mode:'full'})}));
 expect(w.s.status.permission_mode).toBe('full');expect(w.s.page).toBe('chat');expect(w.loadStatus).toHaveBeenCalled();
});
it('restores the saved mode when the server rejects a change',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:409,json:async()=>({detail:'有任务正在运行'})})));
 const w=work();panel=mount(PermissionSelect,{props:{work:w}});
 await panel.find('select').setValue('full');await flushPromises();
 expect(w.s.status.permission_mode).toBe('approval');expect(panel.find('select').element.value).toBe('approval');
 expect(w.notify).toHaveBeenCalledWith('有任务正在运行');
});
it('disables changes while running and removes the old settings form',async()=>{
 const w=work();w.s.running=true;panel=mount(PermissionSelect,{props:{work:w}});
 expect(panel.find('select').attributes('disabled')).toBeDefined();panel.unmount();
 panel=mount(SettingsPage,{props:{work:w}});expect(panel.findAll('form')).toHaveLength(1);expect(panel.text()).not.toContain('操作权限');
});
