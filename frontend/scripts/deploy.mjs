import {cp,mkdir,readFile,rename,writeFile,readdir,stat,realpath,unlink} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root=fileURLToPath(new URL('..',import.meta.url));
const output=path.resolve(root,'dist');
const target=path.resolve(root,'../static');
const assets=path.join(target,'vue/assets');
const manifest=path.join(target,'vue/deployments.json');
const managed=name=>/^(?:index|StoragePage)-[\w-]+\.(?:js|css)$/.test(name);
const html=await readFile(path.join(output,'index.html'),'utf8');
if(!html.includes('/static/vue/assets/'))throw new Error('Build the frontend before deploying.');
await mkdir(assets,{recursive:true});
if((await realpath(assets)).toLowerCase()!==path.resolve(assets).toLowerCase())throw new Error('Refuse cleanup through a linked assets directory.');
async function generation(entryNames){
  const found=new Set();
  async function visit(name){
    if(!managed(name)||found.has(name))return;
    const resolved=path.resolve(assets,name);
    if(path.dirname(resolved)!==assets)throw new Error('Asset path escaped deployment directory.');
    let source;try{source=await readFile(resolved,'utf8');}catch(error){if(error.code==='ENOENT')return;throw error;}
    found.add(name);
    for(const match of source.matchAll(/["'`]?(?:\.\/)?((?:index|StoragePage)-[\w-]+\.(?:js|css))["'`]/g))await visit(match[1]);
  }
  for(const name of entryNames)await visit(name);
  return [...found].sort();
}
let previousHtml='';try{previousHtml=await readFile(path.join(target,'index.html'),'utf8');}catch(error){if(error.code!=='ENOENT')throw error;}
const previous=await generation([...previousHtml.matchAll(/\/static\/vue\/assets\/([^"']+\.(?:js|css))/g)].map(match=>match[1]));
let history=[];try{history=JSON.parse(await readFile(manifest,'utf8')).generations||[];}catch(error){if(error.code!=='ENOENT'&&!(error instanceof SyntaxError))throw error;}
if(!history.length){
  const existing=await Promise.all((await readdir(assets)).filter(managed).map(async name=>({name,time:(await stat(path.join(assets,name))).mtimeMs})));
  const older=existing.filter(item=>item.name.startsWith('index-')&&item.name.endsWith('.js')&&!previous.includes(item.name)).sort((a,b)=>b.time-a.time)[0];
  if(older){const css=existing.filter(item=>item.name.endsWith('.css')).sort((a,b)=>Math.abs(a.time-older.time)-Math.abs(b.time-older.time))[0];history.push(await generation([older.name,...(css?[css.name]:[])]));}
}
await cp(path.join(output,'assets'),assets,{recursive:true});
const next=(await readdir(path.join(output,'assets'))).filter(managed).sort();
const generations=[];
for(const files of [next,previous,...history]){
  const checked=Array.isArray(files)?files.filter(managed).sort():[];
  if(checked.length&&!generations.some(kept=>JSON.stringify(kept)===JSON.stringify(checked)))generations.push(checked);
  if(generations.length===3)break;
}
await writeFile(path.join(target,'index.html.tmp'),html);
await rename(path.join(target,'index.html.tmp'),path.join(target,'index.html'));
await writeFile(manifest,JSON.stringify({generations},null,2)+'\n');
const keep=new Set(generations.flat());let removed=0;
for(const name of await readdir(assets)){
  if(!managed(name)||keep.has(name))continue;
  const resolved=path.resolve(assets,name);
  if(path.dirname(resolved)!==assets)throw new Error('Invalid cleanup target.');
  await unlink(resolved);removed++;
}
console.log(`Vue frontend deployed; retained ${generations.length} builds, removed ${removed} obsolete assets.`);
