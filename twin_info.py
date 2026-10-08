"""디지털 트윈에서 설비를 눌렀을 때 오른쪽 메뉴에 보여 줄 '그 설비만의' 숫자 (/api/twin/eq?name=)

공통: 건강 점수 · 7일 고장 · 다음 정기 점검 · 반복 고장 경고 (maint_info)
설비별:
  자재 투입기 — 오늘 투입 · 평균 왕복 · 자재 선반 재고(추정) · 배터리(추정)
  프레스 #1  — 오늘 타발 · 안전 정지 · 경고구역 접근
  컨베이어   — 속도 · 가동률 · 멈춘 시간을 원인 설비별로 · 시간대별 가동률
  비전 검사기 — 불량률(최근 50개) · 오늘 검사 · 확인 대기 · 불량 위치 3×3 · 최근 판정 15개
  로봇 적재기 — 오늘 적재 · 집기 성공률(추정) · 평균 사이클
  안전 게이트 — 오늘 입장 · 우회 · 퇴장 · 최근 기록
'추정'이 붙은 값은 실제 센서가 없어서 생산 기록으로 계산한 값이다.
"""
import collections
import datetime
import json
import time
import config
import db
import analytics
from analytics import TARGET_CYCLE_SEC, CONVEYOR

REFILL = int(getattr(config, "SHELF_REFILL", 1500))      # 자재 선반 보충 1회 = 이만큼 (추정 재고 계산용)
BATTERY_HOURS = float(getattr(config, "AMR_BATTERY_HOURS", 4.0))   # AMR 한 번 충전으로 가는 시간 (추정)


def _midnight(ts):
    return datetime.datetime.combine(datetime.date.fromtimestamp(ts), datetime.time()).timestamp()


def _health(name, now):
    try:
        import maint_info
        mi = maint_info.info(now)
        h = next((x for x in mi["health"] if x["name"] == name), None)
        return h
    except Exception:
        return None


def _shift(now):
    w = analytics.window("shift", now)
    a = min(w["start"], now - 1800)
    return a, now


def info(name, now=None):
    now = now or time.time()
    m = _midnight(now)
    insp = db.inspections_between(m, now + 1)
    total = len(insp)
    good = sum(1 for i in insp if i["result"] != "불량")
    a, b = _shift(now)
    segs = analytics.segments({"start": a, "cur": b})
    conv_run = analytics._run(segs.get(CONVEYOR, []), a, b)
    avg_cycle = conv_run / sum(1 for i in insp if i["ts"] >= a) if any(i["ts"] >= a for i in insp) else None
    h = _health(name, now) if name != "안전 게이트" else None
    out = {"name": name, "health": h and {k: h[k] for k in ("score", "fails7", "down7", "repeat", "pm_days", "pm_task", "pm_late")}}

    if name == "자재 투입기":
        since_refill = total % REFILL
        stock = REFILL - since_refill
        hrs = ((now - m) / 3600) % BATTERY_HOURS
        out.update(nums=[["오늘 투입", f"{total:,}", "개"], ["평균 왕복", f"{avg_cycle:.1f}" if avg_cycle else "-", "초"],
                         ["배터리 (추정)", f"{max(5, round(100 - hrs / BATTERY_HOURS * 95))}", "%"]],
                   stock={"left": stock, "ratio": stock / REFILL, "refill": REFILL,
                          "eta_min": round(stock * (avg_cycle or TARGET_CYCLE_SEC) / 60)})
    elif name == "프레스 #1":
        try:
            import safety_info
            k = safety_info.info(now)["kpi"]
        except Exception:
            k = {"stops": None, "warns": None}
        out.update(nums=[["오늘 타발", f"{total:,}", "회"], ["안전 정지", k.get("stops", "-"), "회"], ["경고 접근", k.get("warns", "-"), "회"]])
    elif name == CONVEYOR:
        import production
        st = production.Stops(now)
        causes = st.causes(a, b)
        down = sum(causes.values())
        hours = []
        hh = datetime.datetime.fromtimestamp(a).replace(minute=0, second=0, microsecond=0).timestamp()
        while hh < b:
            e = min(hh + 3600, b)
            hours.append({"h": datetime.datetime.fromtimestamp(hh).strftime("%H"),
                          "ratio": analytics._run(segs.get(CONVEYOR, []), max(hh, a), e) / max(1, e - max(hh, a))})
            hh += 3600
        out.update(nums=[["속도", f"{avg_cycle:.1f}" if avg_cycle else "-", "초/개"], ["벨트 위", "3", "개"],
                         ["가동률", f"{conv_run / max(1, b - a) * 100:.0f}", "%"]],
                   causes=[{"name": k, "sec": round(v)} for k, v in causes.items()], down=round(down), hours=hours[-8:])
    elif name == "비전 검사기":
        last50 = insp[-50:]
        r50 = sum(i["result"] == "불량" for i in last50) / len(last50) if last50 else None
        pending = sum(1 for i in insp if (i.get("disposition") or "") == "자동 격리")
        heat = [0] * 9
        try:
            from quality_info import QUALITY_ROI
            ra, rt, rc, rd = QUALITY_ROI
            for i in insp:
                if i["result"] == "불량" and i.get("box"):
                    bx = json.loads(i["box"]) if isinstance(i["box"], str) else i["box"]
                    fx = min(0.999, max(0.0, ((bx[0] + bx[2]) / 2 - ra) / (rc - ra)))
                    fy = min(0.999, max(0.0, ((bx[1] + bx[3]) / 2 - rt) / (rd - rt)))
                    heat[int(fy * 3) * 3 + int(fx * 3)] += 1           # 위 줄 → 아래 줄, 왼쪽 → 오른쪽
        except Exception:
            pass
        last = insp[-1] if insp else None
        out.update(nums=[["불량률 50개", f"{r50 * 100:.1f}" if r50 is not None else "-", "%"], ["오늘 검사", f"{total:,}", "개"],
                         ["확인 대기", pending, "건"]],
                   heat=heat, recent=[i["result"] == "불량" for i in insp[-15:]],
                   last={"result": last["result"], "conf": last.get("conf"), "ts": last["ts"], "id": last["id"],
                         "type": last.get("defect_type") or ""} if last else None)
    elif name == "로봇 적재기":
        robot_bad = sum(1 for e in db.events_between(m, now + 1, "equipment") if e["event"] == "로봇 적재기 → 고장 정지")
        out.update(nums=[["오늘 적재", f"{good:,}", "개"], ["집기 성공 (추정)", f"{100 - min(5, robot_bad * 0.2):.1f}", "%"],
                         ["평균 사이클", f"{avg_cycle:.1f}" if avg_cycle else "-", "초"]])
    elif name == "안전 게이트":
        ev = db.events_between(m, now + 1, "gate")
        cnt = collections.Counter(e["event"] for e in ev)
        out.update(nums=[["오늘 입장", cnt.get("작업자 입장 승인", 0), "회"], ["관리자 우회", cnt.get("관리자 우회 입장", 0), "회"],
                         ["퇴장", cnt.get("작업자 퇴장", 0), "회"]],
                   log=[{"ts": e["ts"], "event": e["event"]} for e in ev[::-1][:6]])
    return out
