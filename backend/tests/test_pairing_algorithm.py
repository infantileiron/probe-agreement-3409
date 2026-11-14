from src.services.pairing import pair_samples
from src.constants.acquisition import PairReason


def s(no, ts, band, reading=10.0, revision=0):
 return {"sample_no": no, "ts_epoch": ts,
         "sampled_at": f"2026-11-12T09:{int(ts):02d}:{int(round((ts - int(ts)) * 60)):02d}Z",
         "range_label": band, "reading": reading, "revision": revision}


def test_greedy_grab_counterexample_prefers_max_cardinality():
 """抢配反例（共享近邻 + 最小总时差）。
 边：X1-Y1(3)、X1-Y2(2)、X2-Y1(1)、X2-Y2(2)，窗=3。
 若按“X1 选最近 Y2”的贪心，会与 X2 抢 Y2；最优满配取总时差更小的
 X1-Y1(3)+X2-Y1 冲突，实际唯一最优为 X1-Y2(2)+X2-Y1(1)，合计 3。"""
 xs = [s("X1", 0, "low"), s("X2", 4, "low")]
 ys = [s("Y1", 3, "low"), s("Y2", 2, "low")]
 pairs, xr, yr = pair_samples(xs, ys, max_time_diff=3)
 assert len(pairs) == 2
 matched = {(p["x_sample_no"], p["y_sample_no"]) for p in pairs}
 assert matched == {("X1", "Y2"), ("X2", "Y1")}
 assert sum(p["time_diff_seconds"] for p in pairs) == 3
 assert xr == [] and yr == []


def test_greedy_grab_leaves_grabbed_reason():
 """三个 X 抢两个 Y：固定裁决取总时差最小的满配，落败 X 记为 grabbed。"""
 xs = [s("X1", 0, "low"), s("X2", 4, "low"), s("X3", 5, "low")]
 ys = [s("Y1", 3, "low"), s("Y2", 4, "low")]
 pairs, xr, _ = pair_samples(xs, ys, max_time_diff=3)
 assert len(pairs) == 2
 leftover = {r["sample_no"]: r["reason"] for r in xr}
 assert len(leftover) == 1
 assert next(iter(leftover.values())) == PairReason.GRABBED


def test_min_total_diff_among_max_cardinality():
 """两种满配方案：A 方案时差合计 4，B 方案合计 6，应取时差更小者。"""
 xs = [s("X1", 0, "low"), s("X2", 10, "low")]
 ys = [s("Y1", 2, "low"), s("Y2", 8, "low")]
 pairs, _, _ = pair_samples(xs, ys, max_time_diff=10)
 assert len(pairs) == 2
 assert sum(p["time_diff_seconds"] for p in pairs) == 4
 assert {(p["x_sample_no"], p["y_sample_no"]) for p in pairs} == {
  ("X1", "Y1"), ("X2", "Y2")}


def test_fixed_tie_break_is_deterministic():
 """完全对称的两种最优方案，固定裁决为 X 编号字典序优先。"""
 xs = [s("XA", 0, "low"), s("XB", 1, "low")]
 ys = [s("YA", 0, "low"), s("YB", 1, "low")]
 first, _, _ = pair_samples(xs, ys, max_time_diff=5)
 # 乱序输入结果必须一致
 second, _, _ = pair_samples(list(reversed(xs)), list(reversed(ys)), max_time_diff=5)
 keys_first = [(p["x_sample_no"], p["y_sample_no"]) for p in first]
 keys_second = [(p["x_sample_no"], p["y_sample_no"]) for p in second]
 assert keys_first == keys_second
 assert keys_first == [("XA", "YA"), ("XB", "YB")]


def test_range_band_partitions_do_not_cross():
 xs = [s("X1", 0, "low"), s("X2", 0, "high")]
 ys = [s("Y1", 0, "high"), s("Y2", 0, "low")]
 pairs, xr, yr = pair_samples(xs, ys, max_time_diff=5)
 assert {(p["x_sample_no"], p["range_label"]) for p in pairs} == {
  ("X1", "low"), ("X2", "high")}
 assert all(p["range_label"] == "low" for p in pairs if p["x_sample_no"] == "X1")
 assert xr == [] and yr == []


