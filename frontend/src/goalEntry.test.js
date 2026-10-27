import {it,expect,vi,afterEach} from 'vitest';
import {reactive,nextTick} from 'vue';
import {shallowMount} from '@vue/test-utils';
import App from './App.vue';
let work,panel;
vi.mock('./composables/useWorkbench.js',()=>({useWorkbench:()=>work}));
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function render(width){vi.stubGlobal('innerWidth',width);work={s:reactive({page:'chat',tab:'timeline',status:null,toast:''}),initialize:vi.fn()};panel=shallowMount(App);}
it('opens the goal panel and toggles goal mode without closing the panel',async()=>{
 render(1200);const chat=panel.findComponent({name:'ChatWorkspace'}),inspector=()=>panel.findComponent({name:'ExecutionPanel'});
 chat.vm.$emit('inspector');await nextTick();expect(inspector().props('collapsed')).toBe(true);
 chat.vm.$emit('goal');await nextTick();expect(work.s.tab).toBe('goal');expect(work.s.goalEnabled).toBe(true);expect(inspector().props('collapsed')).toBe(false);
 chat.vm.$emit('goal');await nextTick();expect(work.s.goalEnabled).toBe(false);expect(inspector().props('collapsed')).toBe(false);
});
it('opens the mobile panel when the composer goal button is used',async()=>{
 render(700);panel.findComponent({name:'ChatWorkspace'}).vm.$emit('goal');await nextTick();
 expect(work.s.tab).toBe('goal');expect(panel.findComponent({name:'ExecutionPanel'}).props('mobile')).toBe(true);
});
