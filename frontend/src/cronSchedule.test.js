import {describe,it,expect} from 'vitest';
import {mount,flushPromises} from '@vue/test-utils';
import {scheduleValues,describeSchedule} from './cronSchedule.js';
import CronPanel from './components/CronPanel.vue';
describe('readable schedule selection',()=>{
  it.each([
    [{frequency:'daily',time:'08:05'},'5 8 * * *',true],
    [{frequency:'workdays',time:'18:30'},'30 18 * * 1-5',true],
    [{frequency:'weekly',weekday:'0',time:'12:00'},'0 12 * * 0',true],
    [{frequency:'interval',interval:'15'},'*/15 * * * *',true],
    [{frequency:'interval',interval:'60'},'0 * * * *',true],
    [{frequency:'once',time:'09:00'},'0 9 * * *',false],
    [{frequency:'advanced',advanced:' 0 1 2 3 * ',recurring:false},'0 1 2 3 *',false],
  ])('compiles %j',(choice,cron,recurring)=>expect(scheduleValues(choice)).toEqual({cron,recurring}));
  it('validates time and interval',()=>{
    expect(()=>scheduleValues({time:'25:00'})).toThrow();
    expect(()=>scheduleValues({frequency:'interval',interval:'7'})).toThrow();
  });
  it('explains existing and advanced rules',()=>{
    expect(describeSchedule({cron:'0 9 * * *'})).toBe('每天 09:00');
    expect(describeSchedule({cron:'30 18 * * 1-5'})).toBe('周一至周五 18:30');
    expect(describeSchedule({cron:'0 9 * * 0',recurring:false})).toContain('下次匹配时执行一次');
    expect(describeSchedule({cron:'0 9 1 * *'})).toContain('自定义规则');
  });
  it('hides Cron by default and sends selected options',async()=>{
    const calls=[];const work={s:{crons:[]},safe:fn=>fn(),createCron:async body=>calls.push(body)};
    const panel=mount(CronPanel,{props:{work}});
    expect(panel.find('[aria-label="Cron 表达式"]').exists()).toBe(false);
    await panel.find('[aria-label="执行频率"]').setValue('workdays');
    await panel.find('[aria-label="执行时间"]').setValue('08:30');
    await panel.find('textarea').setValue('task');await panel.find('form').trigger('submit');await flushPromises();
    expect(calls[0]).toEqual({cron:'30 8 * * 1-5',prompt:'task',recurring:true,durable:true});
    await panel.find('[aria-label="执行频率"]').setValue('advanced');
    expect(panel.find('[aria-label="Cron 表达式"]').exists()).toBe(true);
  });
});
