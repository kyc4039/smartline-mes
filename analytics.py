"""설비 분석: 상태 구간 → 타임라인 통계 → OEE → 교대 보고서

핵심 정의
  - 구간(segment): 한 설비가 같은 상태로 있었던 시간 [start, end)
  - 라인 가동 시간 = 컨베이어 '가동' 시간 (어느 설비든 멈추면 컨베이어가 연동 정지하므로)
  - OEE = 가용률 × 성능 × 품질
      가용률 = 라인 가동 시간 / 계획 시간(교대 시작 ~ 지금)
      성능   = 검사 수량 × 목표 사이클 / 라인 가동 시간   (100% 상한)
      품질   = 양품 수 / 검사 수량
설정 (config.py에 없으면 기본값)
  SHIFT_START = "08:00", SHIFT_END = "16:00", TARGET_CYCLE_SEC = 4.0
"""
import datetime
import json
import time
import config
import db
import incidents
from config import EQUIPMENT

SHIFT_START = getattr(config, "SHIFT_START", "08:00")
SHIFT_END = getattr(config, "SHIFT_END", "16:00")
TARGET_CYCLE_SEC = float(getattr(config, "TARGET_CYCLE_SEC", 4.0))
# 10/07 검사기 정지 방식(FLOW_V2): 상자가 비전 검사기에서 INSPECT_SEC(4초) 멈춰 검사 + 다음 상자 이동 1초
#   → 한 개 만드는 시간(택트)은 최소 5초. config의 목표 사이클이 이보다 짧으면 5초로 맞춤 (OEE 성능 · 생산 계획이 실제 속도 기준)
INSPECT_SEC = float(getattr(config, "INSPECT_SEC", 4.0))     # 10/07 저녁: 5초 → 4초 (택트 5초)
if getattr(config, "FLOW_V2", True):
    TARGET_CYCLE_SEC = max(TARGET_CYCLE_SEC, INSPECT_SEC + 1.0)
CONVEYOR = "컨베이어"
BAD = ("안전 정지", "고장 정지")


# ---------------------------------------------------------------- 기간
def _at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m)).timestamp()


def window(kind="shift", now=None):
    """kind: shift(이번 교대) / today(오늘 0시~) / prev(어제 교대)"""
    now = now or time.time()
    today = datetime.date.fromtimestamp(now)
    if kind == "today":
        a = _at(today, "00:00"); b = a + 86400; label = "오늘"
    elif kind == "prev":
        d = today - datetime.timedelta(days=1)
        a, b = _at(d, SHIFT_START), _at(d, SHIFT_END); label = f"어제 교대 ({SHIFT_START}~{SHIFT_END})"
    else:
        a, b = _at(today, SHIFT_START), _at(today, SHIFT_END); label = f"이번 교대 ({SHIFT_START}~{SHIFT_END})"
    if b <= a:
        b += 86400                                  # 야간 교대 (예: 22:00~06:00)
        if kind != "today" and now < a and a - 86400 <= now < b - 86400:
            a, b = a - 86400, b - 86400             # 자정이 지난 뒤에는 어제 저녁에 시작한 교대가 '이번 교대'
            if kind == "prev":
                a, b = a - 86400, b - 86400
    cur = max(a, min(now, b))
    return {"kind": kind, "label": label, "start": a, "end": b, "cur": cur, "elapsed": cur - a}


# ---------------------------------------------------------------- 구간
def _reason(e):
    try:
        return json.loads(e.get("detail") or "{}").get("reason", "")
    except ValueError:
        return ""


def segments(w):
    """설비별 상태 구간. 기간 시작 전 마지막 상태를 이어받아 시작한다."""
    status = {n: "가동" for n in EQUIPMENT}
    reason = {n: "" for n in EQUIPMENT}
    since = {n: w["start"] for n in EQUIPMENT}
    segs = {n: [] for n in EQUIPMENT}
    for e in db.equipment_events_until(w["cur"]):
        if " → " not in e["event"]:
            continue
        name, st = e["event"].split(" → ", 1)
        if name not in status:
            continue
        if e["ts"] <= w["start"]:
            status[name], reason[name] = st, _reason(e)
            continue
        if e["ts"] > since[name]:
            segs[name].append({"status": status[name], "start": since[name], "end": e["ts"], "reason": reason[name]})
        status[name], reason[name], since[name] = st, _reason(e), e["ts"]
    for n in EQUIPMENT:
        if w["cur"] > since[n]:
            segs[n].append({"status": status[n], "start": since[n], "end": w["cur"], "reason": reason[n], "open": True})
    return segs


