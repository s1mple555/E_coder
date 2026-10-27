import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,copyFile,readdir,utimes,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';

test('deployment retains three complete builds and preserves unmanaged files',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'ecoder-deploy-test-'));
 try{
  const frontend=path.join(root,'frontend'),assets=path.join(root,'static/vue/assets'),dist=path.join(frontend,'dist');
  await mkdir(assets,{recursive:true});await mkdir(path.join(frontend,'scripts'),{recursive:true});await mkdir(path.join(dist,'assets'),{recursive:true});
  await copyFile(new URL('../frontend/scripts/deploy.mjs',import.meta.url),path.join(frontend,'scripts/deploy.mjs'));
  async function build(directory,version,time){
   const files={[`index-${version}.js`]:`import('./StoragePage-${version}.js');`,[`StoragePage-${version}.js`]:`import './index-${version}.js';`,[`index-${version}.css`]:'body{color:black}'};
   for(const [name,text] of Object.entries(files)){const file=path.join(directory,name);await writeFile(file,text);if(time)await utimes(file,time,time);}
   return `<script src="/static/vue/assets/index-${version}.js"></script><link href="/static/vue/assets/index-${version}.css">`;
  }
  await build(assets,'ancient',1000);await build(assets,'middle',2000);
  await writeFile(path.join(root,'static/index.html'),await build(assets,'old',3000));await writeFile(path.join(assets,'user-custom.js'),'user file');
  for(const version of ['new1','new2','new3']){
   for(const name of await readdir(path.join(dist,'assets')))await rm(path.join(dist,'assets',name));
   await writeFile(path.join(dist,'index.html'),await build(path.join(dist,'assets'),version));
   execFileSync(process.execPath,[path.join(frontend,'scripts/deploy.mjs')],{stdio:'pipe'});
  }
  const files=await readdir(assets);assert(files.includes('user-custom.js'));assert(!files.includes('index-old.js'));assert(!files.includes('index-ancient.js'));
  const manifest=JSON.parse(await readFile(path.join(root,'static/vue/deployments.json'),'utf8'));
  assert.equal(manifest.generations.length,3);
  for(const version of ['new1','new2','new3'])for(const file of [`index-${version}.js`,`index-${version}.css`,`StoragePage-${version}.js`])assert(files.includes(file));
  assert((await readFile(path.join(root,'static/index.html'),'utf8')).includes('index-new3.js'));
 }finally{
  const resolved=path.resolve(root);assert(resolved.startsWith(path.join(os.tmpdir(),'ecoder-deploy-test-')));
  await rm(resolved,{recursive:true,force:true});
 }
});
