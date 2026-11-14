from enum import StrEnum

class ProbeSide(StrEnum):
 X="x"
 Y="y"

class IngestResult(StrEnum):
 INSERTED="inserted"
 SKIPPED="skipped"

class PairReason(StrEnum):
 PAIRED="paired"
 NO_CANDIDATE="no_candidate"
 GRABBED="grabbed"

# 单批单侧最多保留的当前样本数；保证配对算法在线性规模可预期
MAX_SAMPLES_PER_SIDE=2000
# 单次上传输水条目上限
MAX_INGEST_ROWS=5000
# 采样编号、批次号长度
MAX_SAMPLE_NO=80
MAX_BATCH_CODE=120
# 读数边界，与既有 CSV 口径保持一致
MAX_ABS_READING=1e9
# 裁决权重：基数目标远大于时差目标，时差目标远大于字典序裁决
BIG=10**15
DWEIGHT=10**7