def _overlap(seg, a, b):
    return max(0.0, min(seg["end"], b) - max(seg["start"], a))


def _run(segs, a, b):
    return sum(_overlap(s, a, b) for s in segs if s["status"] == "가동")


# ---------------------------------------------------------------- 타임라인
def timeline(kind="shift"):
    w = window(kind)
    segs = segments(w)
    incs = incidents.build(db.events_since(w["start"] - 1))

    # 정지 구간에 사건 정보 붙이기 (원인·연쇄·복구)
    for name, ss in segs.items():
        for s in ss:
            if s["status"] in BAD:
                inc = next((i for i in incs if i["equipment"] == name and abs(i["start"] - s["start"]) < 2), None)
            elif s["status"] == "연동 정지":
                inc = next((i for i in incs if any(st["kind"] == "linked" and abs(st["ts"] - s["start"]) < 2
                                                     for st in i["steps"])), None)
            else:
                inc = None
            if inc:
                s["incident"] = {"no": inc["no"], "cause": inc["equipment"], "status": inc["status"],
                                 "steps": [st["title"] for st in inc["steps"]], "recovery": inc["recovery"]}

    rows, bad_durations = [], []
    for name in EQUIPMENT:
        ss = segs[name]
        run = _run(ss, w["start"], w["cur"])
        stops = [s for s in ss if s["status"] != "가동"]
        down = sum(s["end"] - s["start"] for s in stops)
        bad_durations += [s["end"] - s["start"] for s in stops if s["status"] in BAD and not s.get("open")]
        rows.append({"name": name, "segments": ss, "run_ratio": run / w["elapsed"] if w["elapsed"] else None,
                     "stops": len(stops), "downtime": down,
                     "bad_stops": sum(s["status"] in BAD for s in stops)})
    longest = max(rows, key=lambda r: r["downtime"])
    frequent = max(rows, key=lambda r: r["bad_stops"])
    return {"window": w, "rows": rows,
            "mttr": sum(bad_durations) / len(bad_durations) if bad_durations else None,
            "mttr_n": len(bad_durations),
            "longest": {"name": longest["name"], "downtime": longest["downtime"]} if longest["downtime"] else None,
            "frequent": {"name": frequent["name"], "stops": frequent["bad_stops"]} if frequent["bad_stops"] else None}


# ---------------------------------------------------------------- OEE
def _oee_parts(run, elapsed, total, defects):
    A = run / elapsed if elapsed > 0 else None
    P = min(1.0, total * TARGET_CYCLE_SEC / run) if run > 0 and total > 0 else None
    Q = (total - defects) / total if total > 0 else None
    O = A * P * Q if None not in (A, P, Q) else None
    return A, P, Q, O


def oee(kind="shift", tl=None):
    tl = tl or timeline(kind)
    w = tl["window"]
    segs = {r["name"]: r["segments"] for r in tl["rows"]}
    conv = segs[CONVEYOR]
    run = _run(conv, w["start"], w["cur"])
    insp = db.inspections_between(w["start"], w["cur"])
    total, defects = len(insp), sum(i["result"] == "불량" for i in insp)
    A, P, Q, O = _oee_parts(run, w["elapsed"], total, defects)

    # 정지 손실: 컨베이어가 멈춘 시간을 원인(안전 정지 / 고장 정지 / 기타)별로
    loss = {"안전 정지": 0.0, "고장 정지": 0.0, "기타 정지": 0.0}
    count = {"안전 정지": 0, "고장 정지": 0, "기타 정지": 0}
    for s in conv:
        if s["status"] == "가동":
            continue
        cause = s["status"] if s["status"] in BAD else (s.get("incident") or {}).get("status", "기타 정지")
        cause = cause if cause in loss else "기타 정지"
        loss[cause] += s["end"] - s["start"]; count[cause] += 1
    ideal = total * TARGET_CYCLE_SEC
    losses = {
        "planned": w["elapsed"] / 60,
        "stops": [{"name": k, "minutes": v / 60, "count": count[k]} for k, v in loss.items() if v > 0],
        "speed": max(0.0, run - ideal) / 60,
        "quality": defects * TARGET_CYCLE_SEC / 60,
        "effective": min(run, (total - defects) * TARGET_CYCLE_SEC) / 60,
    }

    per_eq = []
    for name in EQUIPMENT:
        a = _run(segs[name], w["start"], w["cur"]) / w["elapsed"] if w["elapsed"] else None
        per_eq.append({"name": name, "availability": a,
                       "oee": a * P * Q if None not in (a, P, Q) else None,
                       "stops": next(r["bad_stops"] for r in tl["rows"] if r["name"] == name)})
    # 컨베이어는 다른 설비 때문에 연동 정지하는 '피해자'라서, 원인 설비를 찾을 때는 제외
    worst = min((e for e in per_eq if e["availability"] is not None and e["name"] != CONVEYOR),
                key=lambda e: e["availability"], default=None)

    # 시간대별: 정시(22시, 23시 ...) 기준으로 나눔. 교대 시작·지금이 걸친 시간은 부분 구간
    hourly, h = [], w["start"]
    while h < w["cur"]:
        he = min(datetime.datetime.fromtimestamp(h).replace(minute=0, second=0, microsecond=0).timestamp() + 3600, w["cur"])
        hi = [i for i in insp if h <= i["ts"] < he]
        a, p, q, o = _oee_parts(_run(conv, h, he), he - h, len(hi), sum(i["result"] == "불량" for i in hi))
        hourly.append({"hour": datetime.datetime.fromtimestamp(h).strftime("%H"), "availability": a, "oee": o,
                       "minutes": (he - h) / 60, "partial": he - h < 3599, "stops_min": (he - h - _run(conv, h, he)) / 60})
        h = he

    return {"window": w, "availability": A, "performance": P, "quality": Q, "oee": O,
            "total": total, "defects": defects, "run_minutes": run / 60, "target_cycle": TARGET_CYCLE_SEC,
            "losses": losses, "per_equipment": per_eq,
            "worst": worst if worst and worst["availability"] is not None and worst["availability"] < 0.999 else None,
            "hourly": hourly}


