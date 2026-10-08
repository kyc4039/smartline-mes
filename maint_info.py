"""설비 보전 페이지용 집계 (/api/maint/info)

- kpi     : 처리 대기(즉시/당일/정기) · 평균 수리 시간(MTTR) · 평균 고장 간격(MTBF) · 오늘 고장 정지 · 처리 기한(SLA) 준수율
- health  : 설비별 건강 점수(0~100) · 7일 고장 · 정지 시간 · 일별 막대 · 반복 고장 경고 · 다음 정기 점검
- board   : 정비 티켓 진행판 (대기 / 조치 중 / 오늘 완료) + 처리 기한까지 남은 시간
- heat    : 고장 지도 (설비 × 담당 분야, 30일)
- pm      : 예방 정비 일정 (이번 주 월~일) · 완료 체크는 notes 'pm_done'에 저장
- similar(): 같은 설비 · 같은 분야의 지난 정비 사례 (AI 판정 결과 옆에 보여 줌)
설정 (config.py에 없으면 기본값)
  PM_PLAN = [("프레스 #1", "금형 점검", 1), ...]   # (설비, 할 일, 며칠마다) — 1이면 평일 매일
  PM_START = "2026-10-01"                          # 주기 계산 기준일
"""
import collections
import datetime
import json
import time
import config
import db

EQUIPMENT = list(config.EQUIPMENT)
TYPES = ["기계", "전기", "유압공압", "센서"]
SLA = {"상": 30 * 60, "중": 8 * 3600, "하": 7 * 86400}          # 처리 기한: 즉시 30분 · 당일 8시간 · 정기 7일
SLA_NAME = {"상": "30분", "중": "8시간", "하": "7일"}
DAY = 86400

PM_PLAN = list(getattr(config, "PM_PLAN", None) or [
    ("프레스 #1", "금형 점검", 1),
    ("프레스 #1", "유압유 점검", 7),
    ("컨베이어", "벨트 장력", 3),
    ("로봇 적재기", "그리퍼 점검", 5),
    ("비전 검사기", "렌즈 청소", 7),
    ("자재 투입기", "롤러 윤활", 7),
])
try:
    PM_START = datetime.date.fromisoformat(getattr(config, "PM_START", "2026-10-01"))
except ValueError:
    PM_START = datetime.date(2026, 10, 1)

# 담당 분야별 기본 점검 순서 (AI 판정 결과 옆 '추천 점검 순서')
STEPS = {
    "기계": ["이상 소리 · 진동 위치 확인", "볼트 · 체결부 풀림 점검", "가이드 · 베어링 윤활 상태", "마모 부품(벨트 · 패드) 교체 여부"],
    "전기": ["전원 · 차단기 상태 확인", "모터 과열 · 전류 확인", "배선 · 커넥터 접촉", "릴레이 · 인버터 알람 코드"],
    "유압공압": ["유압유 · 공기압 레벨과 누유 확인", "압력 게이지 변동 확인", "밸브 · 호스 연결부", "필터 막힘 점검"],
    "센서": ["센서 표면 오염 · 정렬", "신호 램프 · 출력값 확인", "케이블 · 커넥터", "영점 · 감도 재설정"],
}
EQ_STEP = {"프레스 #1": "정비 전 설비 안전 제어에서 정비 잠금(LOTO)",
           "로봇 적재기": "정비 전 로봇 비상 정지 · 작업 반경 확보"}


def steps(type_, equipment=""):
    s = list(STEPS.get(type_, STEPS["기계"]))
    if equipment in EQ_STEP:
        s.insert(0, EQ_STEP[equipment])
    return s


def _midnight(ts):
    return datetime.datetime.combine(datetime.date.fromtimestamp(ts), datetime.time()).timestamp()


def _all_tickets():
    with db._lock, db._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tickets ORDER BY id")]


def _done_ts(tickets):
    """완료 시각: done_ts 칸 (예전 티켓은 '정비 완료' 이벤트 시각으로 채움)"""
    need = [t for t in tickets if t["status"] == "완료" and not t.get("done_ts")]
    if not need:
        return
    ev = {}
    for e in db.events_between(0, time.time() + 1, "maintenance"):
        if e["event"] == "정비 완료":
            try:
                ev[json.loads(e["detail"] or "{}").get("ticket")] = e["ts"]
            except ValueError:
                pass
    for t in need:
        t["done_ts"] = ev.get(t["id"])


def _feedback_map():
    try:
        return {r["ticket_id"]: r for r in db.all_feedback()}
    except Exception:
        return {}


def similar(equipment, type_, exclude=None, n=3):
    """같은 설비 · 같은 분야의 완료된 정비 (없으면 같은 분야 다른 설비) → 증상 · 조치 메모 · 걸린 시간"""
    ts = [t for t in _all_tickets() if t["status"] == "완료" and t["id"] != exclude and t["type"] == type_]
    _done_ts(ts)
    fb = _feedback_map()
    same = [t for t in ts if t["equipment"] == equipment]
    pick = (same[::-1] + [t for t in ts[::-1] if t["equipment"] != equipment])[:n]
    out = []
    for t in pick:
        f = fb.get(t["id"]) or {}
        start = t.get("started") or t["ts"]
        out.append({"id": t["id"], "ts": t["ts"], "equipment": t["equipment"], "text": t["text"],
                    "note": t.get("action") or f.get("note") or "", "min": round((t["done_ts"] - start) / 60) if t.get("done_ts") else None,
                    "same": t["equipment"] == equipment})
    return out


