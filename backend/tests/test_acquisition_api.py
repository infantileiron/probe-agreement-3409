def sample(no, ts, band="low", reading=10.0, revision=0):
 return {"sample_no": no, "sampled_at": ts, "range_label": band,
         "reading": reading, "revision": revision}


def test_viewer_cannot_ingest(client, viewer_headers):
 resp = client.post("/acquisition/ingest",
                    json={"batch_code": "W1", "side": "x", "unit": "kPa",
                          "samples": [sample("X1", "2026-11-12T09:00:00Z")]},
                    headers=viewer_headers)
 assert resp.status_code == 403


def test_anonymous_rejected(client):
 assert client.get("/acquisition/batches").status_code == 401


def test_full_flow_over_http(client, analyst_headers):
 h = analyst_headers
 xs = [sample(f"X{i}", f"2026-11-12T09:0{i}:00Z") for i in range(4)]
 ys = [sample(f"Y{i}", f"2026-11-12T09:0{i}:02Z") for i in range(4)]
 r = client.post("/acquisition/ingest",
                 json={"batch_code": "W2", "side": "x", "unit": "kPa", "samples": xs},
                 headers=h)
 assert r.status_code == 201 and r.json()["inserted"] == 4
 r = client.post("/acquisition/ingest",
                 json={"batch_code": "W2", "side": "y", "unit": "kPa", "samples": ys},
                 headers=h)
 assert r.status_code == 201
 # 重复上传：幂等，不新增
 r = client.post("/acquisition/ingest",
                 json={"batch_code": "W2", "side": "x", "unit": "kPa", "samples": xs},
                 headers=h)
 body = r.json()
 assert body["inserted"] == 0 and body["skipped_duplicate"] == 4

 groups = client.get("/acquisition/batches", headers=h).json()
 group = next(g for g in groups if g["batch_code"] == "W2")
 assert set(group["sides"]) == {"x", "y"}

 r = client.post("/acquisition/batches/W2/preview", json={"max_time_diff": 5}, headers=h)
 assert r.status_code == 200
 preview = r.json()
 assert preview["result"]["pair_count"] == 4
 assert preview["result"]["total_time_diff"] == 8
 # 未配对原因为空（满配）
 assert preview["result"]["unmatched"] == []

 r = client.post("/acquisition/batches/W2/publish",
                 json={"name": "HTTP发布W2", "description": ""}, headers=h)
 assert r.status_code == 200
 pairing_id = r.json()["id"]
 detail = client.get(f"/acquisition/pairings/{pairing_id}", headers=h).json()
 assert detail["snapshot"]["pair_count"] == 4
 # 发布后生成的下游 dataset 可被既有研究流程读取
 ds = client.get("/datasets", headers=h).json()
 assert any(d["name"] == "HTTP发布W2" for d in ds)


def test_conflict_batch_rejected_over_http(client, analyst_headers):
 h = analyst_headers
 client.post("/acquisition/ingest",
             json={"batch_code": "W3", "side": "x", "unit": "kPa",
                   "samples": [sample("X1", "2026-11-12T09:00:00Z", reading=10.0)]},
             headers=h)
 r = client.post("/acquisition/ingest",
                 json={"batch_code": "W3", "side": "x", "unit": "kPa",
                       "samples": [sample("X1", "2026-11-12T09:00:00Z", reading=55.5)]},
                 headers=h)
 assert r.status_code == 409
 assert "冲突" in r.json()["detail"]["detail"]


def test_csv_ingest_and_unmatched_reasons(client, analyst_headers):
 h = analyst_headers
 csv_x = ("sample_no,sampled_at,range_label,reading,revision\n"
          "X1,2026-11-12T09:00:00Z,low,10,0\n"
          "X2,2026-11-12T09:00:10Z,low,11,0\n")
 csv_y = ("sample_no,sampled_at,range_label,reading,revision\n"
          "Y1,2026-11-12T09:00:01Z,low,10.2,0\n"
          "Y2,2026-11-12T09:05:00Z,middle,11.2,0\n")
 assert client.post("/acquisition/ingest",
                    json={"batch_code": "W4", "side": "x", "unit": "kPa",
                          "csv_text": csv_x}, headers=h).status_code == 201
 assert client.post("/acquisition/ingest",
                    json={"batch_code": "W4", "side": "y", "unit": "kPa",
                          "csv_text": csv_y}, headers=h).status_code == 201
 r = client.post("/acquisition/batches/W4/preview",
                 json={"max_time_diff": 3}, headers=h)
 result = r.json()["result"]
 assert result["pair_count"] == 1
 reasons = {(u["side"], u["sample_no"]): u["reason"] for u in result["unmatched"]}
 # X2 量程 low 与 Y2(middle) 不跨量程，且窗内无 low 候选
 assert reasons[("x", "X2")] == "no_candidate"
 assert reasons[("y", "Y2")] == "no_candidate"


def test_bad_csv_rejected(client, analyst_headers):
 r = client.post("/acquisition/ingest",
                 json={"batch_code": "W5", "side": "x", "unit": "kPa",
                       "csv_text": "sample_no,sampled_at,range_label,reading,revision\n"
                                   "X1,2026-11-12T09:00:00Z,huge,10,0\n"},
                 headers=analyst_headers)
 assert r.status_code == 422


def test_backfill_revision_keeps_new_value(client, admin_headers):
 h = admin_headers
 client.post("/acquisition/ingest",
             json={"batch_code": "W6", "side": "x", "unit": "kPa",
                   "samples": [sample("X1", "2026-11-12T09:00:00Z", reading=20.0, revision=2)]},
             headers=h)
 client.post("/acquisition/ingest",
             json={"batch_code": "W6", "side": "x", "unit": "kPa",
                   "samples": [sample("X1", "2026-11-12T09:00:00Z", reading=18.0, revision=1)]},
             headers=h)
 detail = client.get("/acquisition/batches/W6", headers=h).json()
 cur = detail["sides"]["x"]["samples"]
 assert len(cur) == 1 and cur[0]["revision"] == 2 and cur[0]["reading"] == 20.0
