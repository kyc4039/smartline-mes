"""디지털 트윈 고도화용 데이터

layers(kind)  ① 레이어: 설비별 정지 빈도 · OEE · 정비 요청 + ② 오늘의 불량 배출/위험구역 진입 요약
replay(kind)  ③ 리플레이: 기간 안의 설비 상태 구간 + 사건 표식 + 불량 시각
(④ 가정 시뮬레이션은 /api/oee 결과를 그대로 받아 화면에서 계산한다)

새로 저장하는 데이터는 없다. 이미 쌓이는 events / inspections / tickets 표만 다시 읽는다.
"""
import datetime
import json
import time
import analytics
import db
import incidents
from config import EQUIPMENT

PRESS = "프레스 #1"
BAD = ("안전 정지", "고장 정지")


def _detail(e):
    try:
        return json.loads(e.get("detail") or "{}")
    except ValueError:
        return {}


def _midnight(now=None):
    d = datetime.date.fromtimestamp(now or time.time())
    return datetime.datetime.combine(d, datetime.time()).timestamp()


# ---------------------------------------------------------------- ② 오늘 요약
def summary():
    now = time.time()
    m = _midnight(now)
    insp = db.inspections_between(m, now + 1)
    bad = [i for i in insp if i["result"] == "불량"]
    zone = [e for e in db.events_between(m, now + 1, "equipment")
            if e["event"] == f"{PRESS} → 안전 정지" and "비상" not in _detail(e).get("reason", "")]
    entries = [e for e in db.events_between(m, now + 1, "gate") if e["event"] in ("작업자 입장 승인", "관리자 우회 입장")]
    return {"defects_today": len(bad), "zone_today": len(zone),
            "inspections_today": len(insp), "entries_today": len(entries),
            "last_entry": entries[-1]["ts"] if entries else None,
            "last_defect": bad[-1]["ts"] if bad else None,
            "last_defect_type": bad[-1]["defect_type"] if bad else ""}


# ---------------------------------------------------------------- ① 레이어
def layers(kind="shift"):
    tl = analytics.timeline(kind)
    o = analytics.oee(kind, tl)
    w = tl["window"]
    per = {e["name"]: e for e in o["per_equipment"]}
    in_window = db.tickets_between(w["start"], w["cur"] + 1)
    waiting = db.open_tickets()
    eq = {}
    for r in tl["rows"]:
        n = r["name"]
        mine = [t for t in waiting if t["equipment"] == n]
        eq[n] = {"stops": r["stops"], "bad_stops": r["bad_stops"], "downtime": r["downtime"],
                 "availability": per[n]["availability"], "oee": per[n]["oee"],
                 "tickets": sum(t["equipment"] == n for t in in_window),
                 "open": len(mine), "urgent": sum(t["urgency"] == "상" for t in mine)}
    return {"window": w, "equipment": eq, "summary": summary()}


# ---------------------------------------------------------------- ③ 리플레이
def _replay_window(kind):
    now = time.time()
    if kind == "hour":
        return {"kind": "hour", "label": "최근 1시간", "start": now - 3600, "end": now, "cur": now, "elapsed": 3600}
    return analytics.window(kind, now)


def replay(kind="hour"):
    w = _replay_window(kind)
    segs = analytics.segments(w) if w["cur"] > w["start"] else {n: [] for n in EQUIPMENT}
    markers, defects = [], []
    for e in db.events_between(w["start"], w["cur"] + 1):
        ev, mod, d = e["event"], e["module"], _detail(e)
        if mod == "equipment" and " → " in ev:
            name, st = ev.split(" → ", 1)
            if st in BAD:
                markers.append({"ts": e["ts"], "tone": "bad", "label": f"{name} {st}", "short": "정지"})
            elif st == "가동" and name != "컨베이어":
                markers.append({"ts": e["ts"], "tone": "ok", "label": f"{name} 재가동", "short": "재가동"})
        elif mod == "quality" and ev == "불량 검출":
            defects.append({"ts": e["ts"], "type": d.get("defect_type") or ""})
        elif mod == "rules" and "불량률" in ev:
            markers.append({"ts": e["ts"], "tone": "warn", "label": "불량률 기준 초과", "short": "품질 경고"})
        elif mod == "maintenance" and ev == "정비 요청 접수":
            markers.append({"ts": e["ts"], "tone": "data", "label": f"정비 요청 #{d.get('ticket', '')} {d.get('equipment', '')}",
                            "short": "정비 요청"})
    incs = [i for i in incidents.build(db.events_since(w["start"] - 3600))
            if (i["end"] or w["cur"]) >= w["start"] and i["start"] <= w["cur"]]
    return {"window": w, "segments": segs, "markers": markers, "defects": defects, "incidents": incs}