# ---------------------------------------------------------------- 예방 정비 일정
def _pm_done():
    try:
        return json.loads(db.get_note("pm_done") or "{}")
    except ValueError:
        return {}


def toggle_pm(day, equipment, task, who=""):
    done = _pm_done()
    k = f"{day}|{equipment}|{task}"
    if k in done:
        done.pop(k)
    else:
        done[k] = {"ts": time.time(), "who": who or "작업자"}
        db.log_event("maintenance", "예방 정비 완료", equipment=equipment, task=task, day=day, who=who or "작업자")
    db.set_note("pm_done", json.dumps(done, ensure_ascii=False))


def _due(d, every):
    if every <= 1:
        return d.weekday() < 5                        # 매일 = 평일 매일
    return (d - PM_START).days % every == 0


def pm_week(now=None):
    today = datetime.date.fromtimestamp(now or time.time())
    mon = today - datetime.timedelta(days=today.weekday())
    days = [mon + datetime.timedelta(days=i) for i in range(7)]
    done = _pm_done()
    rows, late = [], 0
    for e in EQUIPMENT:
        cells = []
        for d in days:
            items = []
            for eq, task, every in PM_PLAN:
                if eq != e or not _due(d, every):
                    continue
                k = f"{d.isoformat()}|{eq}|{task}"
                st = "done" if k in done else "late" if d < today else "plan"
                late += st == "late"
                items.append({"task": task, "st": st, "who": (done.get(k) or {}).get("who", "")})
            cells.append(items)
        rows.append({"equipment": e, "cells": cells})
    return {"days": [{"date": d.isoformat(), "dow": "월화수목금토일"[d.weekday()], "day": d.day, "today": d == today} for d in days],
            "rows": rows, "late": late}


def next_pm(equipment, now=None):
    """오늘 이후(오늘 포함) 아직 안 한 첫 정기 점검 → (며칠 뒤, 할 일)"""
    today = datetime.date.fromtimestamp(now or time.time())
    done = _pm_done()
    for i in range(0, 15):
        d = today + datetime.timedelta(days=i)
        for eq, task, every in PM_PLAN:
            if eq == equipment and _due(d, every) and f"{d.isoformat()}|{eq}|{task}" not in done:
                return i, task
    return None, ""


