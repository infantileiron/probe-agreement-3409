<script setup lang="ts">
import {ref,computed,onMounted} from 'vue';
import {datasets} from '../stores/datasets';
import {canWrite} from '../stores/auth';
import {useTask} from '../hooks/useTask';
import {units,rangeBands,rangeLabels} from '../constants/enums';
import PageHeading from '../components/common/PageHeading.vue';
import Notice from '../components/common/Notice.vue';
import PairTable from '../components/PairTable.vue';
import {
 acquisition,previewMap,loadGroups,loadPairings,loadPreview,ingest,refreshPreview,publish,
} from '../stores/acquisition';
import type {BatchGroup,PairingPreview,UnmatchedRow} from '../types/acquisition';

const tab=ref<'stream'|'csv'>('stream');
const {error,busy,act}=useTask();
onMounted(()=>{datasets.load();loadGroups();loadPairings()});

/* ---- 流水接收表单 ---- */
const batchCode=ref(''),side=ref<'x'|'y'>('x'),unit=ref('kPa'),csvText=ref('');
const ingestMsg=ref('');
async function pickFile(e:Event){
 const f=(e.target as HTMLInputElement).files?.[0];
 if(f)csvText.value=await f.text();
}
function submitIngest(){
 ingestMsg.value='';
 act(async()=>{
  if(!batchCode.value.trim())throw new Error('请填写采集批次号');
  const r=await ingest({batch_code:batchCode.value.trim(),side:side.value,
   unit:unit.value,csv_text:csvText.value});
  ingestMsg.value=`已接收：新增 ${r.inserted} 条，重复跳过 ${r.skipped_duplicate} 条，取代 ${r.superseded} 条，当前 ${r.current_samples} 条（${side.value.toUpperCase()} 侧）`;
  csvText.value='';
 });
}

/* ---- 预览与发布 ---- */
const timeDiff=ref(30),publishName=ref(''),publishDesc=ref(''),publishMsg=ref('');
const selected=ref('');
const selectedGroup=computed<BatchGroup|undefined>(()=>
 acquisition.groups.find(g=>g.batch_code===selected.value));
const preview=computed<PairingPreview|undefined>(()=>
 selected.value?previewMap[selected.value]:undefined);
function selectGroup(code:string){
 selected.value=selected.value===code?'':code;
 publishMsg.value='';
 if(selected.value)loadPreview(selected.value);
}
function doPreview(){
 publishMsg.value='';
 act(async()=>{
  if(selected.value)await refreshPreview(selected.value,Number(timeDiff.value));
 });
}
function doPublish(){
 publishMsg.value='';
 act(async()=>{
  if(!selected.value)return;
  const name=publishName.value.trim()||`配对批次 ${selected.value}`;
  const r=await publish(selected.value,name,publishDesc.value);
  publishMsg.value=r.idempotent
   ?`该预览已发布，返回同一份不可变批次 ${r.id}`
   :`已生成不可变配对批次 ${r.id}（${r.pair_count} 组），并写入下游配对数据集`;
 });
}
const reasonText=(r:UnmatchedRow)=>r.reason==='no_candidate'?'时差窗内无候选':'候选被抢配';
const bothSides=(g?:BatchGroup)=>!!g?.sides.x&&!!g?.sides?.y;

/* ---- 既有已配对 CSV 导入 ---- */
const csvName=ref(''),csvPairs=ref(''),csvUnit=ref('kPa');
async function pickCsv(e:Event){
 const f=(e.target as HTMLInputElement).files?.[0];
 if(f)csvPairs.value=await f.text();
}
function submitCsv(){
 act(async()=>{
  await datasets.create({name:csvName.value,x_unit:csvUnit.value,y_unit:csvUnit.value,
   csv_text:csvPairs.value,description:'由已配对 CSV 导入'});
  csvName.value='';csvPairs.value='';
 });
}
</script>

