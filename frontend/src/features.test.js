import {describe,it,expect,vi,afterEach} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import ExperiencePanel from './components/ExperiencePanel.vue';
import PreviewPanel from './components/PreviewPanel.vue';
const response=data=>({ok:true,json:async()=>data});let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function work(){return {s:{session:'s',running:false,prompt:'',events:[{seq:1,type:'user_message',run_id:'round',content:'修复计算器加法错误'},{seq:2,type:'run_start',run_id:'round',time:1793000000},{seq:3,type:'tool_end',run_id:'round',name:'run_command',result:{exit_code:0,output:'TEST_OK'}},{seq:4,type:'text_delta',run_id:'round',content:'加法已修复并通过验证'},{seq:5,type:'run_end',status:'completed',run_id:'round'}]},safe:fn=>Promise.resolve().then(fn),openSession:vi.fn()};}
describe('experience and visual feedback panels',()=>{
 it('requires success confirmation before extracting',async()=>{
  const fetch=vi.fn(async()=>response({experiences:[]}));vi.stubGlobal('fetch',fetch);
  panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();
  await panel.find('select').setValue('round');expect(panel.find('button.secondary').attributes('disabled')).toBeDefined();
  await panel.find('input[type=checkbox]').setValue(true);await panel.find('button.secondary').trigger('click');await flushPromises();
  expect(fetch.mock.calls.some(([url,opts])=>url.endsWith('/jobs')&&JSON.parse(opts.body).confirmed===true)).toBe(true);
 });
 it('keeps extraction errors visible and allows retrying',async()=>{
  const fetch=vi.fn(async(url,options)=>options?.method==='POST'?{ok:false,status:400,json:async()=>({detail:'模型引用了不属于本任务的工具证据，方案未保存，请重试。'})}:response({experiences:[]}));vi.stubGlobal('fetch',fetch);
  panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();
  await panel.find('select').setValue('round');await panel.find('input[type=checkbox]').setValue(true);
  await panel.find('button.secondary').trigger('click');await flushPromises();
  expect(panel.find('[role=alert]').text()).toContain('工具证据');
  expect(panel.find('button.secondary').attributes('disabled')).toBeUndefined();
 });
 it('accepts focus-only session summaries and focus combined with a task',async()=>{
  const fetch=vi.fn(async()=>response({experiences:[],jobs:[]}));vi.stubGlobal('fetch',fetch);
  panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();
  await panel.find('textarea[aria-label="经验总结方向"]').setValue('总结 Windows 路径问题');
  await panel.find('input[type=checkbox]').setValue(true);await panel.find('button.secondary').trigger('click');await flushPromises();
  let posts=fetch.mock.calls.filter(([url])=>url.endsWith('/jobs'));
  expect(JSON.parse(posts[0][1].body)).toEqual({run_id:'',confirmed:true,focus:'总结 Windows 路径问题',source_scope:'session'});
  await panel.find('select').setValue('round');await panel.find('input[type=checkbox]').setValue(true);
  await panel.find('button.secondary').trigger('click');await flushPromises();
  posts=fetch.mock.calls.filter(([url])=>url.endsWith('/jobs'));
  expect(JSON.parse(posts[1][1].body).source_scope).toBe('run');expect(JSON.parse(posts[1][1].body).run_id).toBe('round');
 });
 it('accepts feedback only from the preview frame and persists user notes',async()=>{
  const fetch=vi.fn(async url=>response(url.endsWith('/preview/entries')?{entries:[{path:'index.html'}]}:url.endsWith('/preview')?{entry:'index.html',revision:'a'.repeat(64),token:'nonce',url:'/preview'}:{annotations:[]}));vi.stubGlobal('fetch',fetch);
  panel=mount(PreviewPanel,{props:{work:work()},attachTo:document.body});await flushPromises();
  await panel.find('button.secondary').trigger('click');await flushPromises();
  const iframe=panel.find('iframe');expect(iframe.attributes('sandbox')).toBe('allow-scripts');
  const data={type:'ecoder:annotation',token:'nonce',entry:'index.html',selector:'button',text:'Submit',rect:{x:0,y:0,width:10,height:10},viewport:{width:1200,height:800}};
  window.dispatchEvent(new MessageEvent('message',{data,origin:'null',source:window}));await flushPromises();expect(panel.find('textarea').exists()).toBe(false);
  window.dispatchEvent(new MessageEvent('message',{data,origin:'null',source:iframe.element.contentWindow}));await flushPromises();
  await panel.find('textarea').setValue('改成蓝色');await panel.find('form').trigger('submit');await flushPromises();
  const call=fetch.mock.calls.find(([url])=>url.endsWith('/annotations')&&url!=='/api/sessions/s/preview'&&fetch.mock.calls.some(([u,o])=>u===url&&o.method==='POST'));
  expect(fetch.mock.calls.some(([url,opts])=>url.endsWith('/annotations')&&opts.method==='POST'&&JSON.parse(opts.body).note==='改成蓝色')).toBe(true);
 });
});