# ---------------------------------------------------------------- 전체 집계
def info(now=None):
    import analytics
    from analytics import TARGET_CYCLE_SEC
    now = now or time.time()
    m = _midnight(now)
    tickets = _all_tickets()
    _done_ts(tickets)
    fb = _feedback_map()
    eqst = {e["name"]: e for e in db.get_equipment()}
    open_ = [t for t in tickets if t["status"] != "완료"]

    # 고장 정지 구간 (7일 · 오늘)
    segs7 = analytics.segments({"start": now - 7 * DAY, "cur": now})
    fault7 = {n: [s for s in segs7.get(n, []) if s["status"] == "고장 정지"] for n in EQUIPMENT}
    ov = lambda s, a, b: max(0.0, min(s["end"], b) - max(s["start"], a))
    down_today = sum(ov(s, m, now) for n in EQUIPMENT for s in fault7[n])

    # MTTR (최근 7일 완료 · 그 전 7일과 비교)
    def mttr(a, b):
        xs = [(t["done_ts"] - (t.get("started") or t["ts"])) for t in tickets
              if t["status"] == "완료" and t.get("done_ts") and a <= t["done_ts"] < b]
        return (sum(xs) / len(xs) / 60, len(xs)) if xs else (None, 0)
    mt, mt_n = mttr(now - 7 * DAY, now)
    mt_prev, _ = mttr(now - 14 * DAY, now - 7 * DAY)
    # MTBF: 최근 7일 가동 시간(교대 시간 × 기록이 있는 날) ÷ 고장(티켓) 수
    t7 = [t for t in tickets if t["ts"] >= now - 7 * DAY]
    days_active = {datetime.date.fromtimestamp(t["ts"]) for t in t7}
    w = analytics.window("shift", now)
    shift_h = max(1.0, (w["end"] - w["start"]) / 3600)
    hours = max(shift_h, len(days_active | {datetime.date.fromtimestamp(now)}) * shift_h)
    mtbf = hours / len(t7) if t7 else None
    # 처리 기한(SLA) 준수율: 최근 7일 완료 티켓 중 기한 안에 끝난 비율
    done7 = [t for t in tickets if t["status"] == "완료" and t.get("done_ts") and t["done_ts"] >= now - 7 * DAY]
    sla_ok = [t for t in done7 if t["done_ts"] - t["ts"] <= SLA.get(t["urgency"], SLA["하"])]

    try:
        from modules.maintenance import feedback_stats
        fs = feedback_stats()
        ai = {"acc": fs["both_acc"], "n": fs["n"]}
    except Exception:
        ai = {"acc": None, "n": 0}

    kpi = {
        "open": len(open_), "open_by": {u: sum(t["urgency"] == u for t in open_) for u in "상중하"},
        "overdue": sum(1 for t in open_ if now - t["ts"] > SLA.get(t["urgency"], SLA["하"])),
        "mttr": round(mt, 1) if mt is not None else None, "mttr_n": mt_n,
        "mttr_prev": round(mt_prev, 1) if mt_prev is not None else None,
        "mtbf": round(mtbf, 1) if mtbf else None, "fails7": len(t7),
        "down_today": round(down_today), "loss_today": int(down_today / TARGET_CYCLE_SEC),
        "sla": round(len(sla_ok) / len(done7), 3) if done7 else None, "sla_n": len(done7),
        "ai": ai,
    }

    # 설비 건강
    pm = pm_week(now)
    late_by = collections.Counter(r["equipment"] for r in pm["rows"] for c in r["cells"] for i in c if i["st"] == "late")
    health = []
    for e in EQUIPMENT:
        mine7 = [t for t in t7 if t["equipment"] == e]
        down7 = sum(s["end"] - s["start"] for s in fault7[e])
        opn = [t for t in open_ if t["equipment"] == e]
        urg = sum(t["urgency"] == "상" for t in opn)
        st = (eqst.get(e) or {}).get("status", "가동")
        score = 100 - len(mine7) * 8 - down7 / 60 * 0.4 - urg * 20 - (len(opn) - urg) * 5 - late_by[e] * 5
        if st == "고장 정지":
            score = min(score, 45)
        score = int(max(5, min(100, round(score))))
        daily = []
        for i in range(6, -1, -1):
            a = m - i * DAY
            daily.append(sum(1 for t in mine7 if a <= t["ts"] < a + DAY))
        rep = collections.Counter(t["type"] for t in mine7).most_common(1)
        nd, ntask = next_pm(e, now)
        health.append({
            "name": e, "score": score, "status": st, "reason": (eqst.get(e) or {}).get("reason", ""),
            "fails7": len(mine7), "down7": round(down7), "open": len(opn), "urgent": urg,
            "open_ids": [t["id"] for t in opn][:3], "daily": daily,
            "repeat": {"type": rep[0][0], "n": rep[0][1]} if rep and rep[0][1] >= 3 else None,
            "pm_days": nd, "pm_task": ntask, "pm_late": late_by[e],
        })

    # 티켓 진행판
    def card(t):
        lim = SLA.get(t["urgency"], SLA["하"])
        f = fb.get(t["id"])
        verdict = None
        if f:
            verdict = "맞음" if f["ai_type"] == f["true_type"] and f["ai_urgency"] == f["true_urgency"] else \
                f"수정 ({f['ai_type']}→{f['true_type']})" if f["ai_type"] != f["true_type"] else \
                f"수정 (조치 시점)"
        end = t.get("done_ts") or now
        return {"id": t["id"], "ts": t["ts"], "equipment": t["equipment"], "text": t["text"], "type": t["type"],
                "urgency": t["urgency"], "status": t["status"], "assignee": t.get("assignee") or "",
                "started": t.get("started"), "done_ts": t.get("done_ts"),
                "sla": lim, "left": round(t["ts"] + lim - now), "took": round(end - (t.get("started") or t["ts"])),
                "in_sla": (end - t["ts"]) <= lim, "verdict": verdict, "note": t.get("action") or (f or {}).get("note", ""),
                "need_review": bool(t.get("need_review"))}
    urank = {"상": 0, "중": 1, "하": 2}
    board = {
        "wait": [card(t) for t in sorted([t for t in open_ if t["status"] != "조치 중"], key=lambda t: (urank.get(t["urgency"], 3), t["ts"]))],
        "doing": [card(t) for t in sorted([t for t in open_ if t["status"] == "조치 중"], key=lambda t: (urank.get(t["urgency"], 3), t["ts"]))],
        "done": [card(t) for t in sorted([t for t in tickets if t["status"] == "완료" and (t.get("done_ts") or 0) >= m],
                                         key=lambda t: -(t.get("done_ts") or 0))][:8],
    }

    # 고장 지도 (30일)
    t30 = [t for t in tickets if t["ts"] >= now - 30 * DAY]
    cnt = collections.Counter((t["equipment"], t["type"]) for t in t30)
    top = cnt.most_common(1)
    heat = {"rows": [{"equipment": e, "cells": [cnt[(e, ty)] for ty in TYPES]} for e in EQUIPMENT],
            "types": TYPES, "total": len(t30), "max": max(cnt.values(), default=0),
            "top": {"equipment": top[0][0][0], "type": top[0][0][1], "n": top[0][1],
                    "share": round(top[0][1] / len(t30), 2)} if top else None}

    return {"now": now, "kpi": kpi, "health": health, "board": board, "heat": heat, "pm": pm,
            "sla_name": SLA_NAME}