def test_unmatched_reasons():
 # X1(t0)/X2(t1) 都只能配 Y1(t0)；X3(t100) 窗内无候选；Y2(t500) 无候选
 xs = [s("X1", 0, "low"), s("X2", 1, "low"), s("X3", 100, "low")]
 ys = [s("Y1", 0, "low"), s("Y2", 500, "low")]
 pairs, xr, yr = pair_samples(xs, ys, max_time_diff=5)
 assert len(pairs) == 1
 reasons = {r["sample_no"]: r["reason"] for r in xr}
 assert reasons["X3"] == PairReason.NO_CANDIDATE
 # X1/X2 抢 Y1，固定裁决下 X1 拿到、X2 被抢配
 assert reasons["X2"] == PairReason.GRABBED
 assert set(reasons) == {"X2", "X3"}
 y_reasons = {r["sample_no"]: r["reason"] for r in yr}
 assert y_reasons["Y2"] == PairReason.NO_CANDIDATE


def test_unbalanced_reason_on_surplus_side():
 """X2(t100) 远离所有 Y 无候选；Y 侧 3 个、可配的只有 X1，多数侧一个被抢配。"""
 xs = [s("X1", 0, "low"), s("X2", 100, "low")]
 ys = [s("Y1", 0, "low"), s("Y2", 1, "low"), s("Y3", 500, "low")]
 pairs, xr, yr = pair_samples(xs, ys, max_time_diff=5)
 assert len(pairs) == 1
 x_reasons = {r["sample_no"]: r["reason"] for r in xr}
 assert x_reasons == {"X2": PairReason.NO_CANDIDATE}
 y_reasons = {r["sample_no"]: r["reason"] for r in yr}
 assert y_reasons["Y3"] == PairReason.NO_CANDIDATE
 leftover = [n for n in ("Y1", "Y2") if n in y_reasons]
 assert len(leftover) == 1
 assert y_reasons[leftover[0]] == PairReason.GRABBED


def test_unbalanced_when_free_candidate_remains():
 """量程失衡导致多数侧样本落空：标签固定为 grabbed，结果与输入顺序无关。"""
 xs = [s("X1", 0, "low"), s("X2", 50, "low")]
 ys = [s("Y1", 1, "low"), s("Y2", 2, "low"), s("Y3", 50, "low")]
 pairs, xr, yr = pair_samples(xs, ys, max_time_diff=5)
 assert len(pairs) == 2
 labels = {r["sample_no"]: r["reason"] for r in yr}
 assert set(labels) <= {"Y1", "Y2"}
 assert all(v == PairReason.GRABBED for v in labels.values())


def test_each_sample_used_once():
 xs = [s(f"X{i}", i, "low") for i in range(6)]
 ys = [s(f"Y{i}", i + 0.5, "low") for i in range(6)]
 pairs, _, _ = pair_samples(xs, ys, max_time_diff=2)
 used_x = [p["x_sample_no"] for p in pairs]
 used_y = [p["y_sample_no"] for p in pairs]
 assert len(used_x) == len(set(used_x))
 assert len(used_y) == len(set(used_y))


def test_larger_scale_and_performance():
 import time
 n = 200
 xs = [s(f"X{i:04d}", i * 10, ["low", "middle", "high"][i % 3]) for i in range(n)]
 ys = [s(f"Y{i:04d}", i * 10 + 2, ["low", "middle", "high"][i % 3]) for i in range(n)]
 start = time.time()
 pairs, xr, yr = pair_samples(xs, ys, max_time_diff=5)
 elapsed = time.time() - start
 # 同量程且时差 2 秒，全部满配
 assert len(pairs) == n
 assert xr == [] and yr == []
 assert all(p["time_diff_seconds"] == 2 for p in pairs)
 assert elapsed < 5.0
 # 每个样本恰好出现一次
 assert len({p["x_sample_no"] for p in pairs}) == n
 assert len({p["y_sample_no"] for p in pairs}) == n
