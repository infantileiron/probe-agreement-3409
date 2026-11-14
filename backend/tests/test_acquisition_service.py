import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.config.database import Session as AppSession
from src.models.acquisition import AcquisitionBatch, Sample, PairingPreview, PairingBatch
from src.models.dataset import PairedDataset
from src.schemas.acquisition import IngestRequest, PreviewRequest, PublishRequest
from src.services import acquisition_service as svc


def entry(no, ts, band="low", reading=10.0, revision=0):
 return {"sample_no": no, "sampled_at": ts, "range_label": band,
         "reading": reading, "revision": revision}


def req(side, samples, code="B1", unit="kPa"):
 return IngestRequest(batch_code=code, side=side, unit=unit, samples=samples)


def test_ingest_idempotent_and_duplicate_upload(db):
 body = req("x", [entry("S1", "2026-11-12T09:00:00Z"),
                  entry("S2", "2026-11-12T09:01:00Z")])
 first = svc.ingest(db, body)
 assert first["inserted"] == 2 and first["skipped_duplicate"] == 0
 second = svc.ingest(db, body)
 assert second["inserted"] == 0 and second["skipped_duplicate"] == 2
 # 重复执行上传不新增已有样本
 count = len(db.scalars(select(Sample)).all())
 assert count == 2


def test_out_of_order_backfill_does_not_duplicate(db):
 svc.ingest(db, req("x", [entry("S1", "2026-11-12T09:00:00Z", revision=2, reading=12.0)]))
 # 更晚才送到的旧修订 1
 svc.ingest(db, req("x", [entry("S1", "2026-11-12T09:00:00Z", revision=1, reading=9.0)]))
 rows = db.scalars(select(Sample).where(Sample.sample_no == "S1")).all()
 assert len(rows) == 2
 current = [r for r in rows if r.is_current]
 assert len(current) == 1 and current[0].revision == 2 and current[0].reading == 12.0
 # 再送同编号新修订 3，旧值被取代，当前值更新
 svc.ingest(db, req("x", [entry("S1", "2026-11-12T09:00:00Z", revision=3, reading=13.0)]))
 current = db.scalars(select(Sample).where(
  Sample.sample_no == "S1", Sample.is_current.is_(True))).all()
 assert len(current) == 1 and current[0].revision == 3 and current[0].reading == 13.0


def test_multiple_revisions_in_one_upload_keeps_single_current(db):
 # 同一上传内同编号两个修订，且旧修订排在后面（乱序）
 body = req("x", [
  entry("S1", "2026-11-12T09:00:00Z", revision=3, reading=30.0),
  entry("S1", "2026-11-12T09:00:00Z", revision=1, reading=10.0),
 ])
 out = svc.ingest(db, body)
 rows = db.scalars(select(Sample).where(Sample.sample_no == "S1")).all()
 current = [r for r in rows if r.is_current]
 assert len(rows) == 2 and len(current) == 1
 assert current[0].revision == 3 and current[0].reading == 30.0
 assert out["superseded"] == 0  # 库中本无当前值，不产生取代计数
 # 再来一批先旧后新的两修订
 body2 = req("x", [
  entry("S2", "2026-11-12T09:01:00Z", revision=1, reading=1.0),
  entry("S2", "2026-11-12T09:01:00Z", revision=2, reading=2.0),
 ])
 svc.ingest(db, body2)
 cur2 = db.scalars(select(Sample).where(
  Sample.sample_no == "S2", Sample.is_current.is_(True))).all()
 assert len(cur2) == 1 and cur2[0].revision == 2 and cur2[0].reading == 2.0


def test_same_revision_content_conflict_rejects_whole_batch(db):
 svc.ingest(db, req("x", [entry("S1", "2026-11-12T09:00:00Z", reading=10.0)]))
 before = len(db.scalars(select(Sample)).all())
 bad = req("x", [
  entry("S1", "2026-11-12T09:00:00Z", reading=99.0),  # 同编号同修订，读数冲突
  entry("S2", "2026-11-12T09:02:00Z", reading=11.0),  # 这条也不得写入
 ])
 with pytest.raises(HTTPException) as exc:
  svc.ingest(db, bad)
 assert exc.value.status_code == 409
 after = len(db.scalars(select(Sample)).all())
 assert after == before  # 整批拒绝，无残留


def test_unit_conflict_rejected(db):
 svc.ingest(db, req("x", [entry("S1", "2026-11-12T09:00:00Z")], unit="kPa"))
 with pytest.raises(HTTPException) as exc:
  svc.ingest(db, req("x", [entry("S2", "2026-11-12T09:01:00Z")], unit="bar"))
 assert exc.value.status_code == 422


