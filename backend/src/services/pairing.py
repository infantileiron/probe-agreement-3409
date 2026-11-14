"""采样流水自动配对。

目标按固定优先级求解（全部为整数/精确运算，结果与上传顺序无关）：
1. 配对数量最多；
2. 配对数量相同时，总绝对时差最小；
3. 仍相同时，按 X 侧样本编号字典序（并列再按 Y 侧编号字典序）固定裁决。

实现为源点→X→Y→汇点的最小费用最大流（SPFA 初始化势能 + Dijkstra 增广），
费用 = -BIG + 时差*DWEIGHT + 字典序裁决项，因此一次求解即按上述优先级出最优匹配。
每个样本在流网络中容量为 1，保证“采样只用一次”。候选边按量程分组、
时间排序后二分定位，避免大样本下的笛卡尔积。
"""
from bisect import bisect_left, bisect_right
from heapq import heappush, heappop

from ..constants.acquisition import BIG, DWEIGHT, PairReason

INF = 10**30


def _lex_cost(i, j, nx):
 return i * (nx + 1) + j


def _build_graph(xs, ys, edges):
 # 节点：0 源点；1..nx 为 X；nx+1..nx+ny 为 Y；nx+ny+1 汇点
 nx, ny = len(xs), len(ys)
 source, sink = 0, nx + ny + 1
 size = sink + 1
 graph = [[] for _ in range(size)]

 def add(u, v, cap, cost):
  graph[u].append([v, cap, cost, len(graph[v])])
  graph[v].append([u, 0, -cost, len(graph[u]) - 1])

 for i in range(nx):
  add(source, i + 1, 1, 0)
 for j in range(ny):
  add(nx + 1 + j, sink, 1, 0)
 for i, j, diff in edges:
  cost = -BIG + diff * DWEIGHT + _lex_cost(i, j, nx)
  add(i + 1, nx + 1 + j, 1, cost)
 return graph, source, sink, nx, ny


def _initial_potential(graph, source):
 n = len(graph)
 dist = [INF] * n
 dist[source] = 0
 queue = [source]
 in_queue = {source}
 head = 0
 while head < len(queue):
  u = queue[head]
  head += 1
  in_queue.discard(u)
  for v, cap, cost, _ in graph[u]:
   if cap > 0 and dist[u] + cost < dist[v]:
    dist[v] = dist[u] + cost
    if v not in in_queue:
     queue.append(v)
     in_queue.add(v)
 return [0 if d == INF else d for d in dist]


def _relax(graph, potential, source, sink):
 n = len(graph)
 dist = [INF] * n
 prev_v = [-1] * n
 prev_e = [-1] * n
 dist[source] = 0
 heap = [(0, source)]
 while heap:
  du, u = heappop(heap)
  if du != dist[u]:
   continue
  for ei, (v, cap, cost, _) in enumerate(graph[u]):
   if cap <= 0:
    continue
   reduced = cost + potential[u] - potential[v]
   nd = du + reduced
   if nd < dist[v]:
    dist[v] = nd
    prev_v[v] = u
    prev_e[v] = ei
    heappush(heap, (nd, v))
 if prev_v[sink] < 0:
  return False
 for v in range(n):
  if dist[v] < INF:
   potential[v] += dist[v]
 v = sink
 while v != source:
  u, ei = prev_v[v], prev_e[v]
  edge = graph[u][ei]
  edge[1] -= 1
  graph[v][edge[3]][1] += 1
  v = u
 return True


def min_cost_match(xs, ys, edges):
 """xs/ys 为样本字典列表（含 sample_no、ts_epoch、reading），edges 为 (i,j,abs_diff)。"""
 graph, source, sink, nx, ny = _build_graph(xs, ys, edges)
 potential = _initial_potential(graph, source)
 while _relax(graph, potential, source, sink):
  pass
 pairs = []
 for i in range(nx):
  for edge in graph[i + 1]:
   v, cap, cost, _ = edge
   # 正向边初始容量 1：承载过流量后剩余容量为 0、反向边容量为 1
   if nx + 1 <= v <= nx + ny and cap == 0:
    j = v - nx - 1
    pairs.append((i, j))
 pairs.sort(key=lambda ij: (xs[ij[0]]["sample_no"], ys[ij[1]]["sample_no"]))
 return pairs


def unmatched_reason(adjacency):
 """固定裁决未配对原因。

 最大匹配性质：未匹配样本在时差窗内的全部对侧邻点必然都已被占用
 （否则存在增广路，匹配数还能增加）。因此只有两类可达原因：
 no_candidate 窗内无候选；grabbed 候选全部被其他样本抢配。
 """
 if not adjacency:
  return PairReason.NO_CANDIDATE
 return PairReason.GRABBED


def pair_samples(xs, ys, max_time_diff):
 """入口：两侧当前样本 + 可设时差（秒），返回 (pairs, x_reasons, y_reasons)。"""
 xs = sorted(xs, key=lambda s: s["sample_no"])
 ys = sorted(ys, key=lambda s: s["sample_no"])
 edges = []
 x_adj, y_adj = [set() for _ in xs], [set() for _ in ys]
 # 按量程分组，组内按时间排序后用二分圈定 [t-w, t+w] 窗口
 y_bands = {}
 for j, y in enumerate(ys):
  y_bands.setdefault(y["range_label"], []).append((y["ts_epoch"], j))
 y_band_index = {}
 for band, items in y_bands.items():
  items.sort(key=lambda item: item[0])
  y_band_index[band] = ([t for t, _ in items], [j for _, j in items])
 for i, x in enumerate(xs):
  times, idxs = y_band_index.get(x["range_label"], ([], []))
  if not times:
   continue
  lo = bisect_left(times, x["ts_epoch"] - max_time_diff)
  hi = bisect_right(times, x["ts_epoch"] + max_time_diff)
  for k in range(lo, hi):
   j = idxs[k]
   diff = abs(x["ts_epoch"] - times[k])
   edges.append((i, j, diff))
   x_adj[i].add(j)
   y_adj[j].add(i)
 raw_pairs = min_cost_match(xs, ys, edges)
 matched_x = {i for i, _ in raw_pairs}
 matched_y = {j for _, j in raw_pairs}
 pairs = []
 for i, j in raw_pairs:
  x, y = xs[i], ys[j]
  pairs.append({
   "x_sample_no": x["sample_no"], "y_sample_no": y["sample_no"],
   "range_label": x["range_label"], "x": x["reading"], "y": y["reading"],
   "x_ts": x["sampled_at"], "y_ts": y["sampled_at"],
   "x_revision": x["revision"], "y_revision": y["revision"],
   "time_diff_seconds": abs(x["ts_epoch"] - y["ts_epoch"]),
  })
 x_reasons, y_reasons = [], []
 for i, sample in enumerate(xs):
  if i not in matched_x:
   x_reasons.append({"side": "x", "sample_no": sample["sample_no"],
                     "range_label": sample["range_label"],
                     "reason": unmatched_reason(x_adj[i])})
 for j, sample in enumerate(ys):
  if j not in matched_y:
   y_reasons.append({"side": "y", "sample_no": sample["sample_no"],
                     "range_label": sample["range_label"],
                     "reason": unmatched_reason(y_adj[j])})
 return pairs, x_reasons, y_reasons
