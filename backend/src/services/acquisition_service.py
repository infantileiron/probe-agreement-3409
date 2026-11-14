import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config.database import engine
from ..constants.acquisition import MAX_SAMPLES_PER_SIDE, PairReason
from ..models.acquisition import AcquisitionBatch, Sample, PairingPreview, PairingBatch
from ..models.dataset import PairedDataset
from .pairing import pair_samples
from .sample_stream import parse_stream_csv


def to_epoch(iso_text):
 dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
 if dt.tzinfo is None:
  dt = dt.replace(tzinfo=timezone.utc)
 return int(dt.timestamp())


def content_hash(entry):
 payload = json.dumps(
  {"sample_no": entry["sample_no"], "sampled_at": entry["sampled_at"],
   "range_label": entry["range_label"], "reading": entry["reading"],
   "revision": entry["revision"]},
  sort_keys=True, separators=(",", ":"), ensure_ascii=False)
 return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_or_create_batch(db, code, side, unit):
 batch = db.scalar(select(AcquisitionBatch).where(
  AcquisitionBatch.code == code, AcquisitionBatch.side == side))
 if batch is not None:
  if batch.unit != unit:
   raise HTTPException(422, f"批次 {code}/{side} 已声明单位 {batch.unit}，与本次 {unit} 冲突")
  if batch.status == "published":
   raise HTTPException(409, "该采集批次已发布不可变配对批次，请另建采集批次承接补传")
  return batch, False
 batch = AcquisitionBatch(id=str(uuid4()), code=code, side=side, unit=unit, status="open")
 db.add(batch)
 try:
  db.flush()
 except IntegrityError:
  db.rollback()
  batch = db.scalar(select(AcquisitionBatch).where(
   AcquisitionBatch.code == code, AcquisitionBatch.side == side))
  if batch is None:
   raise HTTPException(500, "采集批次创建失败")
  if batch.unit != unit:
   raise HTTPException(422, f"批次 {code}/{side} 已声明单位 {batch.unit}，与本次 {unit} 冲突")
  return batch, False
 return batch, True


def ingest(db, body):
 entries = [e.model_dump() for e in body.samples]
 if body.csv_text.strip():
  try:
   entries.extend(parse_stream_csv(body.csv_text))
  except ValueError as exc:
   raise HTTPException(422, str(exc))
 if not entries:
  raise HTTPException(422, "未提供任何采样条目")
 # 同编号同修订在本次上传内去重校验（CSV 解析已校验，JSON 入口在此补齐）
 local_seen = set()
 for e in entries:
  key = (e["sample_no"], e["revision"])
  if key in local_seen:
   raise HTTPException(422, f"采样编号 {e['sample_no']} 修订 {e['revision']} 在本次上传内重复")
  local_seen.add(key)

 batch, _ = _get_or_create_batch(db, body.batch_code, body.side, body.unit)
 current_obj = {s.sample_no: s for s in db.scalars(select(Sample).where(
  Sample.batch_id == batch.id, Sample.side == body.side, Sample.is_current.is_(True)))}
 current_rev = {no: row.revision for no, row in current_obj.items()}
 all_revisions = {(s.sample_no, s.revision): s for s in db.scalars(select(Sample).where(
  Sample.batch_id == batch.id, Sample.side == body.side))}

 inserted, skipped, superseded, conflict = 0, 0, 0, []
 for e in entries:
  no, rev = e["sample_no"], e["revision"]
  h = content_hash(e)
  prior = all_revisions.get((no, rev))
  if prior is not None:
   if prior.content_hash != h:
    conflict.append({"sample_no": no, "revision": rev,
                     "reason": "同编号同修订内容与已存样本冲突，整批拒绝"})
   else:
    skipped += 1
   continue
  cur_rev = current_rev.get(no)
  if cur_rev is not None and rev < cur_rev:
   # 旧修订晚到：保留更新值，仅存档不成为当前值
   row = Sample(id=str(uuid4()), batch_id=batch.id, side=body.side, sample_no=no,
                revision=rev, sampled_at=e["sampled_at"], ts_epoch=to_epoch(e["sampled_at"]),
                range_label=e["range_label"], reading=e["reading"], content_hash=h,
                is_current=False)
   db.add(row)
   all_revisions[(no, rev)] = row
   inserted += 1
   continue
  if cur_rev is not None:  # 同编号更新修订（相等修订上面已命中 prior）
   current_obj[no].is_current = False
   superseded += 1
  row = Sample(id=str(uuid4()), batch_id=batch.id, side=body.side, sample_no=no,
               revision=rev, sampled_at=e["sampled_at"], ts_epoch=to_epoch(e["sampled_at"]),
               range_label=e["range_label"], reading=e["reading"], content_hash=h,
               is_current=True)
  db.add(row)
  current_obj[no] = row
  current_rev[no] = rev
  all_revisions[(no, rev)] = row
  inserted += 1

 if conflict:
  db.rollback()
  raise HTTPException(409, {"detail": "同编号同修订内容冲突，整批拒绝，未写入任何样本",
                            "conflicts": conflict})

 # 容量护栏（以当前样本计）
 total_current = len(db.scalars(select(Sample).where(
  Sample.batch_id == batch.id, Sample.side == body.side,
  Sample.is_current.is_(True))).all())
 if total_current > MAX_SAMPLES_PER_SIDE:
  db.rollback()
  raise HTTPException(422, f"单侧当前样本超过 {MAX_SAMPLES_PER_SIDE} 条上限，整批拒绝")
 db.commit()
 db.refresh(batch)
 return {"batch_id": batch.id, "batch_code": batch.code, "side": batch.side,
         "unit": batch.unit, "status": batch.status,
         "inserted": inserted, "skipped_duplicate": skipped, "superseded": superseded,
         "current_samples": total_current}


