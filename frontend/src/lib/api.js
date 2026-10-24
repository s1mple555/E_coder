export async function api(path,options={}) {
  const headers=options.body instanceof FormData ? {} : {'Content-Type':'application/json'};
  const response=await fetch(path,{...options,headers:{...headers,...options.headers}});
  if(!response.ok){
    let detail;try{detail=(await response.json()).detail;}catch{}
    throw new Error(typeof detail==='string'?detail:`请求失败（${response.status}）`);
  }
  return response.json();
}
export const action=(path,body={})=>api(path,{method:'POST',body:JSON.stringify(body)});
export const formatSize=value=>value<1024?`${value} B`:value<1048576?`${(value/1024).toFixed(1)} KB`:`${(value/1048576).toFixed(1)} MB`;
export const imageFile=file=>['image/png','image/jpeg','image/webp','image/gif'].includes(file.mime);
export const fileUrl=(session,file)=>`/api/sessions/${session}/content?${file.id?`attachment=${encodeURIComponent(file.id)}`:`path=${encodeURIComponent(file.path)}`}`;
export const pretty=value=>{try{return JSON.stringify(typeof value==='string'?JSON.parse(value):value,null,2);}catch{return String(value??'');}};
