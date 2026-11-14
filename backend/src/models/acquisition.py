from sqlalchemy import String, Integer, BigInteger, Boolean, Double, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .common import RecordMixin
from ..config.database import Base


class AcquisitionBatch(RecordMixin, Base):
 """两探头各自导出的采样流水按采集批次分侧接收。"""
 __tablename__ = "acquisition_batches"
 code: Mapped[str] = mapped_column(String(120))
 side: Mapped[str] = mapped_column(String(8))
 unit: Mapped[str] = mapped_column(String(20))
 status: Mapped[str] = mapped_column(String(16), default="open")
 published_pairing_id: Mapped[str] = mapped_column(String(36), default="")
 __table_args__ = (UniqueConstraint("code", "side", name="uq_batch_code_side"),)


class Sample(RecordMixin, Base):
 """带采样编号、时间、量程、读数、修订号的单条采样；同编号同修订唯一。"""
 __tablename__ = "samples"
 batch_id: Mapped[str] = mapped_column(ForeignKey("acquisition_batches.id"))
 side: Mapped[str] = mapped_column(String(8))
 sample_no: Mapped[str] = mapped_column(String(80))
 revision: Mapped[int] = mapped_column(Integer)
 sampled_at: Mapped[str] = mapped_column(String(40))
 ts_epoch: Mapped[int] = mapped_column(BigInteger)
 range_label: Mapped[str] = mapped_column(String(12))
 reading: Mapped[float] = mapped_column(Double)
 content_hash: Mapped[str] = mapped_column(String(64))
 is_current: Mapped[bool] = mapped_column(Boolean, default=True)
 __table_args__ = (
  UniqueConstraint("batch_id", "side", "sample_no", "revision", name="uq_sample_revision"),
  Index("ix_sample_current", "batch_id", "side", "is_current"),
 )


class PairingPreview(RecordMixin, Base):
 """按量程与可设时差生成的配对预览，重新计算即整体覆盖。"""
 __tablename__ = "pairing_previews"
 batch_code: Mapped[str] = mapped_column(String(120), unique=True)
 max_time_diff: Mapped[int] = mapped_column(Integer)
 result: Mapped[dict] = mapped_column(JSON)
 published_pairing_id: Mapped[str] = mapped_column(String(36), default="")


class PairingBatch(RecordMixin, Base):
 """发布生成的不可变配对批次；并发发布同一预览只生成一份。"""
 __tablename__ = "pairing_batches"
 preview_id: Mapped[str] = mapped_column(String(36), unique=True)
 batch_code: Mapped[str] = mapped_column(String(120))
 name: Mapped[str] = mapped_column(String(180), unique=True)
 unit: Mapped[str] = mapped_column(String(20))
 max_time_diff: Mapped[int] = mapped_column(Integer)
 snapshot: Mapped[dict] = mapped_column(JSON)
 dataset_id: Mapped[str] = mapped_column(String(36))
