"""생산관리: LOT(로트) = 트럭 1대분 출하 단위

흐름
  - 로봇이 양품을 팔레트에 쌓음 → PALLET_SIZE(기본 8개)가 차면 지게차가 트럭에 실음
  - 트럭에 TRUCK_PALLETS(기본 10팔레트 = 양품 80개)가 실리면 트럭 출발 = LOT 1개 출하 완료
  - 다음 LOT은 바로 이어서 시작 (빈 트럭이 들어옴). 날짜가 바뀌면 LOT 번호는 01부터 다시
계산 근거: DB inspections (품질 검사 기록). 양품 = 판정이 '불량'이 아닌 것
  → 80번째 양품이 검사된 시각 = 트럭 출발 시각
  (품질 카메라가 없을 때는 demo_sim.py가 만든 기록(source = sim)도 같이 셈)
속도: 목표 사이클(TARGET_CYCLE_SEC, 기본 4초)로 80개를 만드는 시간 = 목표 소요 시간(약 5분)
설정 (config.py에 없으면 기본값)
  PALLET_SIZE = 8
  TRUCK_PALLETS = 10      # 발표 시연 때 2로 줄이면 양품 16개마다 트럭 출발
"""
import collections
import datetime
import json
import time
import config
import db
from analytics import TARGET_CYCLE_SEC

PALLET_SIZE = max(1, int(getattr(config, "PALLET_SIZE", 8)))
TRUCK_PALLETS = max(1, int(getattr(config, "TRUCK_PALLETS", 10)))
LOT_GOOD = PALLET_SIZE * TRUCK_PALLETS                 # 트럭 1대 = LOT 1개의 양품 수 (기본 80)
TARGET_LOT_SEC = LOT_GOOD * TARGET_CYCLE_SEC           # 목표 속도로 LOT 1개를 채우는 시간 (기본 320초)
TARGET_PER_HOUR = int(3600 / TARGET_CYCLE_SEC)


def _midnight(ts):
    return datetime.datetime.combine(datetime.date.fromtimestamp(ts), datetime.time()).timestamp()


# ---------------------------------------------------------------- 정지 구간 → 손실
CONVEYOR = "컨베이어"


class Stops:
    """오늘의 설비 정지 구간 (analytics.segments 사용)
    - line: 컨베이어가 멈춘 구간 = 실제로 생산이 멈춘 시간 (손실 계산 기준)
    - roots: '원인' 정지 (다른 설비의 정지 + 컨베이어 자체 고장). 연동 정지는 결과라서 원인 목록에서 뺌"""
    def __init__(self, now):
        import analytics
        w = {"start": _midnight(now), "cur": now}
        segs = analytics.segments(w)
        bad = lambda g: g["status"] != "가동"
        self.line = [g for g in segs.get(CONVEYOR, []) if bad(g)]
        self.roots = [dict(g, equipment=n) for n, gs in segs.items() for g in gs
                      if bad(g) and (n != CONVEYOR or g["status"] != "연동 정지")]
        self.roots.sort(key=lambda g: g["start"])

    @staticmethod
    def _ov(g, a, b):
        return max(0.0, min(g["end"], b) - max(g["start"], a))

    def down(self, a, b):
        """[a, b) 동안 라인이 멈춘 초"""
        return sum(self._ov(g, a, b) for g in self.line)

    def causes(self, a, b):
        """라인이 멈춘 시간을 원인 설비별로 나눔 {설비: 초}"""
        out = collections.Counter()
        for g in self.line:
            for_line = self._ov(g, a, b)
            if not for_line:
                continue
            best = max(self.roots, key=lambda r: self._ov(r, g["start"], g["end"]), default=None)
            name = best["equipment"] if best and self._ov(best, g["start"], g["end"]) > 0 else CONVEYOR
            out[name] += for_line
        return dict(out.most_common())

    def list(self, a, b):
        """[a, b)에 걸친 원인 정지 목록 (시각 · 멈춘 시간 · 손실 개수)"""
        return [{"ts": g["start"], "equipment": g["equipment"], "status": g["status"], "reason": g.get("reason", ""),
                 "dur": round(g["end"] - g["start"]), "loss": int(self._ov(g, a, b) / TARGET_CYCLE_SEC),
                 "open": bool(g.get("open"))}
                for g in self.roots if self._ov(g, a, b) > 0]


