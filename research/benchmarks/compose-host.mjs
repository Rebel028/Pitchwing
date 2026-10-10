// Original minimal wasm32 CLAP host, for public-API measurements only.
// Uses the public WebCLAP WASI implementation and typed-callback helper.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const hostDir=process.env.WEBCLAP_HOST || path.resolve(here,'../forensics/browser-test-host');
const {startWasi}=await import(pathToFileURL(path.join(hostDir,'clap-audionode/wclap-js/es6/wasi/wasi.mjs')));
const {default: forwarding}=await import(pathToFileURL(path.join(hostDir,'clap-audionode/wclap-js/es6/generate-forwarding-wasm.mjs')));
const wasiModule=await WebAssembly.compile(await fs.readFile(path.join(hostDir,'clap-audionode/wclap-js/es6/wasi/wasi.wasm')));
export async function createHost(binaryPath, pluginIndex=0, sampleRate=48000, blockSize=128, initialParams={}) {
  const memory=new WebAssembly.Memory({initial:8,maximum:32768,shared:true});
  const wasi=await startWasi({module:wasiModule,seedString:'compose-public-api-benchmark'});
  wasi.bindToOtherMemory(memory);
  const module=await WebAssembly.compile(await fs.readFile(binaryPath));
  const instance=await WebAssembly.instantiate(module,{env:{memory},...wasi.importObj});
  instance.exports._initialize();
  const table=instance.exports.__indirect_function_table;
  const dv=()=>new DataView(memory.buffer);
  const u32=(ptr)=>dv().getUint32(ptr,true);
  const set=(ptr,v)=>dv().setUint32(ptr,v,true);
  const alloc=n=>{const p=instance.exports.malloc(n);new Uint8Array(memory.buffer,p,n).fill(0);return p};
  const str=s=>{let b=new TextEncoder().encode(s+'\0'),p=alloc(b.length);new Uint8Array(memory.buffer,p,b.length).set(b);return p};
  const read=p=>{const b=new Uint8Array(memory.buffer);let q=p;while(b[q])q++;return new TextDecoder().decode(b.slice(p,q))};
  const call=(ptr,...args)=>table.get(u32(ptr))(...args);
  let callbackRequested=false;
  let pendingEvents=[];
  const callbacks={getExtension:()=>0,restart:()=>{},process:()=>{},callback:()=>{callbackRequested=true},eventSize:()=>pendingEvents.length,eventGet:(_,i)=>pendingEvents[i]||0,eventPush:()=>1};
  const sigs={getExtension:'III',restart:'vI',process:'vI',callback:'vI',eventSize:'II',eventGet:'III',eventPush:'III'};
  const bridge=new WebAssembly.Instance(new WebAssembly.Module(forwarding(sigs)),{proxy:callbacks});
  const idx={};for(const k of Object.keys(callbacks)){idx[k]=table.length;table.grow(1);table.set(idx[k],bridge.exports[k]);}
  const host=alloc(48);set(host,1);set(host+4,2);set(host+8,7);
  set(host+16,str('Reproducible public CLAP benchmark'));set(host+20,str('Independent research'));set(host+24,str(''));set(host+28,str('0.1'));
  set(host+32,idx.getExtension);set(host+36,idx.restart);set(host+40,idx.process);set(host+44,idx.callback);
  const entry=Number(instance.exports.clap_entry.value);
  if(!call(entry+12,str(binaryPath)))throw Error('CLAP entry init failed');
  const factory=call(entry+20,str('clap.plugin-factory'));
  const count=call(factory,factory),descriptors=[];
  for(let i=0;i<count;i++){const d=call(factory+4,factory,i);descriptors.push({id:read(u32(d+12)),name:read(u32(d+16)),vendor:read(u32(d+20)),version:read(u32(d+36))});}
  const plugin=call(factory+8,factory,host,str(descriptors[pluginIndex].id));
  if(!plugin || !call(plugin+8,plugin))throw Error('CLAP plugin init failed');
  const extension=name=>call(plugin+40,plugin,str(name));
  const paramExt=extension('clap.params'),params=[];
  if(paramExt){const n=call(paramExt,plugin),p=alloc(1320);for(let i=0;i<n;i++){if(!call(paramExt+4,plugin,i,p))continue;params.push({id:u32(p),flags:u32(p+4),name:read(p+12),module:read(p+268),min:dv().getFloat64(p+1296,true),max:dv().getFloat64(p+1304,true),default:dv().getFloat64(p+1312,true)});}}
  const inEvents=alloc(12);set(inEvents+4,idx.eventSize);set(inEvents+8,idx.eventGet);
  const outEvents=alloc(8);set(outEvents+4,idx.eventPush);
  const event=alloc(48);
  const setParam=(id,value)=>{new Uint8Array(memory.buffer,event,48).fill(0);set(event,48);dv().setUint16(event+10,5,true);set(event+16,id);dv().setInt32(event+24,-1,true);dv().setInt16(event+28,-1,true);dv().setInt16(event+30,-1,true);dv().setInt16(event+32,-1,true);dv().setFloat64(event+40,value,true);pendingEvents=[event];call(paramExt+20,plugin,inEvents,outEvents);pendingEvents=[];};
  const getParam=id=>{const p=alloc(8);call(paramExt+8,plugin,id,p);return dv().getFloat64(p,true)};
  const getParamText=(id,value=getParam(id))=>{const p=alloc(256);return call(paramExt+12,plugin,id,value,p,256)?read(p):null};
  for(const [name,value] of Object.entries(initialParams)){const param=params.find(p=>p.name===name);if(!param)throw Error('Unknown parameter '+name);setParam(param.id,value);}
  if(!call(plugin+16,plugin,sampleRate,1,blockSize))throw Error('activate failed');
  if(!call(plugin+24,plugin))throw Error('start processing failed');
  const latencyExt=extension('clap.latency');
  const reportedLatency=()=>latencyExt?call(latencyExt,plugin):null;
  const ports=extension('clap.audio-ports');
  function buffers(isInput){const n=call(ports,plugin,isInput?1:0),p=alloc(24*n),result=[];const info=alloc(280);for(let i=0;i<n;i++){call(ports+4,plugin,i,isInput?1:0,info);const channels=u32(info+264),pointers=alloc(channels*4),ptrs=[];for(let c=0;c<channels;c++){const a=alloc(blockSize*4);set(pointers+c*4,a);ptrs.push(a);}set(p+i*24,pointers);set(p+i*24+8,channels);result.push(ptrs);}return {p,n,ptrs:result};}
  const inputs=buffers(true),outputs=buffers(false),processStruct=alloc(40);
  const transport=alloc(104);set(transport,104);dv().setUint16(transport+10,9,true);set(processStruct+12,transport);
  dv().setBigInt64(processStruct,-1n,true);set(processStruct+16,inputs.p);set(processStruct+20,outputs.p);set(processStruct+24,inputs.n);set(processStruct+28,outputs.n);set(processStruct+32,inEvents);set(processStruct+36,outEvents);
  const processBlock=(input)=>{const n=input.length;set(processStruct+8,n);for(const port of inputs.ptrs)for(const p of port)new Float32Array(memory.buffer,p,n).set(input);const status=call(plugin+36,plugin,processStruct);if(status===0)throw Error('CLAP_PROCESS_ERROR');if(callbackRequested){callbackRequested=false;call(plugin+44,plugin);}return outputs.ptrs.map(port=>port.map(p=>new Float32Array(memory.buffer,p,n).slice()));};
  const close=()=>{call(plugin+28,plugin);call(plugin+20,plugin);call(plugin+12,plugin);call(entry+16)};
  return {descriptors,params,reportedLatency,processBlock,setParam,getParam,getParamText,close,inputs:inputs.ptrs.map(p=>p.length),outputs:outputs.ptrs.map(p=>p.length),processFunctionTableIndex:u32(plugin+36)};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 const binary=process.argv[2]||path.resolve(here,'../forensics/compose-2026-10-01.wclap.wasm');
 const h=await createHost(binary,Number(process.argv[3]||0));
 console.log(JSON.stringify({descriptors:h.descriptors,params:h.params,latency:h.reportedLatency(),inputs:h.inputs,outputs:h.outputs,processFunctionTableIndex:h.processFunctionTableIndex},null,2));
 const result=h.processBlock(new Float32Array(128));console.log(result.map(p=>p.map(c=>c.slice(0,8))));h.close();
}
