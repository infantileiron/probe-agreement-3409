import csv
import io
import math
from datetime import datetime

REQUIRED = {"sample_no", "sampled_at", "range_label", "reading", "revision"}
BANDS = {"low", "middle", "high"}


def parse_stream_csv(text):
 """解析两探头导出的采样流水 CSV，列：sample_no,sampled_at,range_label,reading,revision。"""
 rows = list(csv.DictReader(io.StringIO(text)))
 if not rows or not REQUIRED.issubset(rows[0].keys()):
  raise ValueError("CSV 需包含列 sample_no,sampled_at,range_label,reading,revision")
 result, seen = [], set()
 for index, row in enumerate(rows, 2):
  no = (row.get("sample_no") or "").strip()
  if not no or len(no) > 80:
   raise ValueError(f"第{index}行采样编号为空或过长")
  band = (row.get("range_label") or "").strip()
  if band not in BANDS:
   raise ValueError(f"第{index}行量程应为 low/middle/high")
  try:
   reading = float(row.get("reading"))
  except (TypeError, ValueError):
   raise ValueError(f"第{index}行 reading 需要有效数值")
  if not math.isfinite(reading) or abs(reading) > 1e9:
   raise ValueError(f"第{index}行 reading 必须有限且绝对值不超过 1e9")
  rev_raw = (row.get("revision") or "").strip()
  try:
   revision = int(rev_raw)
   if revision < 0 or str(revision) != rev_raw:
    raise ValueError
  except ValueError:
   raise ValueError(f"第{index}行 revision 需为非负整数")
  ts = (row.get("sampled_at") or "").strip()
  try:
   datetime.fromisoformat(ts.replace("Z", "+00:00"))
  except ValueError:
   raise ValueError(f"第{index}行 sampled_at 需为 ISO 8601 时间")
  key = (no, revision)
  if key in seen:
   raise ValueError(f"第{index}行采样编号 {no} 修订 {revision} 在本次上传内重复")
  seen.add(key)
  result.append({"sample_no": no, "sampled_at": ts, "range_label": band,
                 "reading": reading, "revision": revision})
 return result