def _lot(seq, day, rows, start, end, now, st):
    bad = [i for i in rows if i["result"] == "불량"]
    total, good = len(rows), len(rows) - len(bad)
    done = end is not None
    b = end if done else now
    stops = st.list(start, b)
    dur = b - start
    down = st.down(start, b)
    sim = sum(1 for i in rows if i.get("source") == "sim")
    return {
        "id": f"{day}-{seq:02d}", "seq": seq, "start": start, "end": end, "duration": dur,
        "total": total, "good": good, "defects": len(bad),
        "rate": len(bad) / total if total else None,
        "pallets": good // PALLET_SIZE, "pallet_fill": good % PALLET_SIZE,
        # 속도 = 목표 사이클로 이만큼 만드는 시간 ÷ 실제 걸린 시간 (100% = 목표 속도)
        "speed": (good * TARGET_CYCLE_SEC / dur) if dur > 30 and good else None,
        "types": dict(collections.Counter(i["defect_type"] or "기타" for i in bad).most_common()),
        "stops": len(stops), "stop_list": stops[-6:],
        "down_sec": round(down), "loss": int(down / TARGET_CYCLE_SEC), "causes": {k: round(v) for k, v in st.causes(start, b).items()},
        "sim_ratio": sim / total if total else 0,
        "status": "출하 완료" if done else "적재 중",
    }


def _plan(now, first_ts):
    """오늘 계획 시간: 교대 시간(analytics의 SHIFT_START~END). 교대 밖이면 첫 생산 시각 ~ 지금"""
    import analytics
    w = analytics.window("shift", now)
    if w["start"] <= now <= w["end"] or (first_ts and w["start"] <= first_ts <= w["end"] and now > w["end"]):
        return w["start"], w["end"], w["label"]
    a = first_ts or now
    return a, max(now, a + 3600), "오늘 (교대 시간 밖)"


def lot_ids(insp, day):
    """검사 기록(시간 순서) 각각이 몇 번째 LOT(트럭)에 들어갔는지 → LOT 번호 목록 (summary와 같은 규칙)"""
    out, good, seq = [], 0, 1
    for i in insp:
        out.append(f"{day}-{seq:02d}")
        if i["result"] != "불량":
            good += 1
            if good == LOT_GOOD:
                good, seq = 0, seq + 1
    return out


