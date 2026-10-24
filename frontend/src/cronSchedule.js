export const weekdays=['星期日','星期一','星期二','星期三','星期四','星期五','星期六'];
const pad=n=>String(n).padStart(2,'0');
export function scheduleValues({frequency='daily',time='09:00',weekday='1',interval='15',advanced='0 9 * * *',recurring=true}){
  if(frequency==='advanced') return {cron:advanced.trim(),recurring};
  const match=/^(\d{2}):(\d{2})$/.exec(time);
  if(!match||Number(match[1])>23||Number(match[2])>59) throw new Error('请选择有效的执行时间');
  const hour=Number(match[1]),minute=Number(match[2]);
  if(frequency==='interval'){
    if(!['5','10','15','20','30','60'].includes(String(interval))) throw new Error('请选择执行间隔');
    return {cron:String(interval)==='60'?'0 * * * *':`*/${interval} * * * *`,recurring:true};
  }
  if(frequency==='weekly'&&!/^[0-6]$/.test(String(weekday))) throw new Error('请选择星期');
  if(!['daily','workdays','weekly','once'].includes(frequency)) throw new Error('请选择执行频率');
  return {cron:`${minute} ${hour} * * ${frequency==='workdays'?'1-5':frequency==='weekly'?weekday:'*'}`,recurring:frequency!=='once'};
}
export function describeSchedule(job){
  const fields=(job.cron||'').trim().split(/\s+/);
  let description=`自定义规则：${job.cron}`;
  if(fields.length===5){
    const [m,h,d,month,w]=fields;
    if(d==='*'&&month==='*'){
      if(/^\d+$/.test(m)&&/^\d+$/.test(h)&&+m<60&&+h<24){
        const time=`${pad(h)}:${pad(m)}`;
        if(w==='*') description=`每天 ${time}`;
        else if(w==='1-5') description=`周一至周五 ${time}`;
        else if(/^[0-6]$/.test(w)) description=`每${weekdays[Number(w)]} ${time}`;
      }else if(h==='*'&&w==='*'){
        if(m==='0') description='每小时整点';
        else if(/^\*\/(5|10|15|20|30)$/.test(m)) description=`每 ${m.slice(2)} 分钟（按整点对齐）`;
      }
    }
  }
  return job.recurring===false?`下次匹配时执行一次 · ${description}`:description;
}
