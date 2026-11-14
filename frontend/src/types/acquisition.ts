export interface SideInfo {
 batch_id:string;
 unit:string;
 status:"open"|"published";
 current_samples:number;
}

export interface BatchGroup {
 batch_code:string;
 status:"open"|"published";
 published_pairing_id?:string;
 sides:Partial<Record<"x"|"y",SideInfo>>;
}

export interface PairRow {
 x_sample_no:string;
 y_sample_no:string;
 range_label:string;
 x:number;
 y:number;
 x_ts:string;
 y_ts:string;
 x_revision:number;
 y_revision:number;
 time_diff_seconds:number;
}

export interface UnmatchedRow {
 side:"x"|"y";
 sample_no:string;
 range_label:string;
 reason:"no_candidate"|"grabbed";
}

export interface PreviewResult {
 max_time_diff:number;
 unit:string;
 x_total:number;
 y_total:number;
 pair_count:number;
 total_time_diff:number;
 pairs:PairRow[];
 unmatched:UnmatchedRow[];
 reason_legend:Record<string,string>;
}

export interface PairingPreview {
 id:string;
 batch_code:string;
 max_time_diff:number;
 published_pairing_id:string;
 result:PreviewResult;
 created_at:string;
}

export interface PairingBatchSummary {
 id:string;
 name:string;
 batch_code:string;
 unit:string;
 max_time_diff:number;
 dataset_id:string;
 pair_count:number;
 created_at:string;
}