def list_batches(db):
 rows = db.scalars(select(AcquisitionBatch).order_by(AcquisitionBatch.created_at.desc())).all()
 result = []
 for b in rows:
  total = len(db.scalars(select(Sample).where(
   Sample.batch_id == b.id, Sample.side == b.side, Sample.is_current.is_(True))).all())
  result.append({"id": b.id, "code": b.code, "side": b.side, "unit": b.unit,
                 "status": b.status, "published_pairing_id": b.published_pairing_id,
                 "current_samples": total,
                 "created_at": b.created_at.isoformat() + "Z"})
 return result


def _grouped_batches(db):
 groups = {}
 for b in db.scalars(select(AcquisitionBatch)).all():
  groups.setdefault(b.code, {})[b.side] = b
 return groups


def list_groups(db):
 out = []
 for code, sides in _grouped_batches(db).items():
  item = {"batch_code": code, "sides": {}, "status": "open"}
  for side, b in sides.items():
   total = len(db.scalars(select(Sample).where(
    Sample.batch_id == b.id, Sample.side == side, Sample.is_current.is_(True))).all())
   item["sides"][side] = {"batch_id": b.id, "unit": b.unit, "status": b.status,
                          "current_samples": total}
   if b.status == "published":
    item["status"] = "published"
    item["published_pairing_id"] = b.published_pairing_id
  out.append(item)
 out.sort(key=lambda g: g["batch_code"])
 return out


def _current_samples(db, batch_id, side):
 rows = db.scalars(select(Sample).where(
  Sample.batch_id == batch_id, Sample.side == side,
  Sample.is_current.is_(True)).order_by(Sample.sample_no)).all()
 return [{"sample_no": s.sample_no, "revision": s.revision, "sampled_at": s.sampled_at,
          "ts_epoch": s.ts_epoch, "range_label": s.range_label, "reading": s.reading}
         for s in rows]


def detail(db, code):
 groups = _grouped_batches(db)
 if code not in groups:
  raise HTTPException(404, "采集批次不存在")
 sides = groups[code]
 data = {"batch_code": code, "sides": {}}
 for side, b in sides.items():
  data["sides"][side] = {"unit": b.unit, "status": b.status,
                         "samples": _current_samples(db, b.id, side)}
 preview = db.scalar(select(PairingPreview).where(PairingPreview.batch_code == code))
 data["preview_id"] = preview.id if preview else None
 data["published_pairing_id"] = preview.published_pairing_id if preview else ""
 return data


def compute_preview(db, code, max_time_diff):
 groups = _grouped_batches(db)
 if code not in groups:
  raise HTTPException(404, "采集批次不存在")
 sides = groups[code]
 if any(b.status == "published" for b in sides.values()):
  raise HTTPException(409, "已发布的采集批次不可重新配对，补传不会改变已发布批次")
 if "x" not in sides or "y" not in sides:
  raise HTTPException(422, "需两侧（x/y）流水均已接收才能配对")
 xb, yb = sides["x"], sides["y"]
 if xb.unit != yb.unit:
  raise HTTPException(422, f"两侧单位不一致：{xb.unit} / {yb.unit}，不自动换算")
 xs = _current_samples(db, xb.id, "x")
 ys = _current_samples(db, yb.id, "y")
 pairs, x_reasons, y_reasons = pair_samples(xs, ys, max_time_diff)
 total_diff = sum(p["time_diff_seconds"] for p in pairs)
 result = {
  "max_time_diff": max_time_diff, "unit": xb.unit,
  "x_total": len(xs), "y_total": len(ys),
  "pair_count": len(pairs), "total_time_diff": total_diff,
  "pairs": pairs,
  "unmatched": x_reasons + y_reasons,
  "reason_legend": {
   PairReason.NO_CANDIDATE: "同量程、时差窗内没有任何对侧候选",
   PairReason.GRABBED: "窗内候选均已被其他样本占用（抢配），本样本落空",
  },
 }
 preview = db.scalar(select(PairingPreview).where(PairingPreview.batch_code == code))
 if preview is None:
  preview = PairingPreview(id=str(uuid4()), batch_code=code,
                           max_time_diff=max_time_diff, result=result)
  db.add(preview)
 else:
  preview.max_time_diff = max_time_diff
  preview.result = result
 db.commit()
 db.refresh(preview)
 return _preview_payload(preview)


