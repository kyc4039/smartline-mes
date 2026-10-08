"""관제 대시보드 요약 (/api/dashboard) — 각 페이지의 '핵심 숫자 하나씩' + '지금 할 일' + 오늘 설비 상태 띠

페이지별 집계(production · oee · safety_info · maint_info)를 그대로 불러 쓰고, 여기서는 고르고 합치기만 한다.
"""
import datetime
import math
import time
import config
import db
import analytics
from analytics import CONVEYOR
from config import EQUIPMENT

OEE_TARGET = float(getattr(config, "OEE_TARGET", 0.75))
RATE_LIMIT = float(getattr(config, "DEFECT_RATE_LIMIT", 0.03))
PENDING = "자동 격리"


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        print(f"[dashboard] {getattr(fn, '__name__', 'fn')} 실패: {e}")
        return default


def _midnight(ts):
    return datetime.datetime.combine(datetime.date.fromtimestamp(ts), datetime.time()).timestamp()


def summary(now=None):
    now = now or time.time()
    m = _midnight(now)
    eq = {e["name"]: e for e in db.get_equipment()}

    # ---- OEE (이번 교대)
    o = _safe(lambda: analytics.oee("shift"), {}) or {}
    parts = [("가용률", o.get("availability")), ("성능", o.get("performance")), ("품질", o.get("quality"))]
    vals = [p for p in parts if p[1] is not None]
    low = min(vals, key=lambda p: p[1])[0] if vals else None
    oee = {"oee": o.get("oee"), "target": OEE_TARGET, "low": low}

    # ---- 생산 · 출하
    import production
    ps = _safe(production.summary, None)
    prod = None
    if ps:
        c, t, pl = ps["current"], ps["today"], ps["plan"]
        prod = {"done": pl["done"], "target": pl["target"], "forecast": pl["forecast"], "plan_label": pl["label"],
                "trucks": t["trucks"], "lot": c["id"], "pallets": c["pallets"], "fill": c["pallet_fill"],
                "truck_pallets": ps["truck_pallets"], "pallet_size": ps["pallet_size"], "eta": c["eta_sec"],
                "good_total": t["shipped_good"] + c["good"], "defects_today": t["defects"], "sim": ps["sim"],
                "last_insp": c.get("last_insp"), "now": now}

    # ---- 품질: 최근 50개 불량률 · 관리 한계 · 확인 대기 · 시간대별 불량률(작은 선)
    insp = db.inspections_between(m, now + 1)
    last50 = insp[-50:]
    r50 = sum(i["result"] == "불량" for i in last50) / len(last50) if last50 else None
    pbar = sum(i["result"] == "불량" for i in insp) / len(insp) if insp else None
    ucl = pbar + 3 * math.sqrt(pbar * (1 - pbar) / 50) if pbar is not None else None
    spark = []
    h = datetime.datetime.fromtimestamp(m).replace(hour=0).timestamp()
    for hh in range(24):
        a = m + hh * 3600
        if a > now:
            break
        xs = [i for i in insp if a <= i["ts"] < a + 3600]
        if xs:
            spark.append(round(sum(i["result"] == "불량" for i in xs) / len(xs), 4))
    quality = {"rate50": r50, "ucl": ucl, "out": bool(r50 is not None and ucl is not None and r50 > ucl),
               "limit": RATE_LIMIT, "pending": sum(1 for i in insp if (i.get("disposition") or "") == PENDING),
               "spark": spark[-10:]}

    # ---- 안전
    import safety_info
    si = _safe(safety_info.info, None)
    safety = None
    if si:
        k = si["kpi"]
        ck = si["check"]
        safety = {"stops": k["stops"], "warns": k["warns"], "safe_days": k["safe_days"],
                  "check_done": sum(1 for c in ck if c.get("ts")), "check_total": len(ck),
                  "check_left": [c["text"] for c in ck if not c.get("ts")], "lock": si["lock"]}

    # ---- 정비
    import maint_info
    mi = _safe(maint_info.info, None)
    maint = None
    if mi:
        k = mi["kpi"]
        worst = min(mi["health"], key=lambda h: h["score"]) if mi["health"] else None
        late = [(r["equipment"], it["task"], mi["pm"]["days"][j]["date"]) for r in mi["pm"]["rows"]
                for j, cell in enumerate(r["cells"]) for it in cell if it["st"] == "late"]
        maint = {"open": k["open"], "open_by": k["open_by"], "overdue": k["overdue"],
                 "worst": {"name": worst["name"], "score": worst["score"]} if worst else None,
                 "health": {h["name"]: h["score"] for h in mi["health"]}, "pm_late": late,
                 "urgent": [t for t in mi["board"]["wait"] + mi["board"]["doing"] if t["urgency"] == "상"],
                 "today_n": sum(1 for t in mi["board"]["wait"] if t["urgency"] == "중")}

    # ---- 지금 할 일 (급한 순서)
    acts = []
    for n in EQUIPMENT:
        e = eq.get(n) or {}
        st, rs = e.get("status"), e.get("reason") or ""
        if st == "안전 정지":
            if "정비 잠금" in rs:
                acts.append({"lv": "y", "icon": "🔒", "title": f"{n} 정비 잠금 중", "sub": f"{(safety or {}).get('lock', {}) and safety['lock'].get('who', '')} 정비 중 · 끝나면 설비 보전에서 완료",
                             "link": "/maintenance", "go": "보전"})
            elif "비상" in rs:
                acts.append({"lv": "r", "icon": "■", "title": f"{n} 비상 정지", "sub": "안전 확인 후 관리자 수동 재가동", "link": "/safety", "go": "안전"})
            else:
                acts.append({"lv": "r", "icon": "■", "title": f"{n} 안전 정지 진행 중", "sub": "위험구역이 비면 몇 초 뒤 자동 재가동", "link": "/safety", "go": "안전"})
        elif st == "고장 정지":
            acts.append({"lv": "r", "icon": "■", "title": f"{n} 고장 정지", "sub": rs or "정비 요청 확인", "link": "/maintenance", "go": "보전"})
    for t in (maint or {}).get("urgent", [])[:3]:
        acts.append({"lv": "r", "icon": "🔧", "title": f"#{t['id']} {t['equipment']} · {t['text'][:22]}",
                     "sub": f"즉시 · {t['type']} · " + (f"👷 {t['assignee']} 조치 중" if t["status"] == "조치 중" else "배정 대기"),
                     "left": t["left"], "link": "/maintenance", "go": "정비"})
    if quality["out"]:
        acts.append({"lv": "r", "icon": "▲", "title": "불량률 관리 한계 이탈", "sub": f"최근 50개 {quality['rate50'] * 100:.1f}% > 한계 {quality['ucl'] * 100:.1f}%", "link": "/quality", "go": "품질"})
    if quality["pending"]:
        acts.append({"lv": "y", "icon": "?", "title": f"불량 확인 대기 {quality['pending']}건", "sub": "자동 격리됨 · 불량 확인 / 오판 / 정비 요청", "link": "/quality", "go": "품질"})
    if maint and maint["overdue"]:
        acts.append({"lv": "y", "icon": "⏱", "title": f"처리 기한 넘긴 정비 {maint['overdue']}건", "sub": "설비 보전 진행판에서 확인", "link": "/maintenance", "go": "보전"})
    if maint and maint["pm_late"]:
        e0, t0, d0 = maint["pm_late"][0]
        acts.append({"lv": "y", "icon": "📅", "title": f"예방 정비 지연 · {e0} {t0}" + (f" 외 {len(maint['pm_late']) - 1}건" if len(maint["pm_late"]) > 1 else ""),
                     "sub": f"{d0[5:].replace('-', '/')} 예정", "link": "/maintenance", "go": "보전"})
    if safety and safety["check_done"] < safety["check_total"]:
        acts.append({"lv": "b", "icon": "✓", "title": f"교대 전 안전 점검 {safety['check_total'] - safety['check_done']}개 남음",
                     "sub": " · ".join(safety["check_left"][:2]), "link": "/safety", "go": "안전"})
    if maint and maint["today_n"]:
        acts.append({"lv": "b", "icon": "🔧", "title": f"오늘 안에 할 정비 {maint['today_n']}건", "sub": "당일 조치", "link": "/maintenance", "go": "보전"})

    # ---- 오늘 설비 상태 띠 (교대 시작 ~ 지금)
    w = analytics.window("shift", now)
    a0 = min(w["start"], now - 3600)
    segs = analytics.segments({"start": a0, "cur": now})
    bands, longest, n_stop = [], None, 0
    order = [n for n in ("자재 투입기", "프레스 #1", "컨베이어", "비전 검사기", "로봇 적재기") if n in EQUIPMENT]
    order += [n for n in EQUIPMENT if n not in order]           # 공정 순서대로
    for n in order:
        ss = [{"s": s["start"], "e": s["end"], "st": s["status"]} for s in segs.get(n, []) if s["status"] != "가동"]
        for s in ss:
            if s["st"] in ("안전 정지", "고장 정지"):
                n_stop += 1
                if not longest or s["e"] - s["s"] > longest["sec"]:
                    longest = {"name": n, "sec": s["e"] - s["s"]}
        bands.append({"name": n, "segs": ss})

    # ---- 설비별 한 줄 숫자 (공정 라인 아래 칸)
    stations = {
        "자재 투입기": f"건강 {maint['health'].get('자재 투입기', '-')}" if maint else "",
        "프레스 #1": f"오늘 안전 정지 {safety['stops']}회" if safety else "",
        "컨베이어": "프레스 때문" if (eq.get(CONVEYOR) or {}).get("status") == "연동 정지" else f"{analytics.TARGET_CYCLE_SEC:g}초에 1개",
        "비전 검사기": f"불량률 {r50 * 100:.1f}%" if r50 is not None else "검사 기록 없음",
        "로봇 적재기": f"팔레트 {prod['fill']}/{prod['pallet_size']}" if prod else "",
    }
    return {"now": now, "oee": oee, "prod": prod, "quality": quality, "safety": safety, "maint": maint,
            "actions": acts[:8], "actions_n": len(acts),
            "bands": {"start": a0, "cur": now, "rows": bands, "stops": n_stop, "longest": longest},
            "stations": stations}