<template>
 <PageHeading index="01 / 配对观测" title="两探头采样流水，分侧接收、按时差自动配对。"
  note="按采集批次分侧导入 sample_no,sampled_at,range_label,reading,revision；按量程与可设时差配对，采样只用一次，先求配对最多再求总时差最小。"/>
 <div class="tab-strip">
  <button :class="{secondary:tab!=='stream'}" @click="tab='stream'">采样流水配对</button>
  <button :class="{secondary:tab!=='csv'}" @click="tab='csv'">已配对 CSV 导入</button>
 </div>

 <div v-if="tab==='stream'" class="two-col">
  <section>
   <Notice :message="acquisition.error||error"/>
   <p v-if="ingestMsg" class="success">{{ingestMsg}}</p>
   <article v-for="g in acquisition.groups" :key="g.batch_code" class="dataset-row">
    <button class="record-open" @click="selectGroup(g.batch_code)">
     <h3>{{g.batch_code}}
      <span class="status" :class="g.status" style="margin-left:10px">{{g.status==='published'?'已发布':'接收中'}}</span>
     </h3>
     <p>
      X 侧 {{g.sides.x?.current_samples??0}} 条 · Y 侧 {{g.sides.y?.current_samples??0}} 条
      · 单位 {{g.sides.x?.unit||g.sides.y?.unit||'—'}}
     </p>
     <span>配对预览与未配对原因 ↗</span>
    </button>

    <div v-if="selected===g.batch_code" class="preview-box">
     <template v-if="preview">
      <div class="metric-strip" style="margin:14px 0">
       <div><small>配对数</small><strong>{{preview.result.pair_count}}</strong><span>先求最多</span></div>
       <div><small>总时差(秒)</small><strong>{{preview.result.total_time_diff}}</strong><span>再求最小</span></div>
       <div><small>未配对</small><strong>{{preview.result.unmatched.length}}</strong>
        <span>X {{preview.result.x_total}} / Y {{preview.result.y_total}}</span></div>
      </div>
      <div class="table-wrap">
       <table>
        <thead><tr><th>X 采样</th><th>Y 采样</th><th>量程</th><th>X 读数</th><th>Y 读数</th>
         <th>时差(s)</th><th>修订 X/Y</th></tr></thead>
        <tbody>
         <tr v-for="(p,i) in preview.result.pairs.slice(0,40)" :key="i">
          <td>{{p.x_sample_no}}</td><td>{{p.y_sample_no}}</td>
          <td>{{rangeLabels[p.range_label]}}</td><td>{{p.x}}</td><td>{{p.y}}</td>
          <td>{{p.time_diff_seconds}}</td><td>{{p.x_revision}}/{{p.y_revision}}</td>
         </tr>
        </tbody>
       </table>
      </div>
      <p v-if="preview.result.pair_count>40" class="success">
       仅展示前 40 组，共 {{preview.result.pair_count}} 组，发布快照保留全部。</p>
      <h3 v-if="preview.result.unmatched.length" style="margin-top:18px">未配对样本与原因</h3>
      <div class="table-wrap" v-if="preview.result.unmatched.length">
       <table>
        <thead><tr><th>侧</th><th>采样编号</th><th>量程</th><th>原因</th></tr></thead>
        <tbody>
         <tr v-for="(u,i) in preview.result.unmatched" :key="i">
          <td>{{u.side.toUpperCase()}}</td><td>{{u.sample_no}}</td>
          <td>{{rangeLabels[u.range_label]}}</td><td>{{reasonText(u)}}</td>
         </tr>
        </tbody>
       </table>
      </div>
     </template>
     <p v-else class="empty" style="padding:18px">两侧流水接收后，设置时差并生成预览。</p>

     <div v-if="canWrite()&&g.status!=='published'" class="preview-actions">
      <label style="min-width:200px">最大时差(秒)
       <input type="number" min="0" max="86400" v-model.number="timeDiff">
      </label>
      <button :disabled="busy||!bothSides(g)" @click="doPreview">按量程与时差配对</button>
     </div>
     <div v-if="canWrite()&&preview&&g.status!=='published'" class="preview-actions">
      <input v-model="publishName" :placeholder="`配对批次 ${g.batch_code}`" style="flex:1">
      <input v-model="publishDesc" placeholder="批次说明（可选）" style="flex:1">
      <button :disabled="busy||preview.result.pair_count<4" @click="doPublish">发布不可变批次</button>
     </div>
     <p v-if="preview&&preview.result.pair_count<4" class="notice" style="margin-top:10px">
      至少 4 组配对才能发布（当前 {{preview.result.pair_count}} 组）。</p>
     <p v-if="publishMsg" class="success">{{publishMsg}}</p>
     <p v-if="g.status==='published'" class="success">
      已发布不可变配对批次 {{g.published_pairing_id}}；后续补传修订不改变已发布批次与关联研究。</p>
    </div>
   </article>

   <h2 style="margin-top:30px">已发布配对批次</h2>
   <article v-for="p in acquisition.pairings" :key="p.id" class="dataset-row">
    <h3 style="font-size:15px">{{p.name}}</h3>
    <p>{{p.pair_count}} 组 · {{p.unit}} · 时差窗 {{p.max_time_diff}}s · 来源批次 {{p.batch_code}} · {{p.created_at}}</p>
   </article>
   <p v-if="!acquisition.groups.length" class="empty">尚无采集批次，从右侧分侧上传采样流水。</p>
  </section>

  <form v-if="canWrite()" class="editor-panel" @submit.prevent="submitIngest">
   <h2>分侧接收采样流水</h2>
   <label>采集批次号<input v-model="batchCode" required placeholder="如 FIELD-20261112-A"></label>
   <label>探头侧别
    <select v-model="side"><option value="x">X 侧探头</option><option value="y">Y 侧探头</option></select>
   </label>
   <label>单位<select v-model="unit"><option v-for="u in units" :key="u">{{u}}</option></select></label>
   <label>量程口径
    <select disabled><option v-for="b in rangeBands" :key="b">{{rangeLabels[b]}}（{{b}}）</option></select>
   </label>
   <label>流水 CSV（含修订号）<input type="file" accept=".csv" @change="pickFile"></label>
   <label>采样流水文本<textarea v-model="csvText" rows="8" required
    placeholder="sample_no,sampled_at,range_label,reading,revision"></textarea></label>
   <Notice :message="error"/>
   <button :disabled="busy">接收本侧流水</button>
   <p class="success" style="font-size:10px;line-height:1.9">
    重复上传不新增样本；旧修订晚到不覆盖新值；同编号同修订内容冲突将整批拒绝。乱序补传可直接再次上传。</p>
  </form>
  <aside v-else class="field-note">只读账号可核查流水与配对结果，导入需要分析师权限。</aside>
 </div>

 <div v-else class="two-col">
  <section>
   <Notice :message="datasets.error.value"/>
   <article v-for="r in datasets.items.value" :key="r.id" class="dataset-row">
    <button class="record-open" @click="selected=selected===r.id?'':r.id">
     <h3>{{r.name}}</h3>
     <p>{{r.pairs.length}}组 · X/Y={{r.x_unit}}/{{r.y_unit}} · {{r.description}}</p>
     <span>预览成对读数 ↗</span>
    </button>
    <PairTable v-if="selected===r.id" :rows="r.pairs.slice(0,16)"/>
   </article>
  </section>
  <form v-if="canWrite()" class="editor-panel" @submit.prevent="submitCsv">
   <h2>导入配对批次</h2>
   <label>批次名称<input v-model="csvName" required minlength="2"></label>
   <label>共同单位<select v-model="csvUnit"><option v-for="u in units" :key="u">{{u}}</option></select></label>
   <label>CSV文件<input type="file" accept=".csv" @change="pickCsv"></label>
   <label>配对CSV<textarea v-model="csvPairs" rows="8" required placeholder="pair_id,range_label,x,y"></textarea></label>
   <Notice :message="error"/>
   <button :disabled="busy">校验并保存配对</button>
  </form>
  <aside v-else class="field-note">只读账号可核查原始读数。导入需要分析师权限。</aside>
 </div>
</template>

<style scoped>
.tab-strip{display:flex;gap:12px;padding-bottom:18px}
.preview-box{margin-top:14px;padding:16px;border:1px solid var(--line);background:var(--paper)}
.preview-actions{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-top:18px}
.preview-actions label{margin-bottom:0}
</style>