def test_preview_and_publish_flow(db):
 xs = [entry(f"X{i}", f"2026-11-12T09:{i:02d}:00Z") for i in range(5)]
 ys = [entry(f"Y{i}", f"2026-11-12T09:{i:02d}:02Z") for i in range(4)]
 svc.ingest(db, req("x", xs, code="B2"))
 svc.ingest(db, req("y", ys, code="B2"))
 preview = svc.compute_preview(db, "B2", max_time_diff=5)
 assert preview["result"]["pair_count"] == 4
 assert preview["result"]["x_total"] == 5 and preview["result"]["y_total"] == 4
 assert len(preview["result"]["unmatched"]) == 1
 out = svc.publish(db, "B2", PublishRequest(name="发布批次B2", description="d"))
 assert out["idempotent"] is False
 pairing = db.get(PairingBatch, out["id"])
 dataset = db.get(PairedDataset, out["dataset_id"])
 assert len(pairing.snapshot["pairs"]) == 4
 assert len(dataset.pairs) == 4 and dataset.name == "发布批次B2"


def test_published_batch_is_immutable_to_later_revision(db):
 svc.ingest(db, req("x", [entry(f"X{i}", f"2026-11-12T09:{i:02d}:00Z", reading=10.0)
                           for i in range(4)], code="B3"))
 svc.ingest(db, req("y", [entry(f"Y{i}", f"2026-11-12T09:{i:02d}:01Z", reading=10.5)
                           for i in range(4)], code="B3"))
 svc.compute_preview(db, "B3", max_time_diff=5)
 out = svc.publish(db, "B3", PublishRequest(name="发布批次B3"))
 snapshot_before = dict(db.get(PairingBatch, out["id"]).snapshot)
 dataset_pairs_before = len(db.get(PairedDataset, out["dataset_id"]).pairs)
 assert dataset_pairs_before == 4
 # 已发布采集批次拒绝再补传
 with pytest.raises(HTTPException) as exc:
  svc.ingest(db, req("x", [entry("X9", "2026-11-12T10:00:00Z")], code="B3"))
 assert exc.value.status_code == 409
 with pytest.raises(HTTPException) as exc2:
  svc.compute_preview(db, "B3", PreviewRequest(max_time_diff=50))
 assert exc2.value.status_code == 409
 pairing = db.get(PairingBatch, out["id"])
 assert pairing.snapshot == snapshot_before
 assert len(db.get(PairedDataset, out["dataset_id"]).pairs) == dataset_pairs_before


def test_repeat_publish_same_preview_returns_same_batch(db):
 svc.ingest(db, req("x", [entry(f"X{i}", f"2026-11-12T09:0{i}:00Z") for i in range(4)],
                    code="B4"))
 svc.ingest(db, req("y", [entry(f"Y{i}", f"2026-11-12T09:0{i}:01Z") for i in range(4)],
                    code="B4"))
 svc.compute_preview(db, "B4", max_time_diff=5)
 first = svc.publish(db, "B4", PublishRequest(name="发布批次B4"))
 again = svc.publish(db, "B4", PublishRequest(name="发布批次B4-重复"))
 assert again["id"] == first["id"] and again["idempotent"] is True
 assert len(db.scalars(select(PairingBatch)).all()) == 1
 assert len(db.scalars(select(PairedDataset)).all()) == 1


def test_concurrent_publish_creates_only_one_batch(db):
 code = "B5"
 svc.ingest(db, req("x", [entry(f"X{i}", f"2026-11-12T09:0{i}:00Z") for i in range(4)],
                    code=code))
 svc.ingest(db, req("y", [entry(f"Y{i}", f"2026-11-12T09:0{i}:01Z") for i in range(4)],
                    code=code))
 svc.compute_preview(db, code, max_time_diff=5)
 results, errors = [], []
 barrier = threading.Barrier(2)

 def worker():
  barrier.wait()
  try:
   with AppSession() as session:
    results.append(svc.publish(session, code, PublishRequest(name="并发发布B5")))
  except HTTPException as exc:
   errors.append(exc.status_code)

 threads = [threading.Thread(target=worker) for _ in range(2)]
 for t in threads:
  t.start()
 for t in threads:
  t.join()
 assert not errors
 ids = {r["id"] for r in results}
 assert len(ids) == 1
 with AppSession() as check:
  assert len(check.scalars(select(PairingBatch)).all()) == 1
  assert len(check.scalars(select(PairedDataset)).all()) == 1
  preview = check.scalar(select(PairingPreview).where(PairingPreview.batch_code == code))
  assert preview.published_pairing_id == next(iter(ids))


def test_publish_requires_four_pairs(db):
 svc.ingest(db, req("x", [entry("X1", "2026-11-12T09:00:00Z")], code="B6"))
 svc.ingest(db, req("y", [entry("Y1", "2026-11-12T09:00:01Z"),
                          entry("Y2", "2026-11-12T09:00:02Z")], code="B6"))
 svc.compute_preview(db, "B6", max_time_diff=5)
 with pytest.raises(HTTPException) as exc:
  svc.publish(db, "B6", PublishRequest(name="不足四组"))
 assert exc.value.status_code == 422
