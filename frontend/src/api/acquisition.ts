import {request} from "./client";

export interface SampleEntry {
 sample_no:string;
 sampled_at:string;
 range_label:string;
 reading:number;
 revision:number;
}

export interface IngestBody {
 batch_code:string;
 side:"x"|"y";
 unit:string;
 samples?:SampleEntry[];
 csv_text?:string;
}

export const fetchBatchGroups=()=>request("/acquisition/batches");
export const fetchBatchDetail=(code:string)=>request("/acquisition/batches/"+encodeURIComponent(code));
export const ingestStream=(body:IngestBody)=>request("/acquisition/ingest","POST",body);
export const computePreview=(code:string,max_time_diff:number)=>
 request("/acquisition/batches/"+encodeURIComponent(code)+"/preview","POST",{max_time_diff});
export const fetchPreview=(code:string)=>
 request("/acquisition/batches/"+encodeURIComponent(code)+"/preview");
export const publishPairing=(code:string,name:string,description:string)=>
 request("/acquisition/batches/"+encodeURIComponent(code)+"/publish","POST",{name,description});
export const fetchPairings=()=>request("/acquisition/pairings");
export const fetchPairing=(id:string)=>request("/acquisition/pairings/"+id);
