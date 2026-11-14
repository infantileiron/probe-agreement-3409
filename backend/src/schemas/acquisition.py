import math
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
from ..constants.enums import UNITS, RangeBand
from ..constants.acquisition import MAX_INGEST_ROWS, MAX_SAMPLE_NO, MAX_BATCH_CODE, MAX_ABS_READING


class SampleEntry(BaseModel):
 sample_no: str = Field(min_length=1, max_length=MAX_SAMPLE_NO)
 sampled_at: str = Field(min_length=1, max_length=40)
 range_label: str
 reading: float
 revision: int = Field(ge=0)

 @model_validator(mode="after")
 def _check(self):
  if self.range_label not in [b.value for b in RangeBand]:
   raise ValueError("range_label 应为 low/middle/high")
  if not math.isfinite(self.reading) or abs(self.reading) > MAX_ABS_READING:
   raise ValueError("reading 必须有限且绝对值不超过 1e9")
  try:
   datetime.fromisoformat(self.sampled_at.replace("Z", "+00:00"))
  except ValueError:
   raise ValueError("sampled_at 需为 ISO 8601 时间，例如 2026-11-12T09:00:00Z")
  return self


class IngestRequest(BaseModel):
 batch_code: str = Field(min_length=2, max_length=MAX_BATCH_CODE)
 side: str
 unit: str
 samples: list[SampleEntry] = Field(default_factory=list)
 csv_text: str = Field(default="", max_length=4000000)

 @model_validator(mode="after")
 def _check(self):
  if self.side not in ("x", "y"):
   raise ValueError("side 只能为 x 或 y，对应两探头分侧接收")
  if self.unit not in UNITS:
   raise ValueError("unit 需属于支持单位，不自动换算")
  if not self.samples and not self.csv_text.strip():
   raise ValueError("需通过 samples 或 csv_text 提供采样流水")
  if len(self.samples) > MAX_INGEST_ROWS:
   raise ValueError(f"单次上传不超过 {MAX_INGEST_ROWS} 条")
  return self


class PreviewRequest(BaseModel):
 max_time_diff: int = Field(ge=0, le=86400)


class PublishRequest(BaseModel):
 name: str = Field(min_length=2, max_length=180)
 description: str = Field(default="", max_length=2000)
