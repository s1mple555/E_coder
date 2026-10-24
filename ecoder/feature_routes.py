import secrets
import time
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import HTMLResponse,FileResponse
from pydantic import BaseModel,Field,ConfigDict
from .preview import Preview

class Model(BaseModel):model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Extract(Model):
    run_id:str=Field(max_length=80)
    confirmed:bool=False
class Toggle(Model):enabled:bool
class Entry(Model):entry:str=Field(min_length=1,max_length=500)
class Annotation(Entry):
    revision:str=Field(min_length=64,max_length=64)
    selector:str=Field(min_length=1,max_length=2000)
    text:str=Field(default='',max_length=500)
    component:str=Field(default='',max_length=200)
    source:str=Field(default='',max_length=500)
    note:str=Field(min_length=1,max_length=4000,pattern=r'\S')
    rect:dict[str,float]=Field(max_length=4)
    viewport:dict[str,float]=Field(max_length=2)
class Submission(Model):ids:list[str]=Field(min_length=1,max_length=30)
class State(Model):status:Literal['resolved','dismissed']

def routes(runtime,require):
    router=APIRouter(prefix='/api/sessions/{session}')
    preview=Preview(runtime);tokens={}
    def checked(session,token):
        value=tokens.get(token)
        if not value or value['session']!=session or value['expires']<time.time():raise HTTPException(404,'预览已过期，请刷新')
        if value['scope']!=runtime.learning.scope(session):raise HTTPException(409,'工作区已切换，请刷新预览')
        return value
    @router.get('/experiences')
    def experiences(session:str):require(session);return {'experiences':runtime.learning.list(session)}
    @router.post('/experiences/extract')
    async def extract(session:str,body:Extract):
        require(session)
        try:
            runtime.ensure_idle(session)
            return {'experiences':await runtime.learning.extract(session,body.run_id,body.confirmed)}
        except (ValueError,TimeoutError):raise HTTPException(400,'无法提取：请确认轮次已成功完成且含工具证据；模型必须返回有效经验与证据引用')
    @router.patch('/experiences/{identifier}')
    def toggle(session:str,identifier:str,body:Toggle):
        require(session)
        try:return runtime.learning.update(session,identifier,body.enabled)
        except ValueError as e:raise HTTPException(400,str(e))
    @router.post('/preview')
    def create(session:str,body:Entry,request:Request):
        require(session)
        try:
            entry=preview.asset(session,body.entry).relative_to(preview.tools(session).root).as_posix()
            if not entry.lower().endswith(('.html','.htm')):raise ValueError('请先构建前端，选择 index.html 或 dist/index.html')
            token=secrets.token_urlsafe(32)
            for key in list(tokens):
                if tokens[key]['expires']<time.time():tokens.pop(key)
            if len(tokens)>500:tokens.pop(next(iter(tokens)))
            tokens[token]={'session':session,'entry':entry,'scope':runtime.learning.scope(session),'expires':time.time()+1800}
            return {'entry':entry,'token':token,'revision':preview.digest(session,entry),'url':f'/api/sessions/{session}/preview/document/{token}'}
        except (ValueError,OSError) as e:raise HTTPException(400,str(e))
    @router.get('/preview/document/{token}')
    def document(session:str,token:str,request:Request):
        require(session);value=checked(session,token)
        try:html=preview.document(session,value['entry'],token,str(request.base_url).rstrip('/'))
        except (ValueError,OSError) as e:raise HTTPException(400,str(e))
        prefix=str(request.base_url).rstrip('/')+f'/api/sessions/{session}/preview/assets/{token}/'
        csp=f"default-src 'none'; script-src 'unsafe-inline' {prefix}; style-src 'unsafe-inline' {prefix}; img-src data: blob: {prefix}; font-src data: {prefix}; connect-src {prefix}; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri {prefix}; sandbox allow-scripts"
        return HTMLResponse(html,headers={'Content-Security-Policy':csp,'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    @router.get('/preview/assets/{token}/{path:path}')
    def asset(session:str,token:str,path:str):
        require(session);checked(session,token)
        try:return FileResponse(preview.asset(session,path),headers={'Cache-Control':'no-store','Access-Control-Allow-Origin':'null','Content-Security-Policy':"sandbox; default-src 'none'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
        except (ValueError,OSError):raise HTTPException(404,'预览资源不存在或不可读取')
    @router.get('/annotations')
    def annotations(session:str):require(session);return {'annotations':preview.list(session)}
    @router.post('/annotations')
    def save(session:str,body:Annotation):
        require(session)
        try:return preview.save(session,body.model_dump())
        except (ValueError,OSError) as e:raise HTTPException(400,str(e))
    @router.patch('/annotations/{identifier}')
    def state(session:str,identifier:str,body:State):
        require(session)
        try:return preview.state(session,identifier,body.status)
        except ValueError as e:raise HTTPException(400,str(e))
    @router.post('/annotations/submit')
    async def submit(session:str,body:Submission):
        require(session)
        try:runtime.ensure_idle(session);return preview.submit(session,body.ids)
        except (ValueError,OSError) as e:raise HTTPException(409,str(e))
    return router
