import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {createHost} from './compose-host.mjs';
// Suppress only the demo's two known per-block diagnostic print lines.
const rawLog=console.log;let suppressedDiagnosticLines=0;console.log=(...args)=>{if(typeof args[0]==='string'&&/^(process->transport =|float\(process->transport->tempo\) =)/.test(args[0])){suppressedDiagnosticLines++;return;}rawLog(...args);};
const here=path.dirname(fileURLToPath(import.meta.url));
const binary=process.argv[2]||path.resolve(here,'../forensics/compose-2026-10-01.wclap.wasm');
const out=process.argv[3]||path.join(here,'results');await fs.mkdir(out,{recursive:true});
const sr=48000,block=128,shifts=[-12,-7,-2,0,7,12];
const init=await createHost(binary);const params=init.params.map(p=>({...p,current:init.getParam(p.id),display:init.getParamText(p.id)}));
const latencyParam=params.find(p=>p.name==='latency');
const latencyMap=Array.from({length:11},(_,i)=>({normalized:i/10,display:init.getParamText(latencyParam.id,i/10)}));
const metadata={date:new Date().toISOString(),binarySha256:crypto.createHash('sha256').update(await fs.readFile(binary)).digest('hex'),binaryFilename:path.basename(binary),node:process.version,platform:process.platform,arch:process.arch,cpu:os.cpus()[0]?.model||'unavailable',sampleRate:sr,blockSize:block,descriptors:init.descriptors,params,latencyMap,scope:'Synthetic public-API tests; no listening or comparison to Neural DSP. Wall CPU timing includes JS host and WASM overhead.'};
init.close();
const cases=[];
function makeInput(type){const n=sr*2,input=new Float32Array(n),onset=8192;for(let i=0;i<n;i++){const t=(i-onset)/sr;if(t<0)continue;if(type==='impulse'){if(i===onset)input[i]=0.5;continue;}if(type==='sine110'||type==='automation'){input[i]=0.4*Math.sin(2*Math.PI*110*t);continue;}let v=0;for(const f of [82.406889,123.470825,164.813778,207.652349,246.941651,329.627557])for(let h=1;h<=6;h++)v+=Math.sin(2*Math.PI*f*h*t)/(6*h*4);input[i]=v;}return{input,onset};}
for(const type of ['impulse','sine110','chord','automation'])for(const shift of type==='automation'?[0]:shifts){const h=await createHost(binary,0,sr,block,{semitones:shift});const {input,onset}=makeInput(type),output=new Float32Array(input.length);const id=h.params.find(p=>p.name==='semitones').id;const latency=h.reportedLatency();const times=[];for(let i=0;i<input.length;i+=block){if(type==='automation'&&i===48000)h.setParam(id,-7);const b=input.subarray(i,Math.min(i+block,input.length));const t=performance.now();const y=h.processBlock(b);times.push(performance.now()-t);output.set(y[0][0],i);}const name=`${type}_${shift}`;await fs.writeFile(path.join(out,name+'.f32'),new Uint8Array(output.buffer));const sum=times.reduce((a,b)=>a+b,0);times.sort((a,b)=>a-b);cases.push({name,type,shift,inputOnsetSample:onset,reportedLatencySamples:latency,outputFile:name+'.f32',durationSeconds:input.length/sr,totalWallMs:sum,realtimeFactor:sum/(input.length/sr*1000),blockP50Ms:times[Math.floor(times.length*.5)],blockP99Ms:times[Math.floor(times.length*.99)],blockMaxMs:times.at(-1),automation:type==='automation'?{sample:48000,from:0,to:-7}:null});h.close();console.error('completed',name);}
await fs.writeFile(path.join(out,'metadata.json'),JSON.stringify({...metadata,suppressedDiagnosticLines,cases},null,2)+'\n');
