import {describe,it,expect,vi,afterEach} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import ExperiencePanel from './components/ExperiencePanel.vue';
import PreviewPanel from './components/PreviewPanel.vue';
const response=data=>({ok:true,json:async()=>data});let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function work(){return {s:{session:'s',running:false,prompt:'',events:[{type:'run_end',status:'completed',run_id:'round'}]},safe:fn=>Promise.resolve().then(fn),openSession:vi.fn()};}
describe('experience and visual feedback panels',()=>{
 it('requires success confirmation before extracting',async()=>{
  const fetch=vi.fn(async()=>response({experiences:[]}));vi.stubGlobal('fetch',fetch);
  panel=mount(ExperiencePanel,{props:{work:work()}});await flushPromises();
  await panel.find('select').setValue('round');expect(panel.find('button.secondary').attributes('disabled')).toBeDefined();
  await panel.find('input[type=checkbox]').setValue(true);await panel.find('button.secondary').trigger('click');await flushPromises();
  expect(fetch.mock.calls.some(([url,opts])=>url.endsWith('/extract')&&JSON.parse(opts.body).confirmed===true)).toBe(true);
 });
 it('accepts feedback only from the preview frame and persists user notes',async()=>{
  const fetch=vi.fn(async url=>response(url.endsWith('/preview')?{entry:'index.html',revision:'a'.repeat(64),token:'nonce',url:'/preview'}:{annotations:[]}));vi.stubGlobal('fetch',fetch);
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
