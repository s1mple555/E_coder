import {it,expect,vi,afterEach} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import PreviewPanel from './components/PreviewPanel.vue';
let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
const response=data=>({ok:true,json:async()=>data});
it('selects a discovered page and opens only desktop annotation preview',async()=>{
 const fetch=vi.fn(async(url,options)=>response(url.endsWith('/preview/entries')?{entries:[{path:'index.html'},{path:'dist/profile.html',generated:true}]}:url.endsWith('/preview')?{entry:JSON.parse(options.body).entry,token:'token',revision:'a'.repeat(64),url:'/document'}:{annotations:[{id:'another',entry:'index.html',status:'pending',selector:'h1',note:'other page'}]}));vi.stubGlobal('fetch',fetch);
 const work={s:{session:'s',running:false,prompt:''},safe:fn=>Promise.resolve().then(fn)};
 panel=mount(PreviewPanel,{props:{work}});await flushPromises();
 expect(panel.findAll('[aria-label="预览入口"] option')).toHaveLength(2);
 await panel.find('[aria-label="预览入口"]').setValue('dist/profile.html');
 await panel.find('button.secondary').trigger('click');await flushPromises();
 expect(fetch).toHaveBeenCalledWith('/api/sessions/s/preview',expect.objectContaining({body:JSON.stringify({entry:'dist/profile.html'})}));
 expect(panel.find('iframe').attributes('sandbox')).toBe('allow-scripts');
 expect(panel.find('[aria-label="预览宽度"]').exists()).toBe(false);
 expect(panel.text()).not.toContain('交互模式');expect(panel.text()).not.toContain('手机 390');
 expect(panel.find('.preview-studio').text()).not.toContain('other page');
 expect(panel.find('.submit-feedback').attributes('disabled')).toBeDefined();
});

it('does not reopen a closed preview when an earlier refresh returns',async()=>{
 let release,count=0;
 const fetch=vi.fn(async(url)=>{if(url.endsWith('/preview/entries'))return response({entries:[{path:'index.html'}]});if(url.endsWith('/preview')){count++;if(count===2)return new Promise(resolve=>release=resolve);return response({entry:'index.html',token:'first',revision:'a'.repeat(64),url:'/document'});}return response({annotations:[]});});vi.stubGlobal('fetch',fetch);
 const work={s:{session:'s',running:false,prompt:''},safe:fn=>Promise.resolve().then(fn)};
 panel=mount(PreviewPanel,{props:{work}});await flushPromises();await panel.find('button.secondary').trigger('click');await flushPromises();
 await panel.findAll('button').find(button=>button.text()==='刷新产物').trigger('click');await flushPromises();
 await panel.findAll('button').find(button=>button.text()==='关闭预览').trigger('click');
 release(response({entry:'index.html',token:'late',revision:'b'.repeat(64),url:'/late'}));await flushPromises();expect(panel.find('.preview-studio').exists()).toBe(false);
});
it('sends only one annotation while saving is pending',async()=>{
 let release,writes=0;
 vi.stubGlobal('fetch',vi.fn(async(url,options)=>{
  if(url.endsWith('/preview/entries'))return response({entries:[{path:'index.html'}]});
  if(url.endsWith('/preview'))return response({entry:'index.html',token:'token',revision:'a'.repeat(64),url:'/document'});
  if(options?.method==='POST'){writes++;return new Promise(resolve=>release=resolve);}return response({annotations:[]});
 }));const work={s:{session:'s',running:false,prompt:''},safe:fn=>Promise.resolve().then(fn)};
 panel=mount(PreviewPanel,{props:{work},attachTo:document.body});await flushPromises();await panel.find('button.secondary').trigger('click');await flushPromises();
 const iframe=panel.find('iframe');window.dispatchEvent(new MessageEvent('message',{origin:'null',source:iframe.element.contentWindow,data:{type:'ecoder:annotation',token:'token',entry:'index.html',selector:'h1',text:'title',rect:{},viewport:{}}}));await flushPromises();
 await panel.find('textarea').setValue('change title');await panel.find('form').trigger('submit');await panel.find('form').trigger('submit');await flushPromises();expect(writes).toBe(1);
 release(response({}));await flushPromises();
});