def summary(now=None, max_rows=48):
    """오늘의 LOT 목록 + 지금 적재 중인 LOT + 오늘 합계 + 시간대별 생산
    (생산관리 페이지 · 관제 대시보드 생산 현황 · 디지털 트윈 출하장이 같이 씀)"""
    now = now or time.time()
    m = _midnight(now)
    day = datetime.date.fromtimestamp(now).strftime("%Y%m%d")
    insp = db.inspections_between(m, now + 1)
    st = Stops(now)

    # 검사 기록을 시간 순서대로 훑으며 양품 LOT_GOOD개마다 LOT을 닫는다 (= 트럭 출발)
    lots, rows, good, start, seq = [], [], 0, (insp[0]["ts"] if insp else now), 1
    for i in insp:
        rows.append(i)
        if i["result"] != "불량":
            good += 1
            if good == LOT_GOOD:
                lots.append(_lot(seq, day, rows, start, i["ts"], now, st))
                rows, good, start, seq = [], 0, i["ts"], seq + 1
    current = _lot(seq, day, rows, start, None, now, st)

    # 예상 출발: 최근 10분 양품 속도로 남은 양품을 채우는 시간 (속도가 없으면 목표 사이클 기준)
    recent = [i for i in insp if i["ts"] >= now - 600 and i["result"] != "불량"]
    span = min(600.0, now - insp[0]["ts"]) if insp else 0
    rate = len(recent) / span if span > 60 and recent else None          # 양품 / 초
    left = LOT_GOOD - current["good"]
    current["left_good"] = left
    current["left_pallets"] = TRUCK_PALLETS - current["pallets"]
    current["eta_sec"] = left / rate if rate else left * TARGET_CYCLE_SEC
    current["eta_basis"] = "최근 10분 속도" if rate else "목표 속도"
    current["last_insp"] = insp[-1]["ts"] if insp else None
    # 지금 숫자가 시뮬레이터 기록으로 움직이는 중인가 (화면에 '시뮬레이션' 표시용)
    sim_now = bool(insp) and insp[-1].get("source") == "sim" and now - insp[-1]["ts"] < 120
    sim_today = sum(1 for i in insp if i.get("source") == "sim")

    # 계획(교대) 시간 · 예측: 지금까지 평균 속도로 남은 계획 시간을 채우면
    total = len(insp)
    p0, p1, plabel = _plan(now, insp[0]["ts"] if insp else None)
    plan_target = int((p1 - p0) / TARGET_CYCLE_SEC)
    done_in_plan = sum(1 for i in insp if p0 <= i["ts"] <= p1)
    el = max(1.0, min(now, p1) - max(p0, insp[0]["ts"] if insp else p0))
    forecast = done_in_plan + (done_in_plan / el) * max(0.0, p1 - now) if insp else 0

    # 시간대별 생산 (계획 시작 ~ 계획 끝 또는 지금 중 늦은 쪽, 앞으로 올 시간은 비어 있음)
    hours = []
    h = datetime.datetime.fromtimestamp(min(p0, insp[0]["ts"] if insp else p0)).replace(minute=0, second=0, microsecond=0).timestamp()
    while h < max(p1, now):
        r = [i for i in insp if h <= i["ts"] < h + 3600]
        bad = sum(i["result"] == "불량" for i in r)
        hours.append({"start": h, "total": len(r), "good": len(r) - bad, "defects": bad, "future": h > now,
                      "down_sec": round(st.down(h, min(h + 3600, now))) if h <= now else 0,
                      "target": TARGET_PER_HOUR if h + 3600 <= now else int((now - h) / TARGET_CYCLE_SEC) if h <= now else 0,
                      "current": h <= now < h + 3600})
        h += 3600

    # 오늘 정지 손실 (원인 설비별)
    down_today = st.down(m, now)
    causes_today = {k: round(v) for k, v in st.causes(m, now).items()}

    defects = sum(i["result"] == "불량" for i in insp)
    return {
        "pallet_size": PALLET_SIZE, "truck_pallets": TRUCK_PALLETS, "lot_good": LOT_GOOD,
        "target_cycle": TARGET_CYCLE_SEC, "target_lot_sec": TARGET_LOT_SEC, "target_per_hour": TARGET_PER_HOUR,
        "now": now, "sim": sim_now, "sim_today": sim_today,
        "current": current,
        "last_shipped": lots[-1] if lots else None,
        "lots": ([current] + list(reversed(lots)))[:max_rows],       # 최신 LOT이 위 (맨 위 = 적재 중)
        "hours": hours[-16:],
        # 트럭 출발 타임라인: 오늘 모든 LOT [시작, 끝(적재 중이면 None), 정지 횟수, 속도]
        "timeline": [[l["start"], l["end"], l["stops"], l["speed"]] for l in lots + [current]],
        "plan": {"start": p0, "end": p1, "label": plabel, "target": plan_target,
                 "done": done_in_plan, "forecast": int(forecast)},
        "today": {"total": total, "good": total - defects, "defects": defects,
                  "rate": defects / total if total else None,
                  "trucks": len(lots), "shipped_pallets": len(lots) * TRUCK_PALLETS,
                  "shipped_good": len(lots) * LOT_GOOD,
                  "down_sec": round(down_today), "loss": int(down_today / TARGET_CYCLE_SEC), "causes": causes_today},
    }
