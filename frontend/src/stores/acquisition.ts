import {reactive} from "vue";
import * as api from "../api/acquisition";
import type {BatchGroup,PairingPreview,PairingBatchSummary} from "../types/acquisition";

export const acquisition=reactive({
 groups:[] as BatchGroup[],
 pairings:[] as PairingBatchSummary[],
 loading:false,
 error:"",
});

export const previewMap=reactive<Record<string,PairingPreview>>({});

export async function loadGroups(){
 acquisition.loading=true;acquisition.error="";
 try{acquisition.groups=await api.fetchBatchGroups()}
 catch(e){acquisition.error=(e as Error).message}
 finally{acquisition.loading=false}
}

export async function loadPairings(){
 try{acquisition.pairings=await api.fetchPairings()}
 catch(e){acquisition.error=(e as Error).message}
}

export async function ingest(body:api.IngestBody){
 const r=await api.ingestStream(body);
 await loadGroups();
 return r;
}

export async function refreshPreview(code:string,timeDiff:number){
 const r=await api.computePreview(code,timeDiff) as PairingPreview;
 previewMap[code]=r;
 await loadGroups();
 return r;
}

export async function loadPreview(code:string){
 try{previewMap[code]=await api.fetchPreview(code)}
 catch{ /* 尚未生成预览时静默 */ }
}

export async function publish(code:string,name:string,description:string){
 const r=await api.publishPairing(code,name,description);
 await Promise.all([loadGroups(),loadPairings(),loadPreview(code)]);
 return r;
}
