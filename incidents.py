"""사건 묶기: 흩어진 이벤트를 '원인 → 정지 → 연쇄 영향 → 복구' 한 줄의 사건으로 엮는다.

사건의 시작: 어떤 설비가 '안전 정지' 또는 '고장 정지'가 되는 순간
사건의 끝  : 그 설비가 다시 '가동'이 되는 순간
단계(steps):
  cause    원인      안전 정지 → 위험구역 감지(손 등) / 비상 정지 버튼, 고장 정지 → 고장 보고 티켓
  stop     즉시 반응  원인 설비 정지
  linked   연쇄 영향  컨베이어 연동 정지 (사건이 열려 있는 동안)
  recover  복구      5초 비움 자동 재가동 / 정비 완료 (예전 기록의 '수신호 승인'도 그대로 읽음)
"""
import datetime
import json
import db

CONVEYOR = "컨베이어"


def _detail(e):
    try:
        return json.loads(e.get("detail") or "{}")
    except ValueError:
        return {}


def build(events):
    incidents, open_by_eq = [], {}
    for e in events:
        ev, ts, mod = e["event"], e["ts"], e["module"]

        if mod == "equipment" and " → " in ev:
            name, status = ev.split(" → ", 1)
            reason = _detail(e).get("reason", "")

            if status in ("안전 정지", "고장 정지") and name not in open_by_eq:
                inc = {"no": len(incidents) + 1, "equipment": name, "status": status, "reason": reason,
                       "start": ts, "end": None, "recovery": None, "steps": []}
                if status == "안전 정지":
                    label = "비상 정지 버튼" if "비상" in reason else "위험구역 감지"
                    inc["steps"].append({"kind": "cause", "title": label, "source": "CAM 3 · 프레스 금형부" if label == "위험구역 감지" else "작업자 조작",
                                         "detail": reason, "ts": ts})
                else:
                    tid = int(reason.split("#")[-1]) if "#" in reason else None
                    t = db.get_ticket(tid) if tid else None
                    inc["ticket"] = tid
                    inc["steps"].append({"kind": "cause", "title": "고장 보고", "source": f"정비 요청 #{tid}" if tid else "정비 요청",
                                         "detail": t["text"] if t else "", "ts": (t["ts"] if t else ts)})
                inc["steps"].append({"kind": "stop", "title": f"{name} {status}", "ts": ts})
                incidents.append(inc)
                open_by_eq[name] = inc

            elif status == "연동 정지" and name == CONVEYOR and open_by_eq:
                inc = list(open_by_eq.values())[-1]
                if not any(s["kind"] == "linked" for s in inc["steps"]):
                    inc["steps"].append({"kind": "linked", "title": f"{CONVEYOR} 연동 정지", "ts": ts})

            elif status == "가동" and name in open_by_eq:
                inc = open_by_eq.pop(name)
                inc["end"] = ts
                inc["recovery"] = inc.get("_hint") or ("정비 완료" if inc["status"] == "고장 정지" else "재가동")
                inc["steps"].append({"kind": "recover", "title": inc["recovery"], "ts": ts})

        # 복구 방법 힌트 (재가동 직전에 기록되는 이벤트)
        elif mod == "rules" and "수신호 승인" in ev and "프레스 #1" in open_by_eq:
            open_by_eq["프레스 #1"]["_hint"] = "수신호 승인"
        elif mod == "safety" and "자동 재가동" in ev and "프레스 #1" in open_by_eq:
            open_by_eq["프레스 #1"]["_hint"] = "구역 비움 자동 재가동"
        elif mod == "maintenance" and ev == "정비 완료":
            eq = _detail(e).get("equipment")
            if eq in open_by_eq:
                open_by_eq[eq]["_hint"] = f"정비 완료 #{_detail(e).get('ticket')}"

    for inc in incidents:
        inc.pop("_hint", None)
        same = [i for i in incidents if i["equipment"] == inc["equipment"] and i["status"] == inc["status"] and i["no"] <= inc["no"]]
        inc["nth_today"] = len(same)
    return incidents


def today():
    midnight = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
    incs = build(db.events_since(midnight))
    active = [i for i in incs if i["end"] is None]
    done = [i for i in incs if i["end"] is not None][::-1][:6]
    return {"active": active, "recent": done}