# ---------------------------------------------------------------- 교대 보고서
def report(kind="shift"):
    tl = timeline(kind)
    o = oee(kind, tl)
    w = tl["window"]
    incs = [i for i in incidents.build(db.events_since(w["start"] - 1)) if i["start"] >= w["start"] - 1]
    insp = db.inspections_between(w["start"], w["cur"])
    types = {}
    for i in insp:
        for t in (i["defect_type"] or "").split(", "):
            if t:
                types[t] = types.get(t, 0) + 1
    over = [e for e in db.events_between(w["start"], w["cur"], "rules") if "불량률" in e["event"]]
    fb = {f["ticket_id"]: f for f in db.all_feedback()}
    tickets = []
    for t in db.tickets_between(w["start"], w["cur"]):
        f = fb.get(t["id"])
        t["ai_check"] = None if not f else ("맞음" if f["true_type"] == t["type"] and f["true_urgency"] == t["urgency"]
                                            else f"수정 → {f['true_type']}·{f['true_urgency']}")
        tickets.append(t)
    fb_shift = [fb[t["id"]] for t in tickets if t["id"] in fb]
    ai_ok = sum(f["true_type"] == f["ai_type"] and f["true_urgency"] == f["ai_urgency"] for f in fb_shift)
    missed = sum(f["true_urgency"] == "상" and f["ai_urgency"] != "상" for f in fb_shift)
    line_down = sum(s["end"] - s["start"] for s in next(r for r in tl["rows"] if r["name"] == CONVEYOR)["segments"]
                    if s["status"] != "가동")

    # 다음 조 인계 사항 자동 제안
    hints = []
    for t in tickets:
        if t["status"] != "완료":
            hints.append(f"정비 요청 #{t['id']} {t['equipment']} '{t['text']}' 미완료 — 다음 조 확인 필요")
    same = {}
    for i in incs:
        same[(i["equipment"], i["status"])] = same.get((i["equipment"], i["status"]), 0) + 1
    for (eq, st), n in same.items():
        if n >= 2:
            hints.append(f"{eq} {st}가 이번 교대에 {n}회 — 원인 점검 필요")
    if over:
        hints.append(f"불량률 기준 초과 {len(over)}회 — 품질 추이 확인")

    key = f"{datetime.date.fromtimestamp(w['start'])}-{kind}"
    return {"window": w, "key": key, "oee": {k: o[k] for k in ("availability", "performance", "quality", "oee")},
            "summary": {"production": o["total"], "defects": o["defects"],
                        "defect_rate": o["defects"] / o["total"] if o["total"] else None,
                        "line_down_min": line_down / 60, "incidents": len(incs),
                        "tickets_done": sum(t["status"] == "완료" for t in tickets), "tickets": len(tickets)},
            "incidents": incs, "defect_types": types, "rate_over": [e["ts"] for e in over],
            "tickets": tickets, "ai": {"n": len(fb_shift), "ok": ai_ok, "missed": missed},
            "hints": hints, "memo": db.get_note(key)}
