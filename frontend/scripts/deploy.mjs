import {cp, mkdir, readFile, rename, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root=fileURLToPath(new URL('..',import.meta.url));
const output=path.resolve(root,'dist');
const target=path.resolve(root,'../static');
const html=await readFile(path.join(output,'index.html'),'utf8');
if(!html.includes('/static/vue/assets/'))throw new Error('Build the frontend before deploying.');
await mkdir(path.join(target,'vue'),{recursive:true});
// Keep earlier hashed assets: a tab open during deployment may still use them.
await cp(path.join(output,'assets'),path.join(target,'vue/assets'),{recursive:true});
await writeFile(path.join(target,'index.html.tmp'),html);
await rename(path.join(target,'index.html.tmp'),path.join(target,'index.html'));
console.log('Vue frontend deployed to static/.');
