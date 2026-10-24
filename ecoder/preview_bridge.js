(()=>{
const token=__TOKEN__,entry=__ENTRY__;let enabled=true,last;
const box=document.createElement('div');box.style.cssText='position:fixed;pointer-events:none;z-index:2147483647;border:2px solid #6366cf;background:#6366cf14;display:none';
function selector(el){const parts=[];for(let i=0;el&&el.nodeType===1&&i<6;i++,el=el.parentElement){if(el.id){parts.unshift('#'+CSS.escape(el.id));break;}const tag=el.tagName.toLowerCase();const peers=el.parentElement?[...el.parentElement.children].filter(x=>x.tagName===el.tagName):[];parts.unshift(tag+(peers.length>1?`:nth-of-type(${peers.indexOf(el)+1})`:''));}return parts.join(' > ');}
function hide(){box.style.display='none';}
addEventListener('DOMContentLoaded',()=>document.body.append(box));
addEventListener('message',e=>{if(e.source===parent&&e.data?.token===token&&e.data?.type==='ecoder:mode'){enabled=!!e.data.enabled;if(!enabled)hide();}});
addEventListener('mouseover',e=>{if(!enabled||e.target===box)return;last=e.target;const r=last.getBoundingClientRect();Object.assign(box.style,{display:'block',left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});},true);
addEventListener('scroll',hide,true);
addEventListener('click',e=>{if(!enabled)return;e.preventDefault();e.stopImmediatePropagation();const el=e.target,r=el.getBoundingClientRect();parent.postMessage({type:'ecoder:annotation',token,entry,selector:selector(el),text:(el.innerText||el.textContent||'').trim().slice(0,500),component:el.getAttribute('data-component')||'',source:el.getAttribute('data-source')||'',rect:{x:r.x,y:r.y,width:r.width,height:r.height},viewport:{width:innerWidth,height:innerHeight}},'*');},true);
})();