def _preview_payload(preview):
 return {"id": preview.id, "batch_code": preview.batch_code,
         "max_time_diff": preview.max_time_diff,
         "published_pairing_id": preview.published_pairing_id,
         "result": preview.result, "created_at": preview.created_at.isoformat() + "Z"}


def get_preview(db, code):
 preview = db.scalar(select(PairingPreview).where(PairingPreview.batch_code == code))
 if preview is None:
  raise HTTPException(404, "尚未生成配对预览")
 return _preview_payload(preview)


def _lock_batch(db, batch_id):
 # MySQL/InnoDB 行级锁串行化并发发布；SQLite 不支持 SELECT ... FOR UPDATE，降级依赖唯一约束
 if engine.dialect.name == "sqlite":
  return db.get(AcquisitionBatch, batch_id)
 return db.query(AcquisitionBatch).filter(
  AcquisitionBatch.id == batch_id).with_for_update().first()


def publish(db, code, body):
 groups = _grouped_batches(db)
 if code not in groups:
  raise HTTPException(404, "采集批次不存在")
 sides = groups[code]
 # 对两侧采集批次加行锁，串行化同一采集批次的并发发布
 for side in sorted(sides):
  _lock_batch(db, sides[side].id)
 preview = db.scalar(select(PairingPreview).where(PairingPreview.batch_code == code))
 if preview is None:
  raise HTTPException(409, "请先生成配对预览再发布")
 if preview.published_pairing_id:
  existing = db.get(PairingBatch, preview.published_pairing_id)
  if existing is not None:
   # 并发/重复发布同一预览：返回同一份，不新建
   return {"id": existing.id, "name": existing.name, "dataset_id": existing.dataset_id,
           "idempotent": True, "pair_count": existing.snapshot["pair_count"]}
 pairs = preview.result["pairs"]
 if len(pairs) < 4:
  raise HTTPException(422, "发布至少需要 4 组配对读数")
 unit = sides["x"].unit
 pairing_id = "pair-" + uuid4().hex[:12]
 dataset_id = "ds-" + uuid4().hex[:12]
 legacy_pairs = [{"pair_id": f"{p['x_sample_no']}|{p['y_sample_no']}",
                  "range_label": p["range_label"], "x": p["x"], "y": p["y"]}
                 for p in pairs]
 snapshot = {**preview.result, "name": body.name, "description": body.description,
             "preview_id": preview.id, "batch_code": code}
 pairing = PairingBatch(id=pairing_id, preview_id=preview.id, batch_code=code,
                        name=body.name, unit=unit, max_time_diff=preview.max_time_diff,
                        snapshot=snapshot, dataset_id=dataset_id)
 dataset = PairedDataset(id=dataset_id, name=body.name, x_unit=unit, y_unit=unit,
                         pairs=legacy_pairs,
                         description=(body.description or f"由采集批次 {code} 自动配对发布")[:2000])
 db.add(pairing)
 db.add(dataset)
 try:
  db.flush()
 except IntegrityError:
  db.rollback()
  # 唯一约束兜底：并发下另一事务已发布同一预览（或占用同名批次）
  winner = db.scalar(select(PairingBatch).where(PairingBatch.preview_id == preview.id))
  if winner is not None:
   return {"id": winner.id, "name": winner.name, "dataset_id": winner.dataset_id,
           "idempotent": True, "pair_count": winner.snapshot["pair_count"]}
  if db.scalar(select(PairedDataset).where(PairedDataset.name == body.name)):
   raise HTTPException(409, "配对批次名称已存在")
  raise HTTPException(409, "该预览已被发布或存在唯一约束冲突")
 preview = db.get(PairingPreview, preview.id)
 preview.published_pairing_id = pairing_id
 for side in sorted(sides):
  b = db.get(AcquisitionBatch, sides[side].id)
  b.status = "published"
  b.published_pairing_id = pairing_id
 db.commit()
 return {"id": pairing_id, "name": body.name, "dataset_id": dataset_id,
         "idempotent": False, "pair_count": len(pairs)}


def list_pairings(db):
 rows = db.scalars(select(PairingBatch).order_by(PairingBatch.created_at.desc())).all()
 return [{"id": p.id, "name": p.name, "batch_code": p.batch_code, "unit": p.unit,
          "max_time_diff": p.max_time_diff, "dataset_id": p.dataset_id,
          "pair_count": p.snapshot["pair_count"],
          "created_at": p.created_at.isoformat() + "Z"} for p in rows]


def get_pairing(db, pairing_id):
 row = db.get(PairingBatch, pairing_id)
 if row is None:
  raise HTTPException(404, "配对批次不存在")
 return {"id": row.id, "name": row.name, "batch_code": row.batch_code, "unit": row.unit,
         "max_time_diff": row.max_time_diff, "dataset_id": row.dataset_id,
         "snapshot": row.snapshot, "created_at": row.created_at.isoformat() + "Z"}
