import {it,expect,vi,afterEach,beforeEach} from 'vitest';
import {reactive} from 'vue';
import {mount,shallowMount,flushPromises,DOMWrapper} from '@vue/test-utils';
import ExperiencePage from './components/ExperiencePage.vue';
import ExperiencePanel from './components/ExperiencePanel.vue';
import Sidebar from './components/Sidebar.vue';
let panel;
beforeEach(()=>{HTMLDialogElement.prototype.showModal=function(){this.open=true;};HTMLDialogElement.prototype.close=function(){this.open=false;};});
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
const rows=[{id:'a',title:'Windows 路径验证',when:'路径带空格',strategy:'使用参数数组并检查退出码',enabled:true,confirmations:1,evidence:[3],source_session:'s',source_run:'r'},{id:'b',title:'解析响应格式',when:'解析 JSON',strategy:'检查 JSON 字段',enabled:false,confirmations:1,evidence:[4],source_session:'s',source_run:'r'}];
function work(){return {s:reactive({session:'s',page:'chat',status:null,localFolder:null,events:[],running:false,sessions:[{id:'s',title:'当前任务'},{id:'other',title:'其他任务'}]}),safe:fn=>Promise.resolve().then(fn),notify:vi.fn()};}
function stub(){const fetch=vi.fn(async url=>({ok:true,json:async()=>String(url).endsWith('/experiences')?{experiences:rows,jobs:[]}:{events:[],local_folder:'D:/other-workspace'}}));vi.stubGlobal('fetch',fetch);return fetch;}
it('adds an independent page to the left navigation',async()=>{
 const w=work();panel=shallowMount(Sidebar,{props:{work:w}});await panel.find('[data-page="experiences"]').trigger('click');expect(w.s.page).toBe('experiences');
});
it('keeps the right panel focused on summarizing with an entry to the full library',async()=>{
 stub();const w=work();panel=mount(ExperiencePanel,{props:{work:w,view:'summary'}});await flushPromises();
 expect(panel.find('[aria-label="经验总结方向"]').exists()).toBe(true);expect(panel.findAll('.solution-card')).toHaveLength(0);
 expect(panel.text()).not.toContain('把做成的任务');
 await panel.findAll('button').find(button=>button.text()==='打开经验管理').trigger('click');expect(w.s.page).toBe('experiences');
});
it('shows detailed experience cards with search and status filters on the main page',async()=>{
 stub();panel=mount(ExperiencePage,{props:{work:work()}});await flushPromises();
 expect(panel.findAll('.solution-card')).toHaveLength(2);expect(panel.find('[aria-label="经验总结方向"]').exists()).toBe(false);
 await panel.find('[aria-label="搜索经验"]').setValue('路径');expect(panel.findAll('.solution-card')).toHaveLength(1);expect(panel.find('.solution-card').text()).not.toContain('使用参数数组并检查退出码');
 await panel.find('.solution-card-open').trigger('click');await flushPromises();
 let dialog=new DOMWrapper(document.querySelector('.experience-detail'));expect(dialog.text()).toContain('使用参数数组并检查退出码');
 await dialog.find('[aria-label="关闭经验详情"]').trigger('click');await flushPromises();
 await panel.find('[aria-label="搜索经验"]').setValue('');await panel.find('[aria-label="筛选经验状态"]').setValue('disabled');expect(panel.findAll('.solution-card')).toHaveLength(1);expect(panel.find('.solution-card').text()).toContain('解析响应格式');
});
it('browses another source session without changing the active chat',async()=>{
 const fetch=stub(),w=work();panel=mount(ExperiencePage,{props:{work:w}});await flushPromises();
 await panel.find('[aria-label="经验来源会话"]').setValue('other');await flushPromises();
 expect(fetch.mock.calls.some(([url])=>url==='/api/sessions/other/experiences')).toBe(true);expect(w.s.session).toBe('s');expect(panel.text()).toContain('D:/other-workspace');
});

it('offers all sessions and uses the global experience management endpoints',async()=>{
 let deleted=false;
 const fetch=vi.fn(async(url,options)=>{if(options?.method==='DELETE'){deleted=true;return {ok:true,json:async()=>({deleted:true})};}return {ok:true,json:async()=>({experiences:deleted?[]:rows.map(row=>({...row,source_session_title:'来源任务 A'})),jobs:[]})};});vi.stubGlobal('fetch',fetch);
 const w=work();panel=mount(ExperiencePage,{props:{work:w}});await flushPromises();
 await panel.find('[aria-label="经验来源会话"]').setValue('__all__');await flushPromises();
 expect(fetch.mock.calls.some(([url])=>url==='/api/experiences')).toBe(true);expect(panel.text()).not.toContain('来源任务 A');expect(panel.findAll('.solution-card')).toHaveLength(2);expect(w.s.session).toBe('s');
 await panel.find('.solution-card-open').trigger('click');await flushPromises();
 const dialog=new DOMWrapper(document.querySelector('.experience-detail'));expect(dialog.text()).toContain('来源任务 A');
 await dialog.findAll('button').find(button=>button.text()==='删除经验').trigger('click');await dialog.findAll('button').find(button=>button.text()==='确认删除').trigger('click');await flushPromises();
 expect(fetch).toHaveBeenCalledWith('/api/experiences/a',expect.objectContaining({method:'DELETE'}));
});
