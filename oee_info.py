"""OEE 페이지 집계 (/api/oee/info?range=shift|today|prev|week)

analytics.oee()는 관제 대시보드 · 교대 보고서가 같이 쓰므로 그대로 두고, 이 파일은 OEE 페이지 전용으로
  - 손실 폭포 (정지: 안전 / 고장 / 짧은 정지(1분 미만) / 기타 → 속도 → 품질 → 좋은 제품 시간) + 양품 개수 · 트럭 대수 환산
  - 개선 기회 TOP 3 (그 손실이 없었다면 OEE가 몇 %p 오르나)
  - 최근 7일 추이 · 요일 × 시간 OEE 지도 (날마다 교대 시간 기준)
  - 가정 시뮬레이터에 필요한 기준 숫자
를 계산한다.
설정 (config.py에 없으면 기본값)
  OEE_TARGET = 0.75     # 우리 목표 (세계 수준 85%는 고정)
"""
import datetime
import time
import config
import db
import analytics
from analytics import TARGET_CYCLE_SEC, CONVEYOR, BAD, SHIFT_START, SHIFT_END, _run, _at, _oee_parts
from config import EQUIPMENT

TARGET = float(getattr(config, "OEE_TARGET", 0.75))
WORLD = 0.85
SHORT_SEC = 60                      # 이보다 짧은 정지 = 짧은 정지(순간 정지)
CAUSES = ["안전 정지", "고장 정지", "짧은 정지", "기타 정지"]
LINK = {"안전 정지": "/safety", "고장 정지": "/maintenance", "짧은 정지": "/timeline", "기타 정지": "/timeline",
        "속도": "/timeline", "품질": "/quality"}


def _lot_good():
    try:
        import production
        return production.LOT_GOOD
    except Exception:
        return 80


def _shift_window(day, now):
    """그날의 교대 시간 [a, cur] (지금보다 뒤는 자름). 아직 시작 안 했으면 None"""
    a, b = _at(day, SHIFT_START), _at(day, SHIFT_END)
    if b <= a:
        b += 86400
    cur = min(now, b)
    return (a, b, cur) if cur > a + 60 else None


def _cause(seg, segs):
    """컨베이어 정지 구간의 원인: 안전 정지 / 고장 정지 / 짧은 정지 / 기타 정지"""
    if seg["end"] - seg["start"] < SHORT_SEC:
        return "짧은 정지"
    if seg["status"] in BAD:
        return seg["status"]
    best, ov = None, 0.0                     # 연동 정지 → 같은 시간에 멈춰 있던 다른 설비의 상태
    for n, ss in segs.items():
        if n == CONVEYOR:
            continue
        for s in ss:
            if s["status"] in BAD:
                o = max(0.0, min(s["end"], seg["end"]) - max(s["start"], seg["start"]))
                if o > ov:
                    best, ov = s["status"], o
    return best or "기타 정지"


def calc(a, cur, insp=None):
    """[a, cur] 동안의 원재료 숫자 (여러 날을 더할 수 있게 합계로)"""
    segs = analytics.segments({"start": a, "cur": cur})
    conv = segs[CONVEYOR]
    insp = db.inspections_between(a, cur) if insp is None else insp
    total, defects = len(insp), sum(i["result"] == "불량" for i in insp)
    loss = {k: 0.0 for k in CAUSES}
    count = {k: 0 for k in CAUSES}
    for s in conv:
        if s["status"] == "가동":
            continue
        d = max(0.0, min(s["end"], cur) - max(s["start"], a))
        if d <= 0:
            continue
        k = _cause(s, segs)
        loss[k] += d
        count[k] += 1
    eq_run = {n: _run(segs[n], a, cur) for n in EQUIPMENT}
    eq_bad = {n: sum(1 for s in segs[n] if s["status"] in BAD) for n in EQUIPMENT}
    return {"elapsed": cur - a, "run": _run(conv, a, cur), "total": total, "defects": defects,
            "loss": loss, "count": count, "eq_run": eq_run, "eq_bad": eq_bad, "segs": segs, "insp": insp}


def _add(x, y):
    if x is None:
        return y
    out = {k: x[k] + y[k] for k in ("elapsed", "run", "total", "defects")}
    out["loss"] = {k: x["loss"][k] + y["loss"][k] for k in CAUSES}
    out["count"] = {k: x["count"][k] + y["count"][k] for k in CAUSES}
    out["eq_run"] = {k: x["eq_run"][k] + y["eq_run"][k] for k in EQUIPMENT}
    out["eq_bad"] = {k: x["eq_bad"][k] + y["eq_bad"][k] for k in EQUIPMENT}
    return out


def _oee(r):
    A, P, Q, O = _oee_parts(r["run"], r["elapsed"], r["total"], r["defects"])
    return {"availability": A, "performance": P, "quality": Q, "oee": O}


def _days(now, n=7, back=21):
    """최근 n일(기록이 있는 날, 오늘 포함)의 교대 시간 창"""
    out = []
    today = datetime.date.fromtimestamp(now)
    for i in range(back):
        d = today - datetime.timedelta(days=i)
        w = _shift_window(d, now)
        if not w:
            continue
        if not db.inspections_between(w[0], w[2])[:1] and i > 0:
            continue                          # 기록이 없는 날(주말 등)은 건너뜀
        out.append((d, w))
        if len(out) >= n:
            break
    return out[::-1]


def info(kind="shift", now=None):
    now = now or time.time()
    lot_good = _lot_good()
    days = _days(now)

    # ---- 선택한 기간
    if kind == "week":
        r = None
        for d, (a, b, cur) in days:
            r = _add(r, calc(a, cur))
        r = r or calc(now - 60, now)
        label = f"최근 {len(days)}일 (교대 시간 합계)"
        span = None
    else:
        w = analytics.window(kind, now)
        r = calc(w["start"], w["cur"])
        label, span = w["label"], {"start": w["start"], "end": w["end"], "cur": w["cur"]}
    o = _oee(r)

    # ---- 비교 (이번 교대 ↔ 어제 교대 · 오늘 ↔ 어제 하루 · 어제 교대 ↔ 그 전날)
    prev = None
    try:
        if kind in ("shift", "prev"):
            base = datetime.date.fromtimestamp(now) - datetime.timedelta(days=1 if kind == "shift" else 2)
            pw = _shift_window(base, now)
            if pw:
                prev = _oee(calc(pw[0], pw[2]))["oee"]
        elif kind == "today":
            m = analytics.window("today", now)["start"]
            prev = _oee(calc(m - 86400, m))["oee"]
    except Exception:
        prev = None

    # ---- 손실 폭포 (분) + 양품 개수 환산
    C = TARGET_CYCLE_SEC
    ideal = r["total"] * C
    speed = max(0.0, r["run"] - ideal)
    quality = r["defects"] * C
    stops = sum(r["loss"].values())
    good_time = min(r["run"], (r["total"] - r["defects"]) * C)
    lost_sec = max(0.0, r["elapsed"] - good_time)
    waterfall = {
        "planned": r["elapsed"], "good": good_time,
        "stops": [{"name": k, "sec": r["loss"][k], "count": r["count"][k], "goods": int(r["loss"][k] / C)} for k in CAUSES if r["loss"][k] > 0],
        "stop_sec": stops, "speed": speed, "quality": quality,
        "lost_goods": int(lost_sec / C), "lost_trucks": round(lost_sec / C / lot_good, 1),
    }

    # ---- 개선 기회: 그 손실이 없었다면 (나머지 비율은 그대로라고 가정)
    opps = []
    A, P, Q, O = o["availability"], o["performance"], o["quality"], o["oee"]
    if O is not None and r["elapsed"] > 0:
        for k in CAUSES:
            if r["loss"][k] > 0:
                A2 = min(1.0, (r["run"] + r["loss"][k]) / r["elapsed"])
                opps.append({"key": k, "title": f"{k} 줄이기" if k != "짧은 정지" else "짧은 정지(1분 미만) 없애기",
                             "detail": f"{r['count'][k]}회 · {round(r['loss'][k] / 60, 1)}분", "gain": A2 * P * Q - O,
                             "oee": A2 * P * Q, "link": LINK[k]})
        if P < 0.999:
            avg = r["run"] / r["total"] if r["total"] else None
            opps.append({"key": "속도", "title": f"속도 회복 ({avg:.1f}초 → {C:g}초)" if avg else "속도 회복",
                         "detail": f"속도 손실 {round(speed / 60, 1)}분", "gain": A * 1.0 * Q - O, "oee": A * Q, "link": LINK["속도"]})
        if Q < 0.999:
            opps.append({"key": "품질", "title": "불량 없애기", "detail": f"불량 {r['defects']}개 · 불량률 {(1 - Q) * 100:.1f}%",
                         "gain": A * P - O, "oee": A * P, "link": LINK["품질"]})
        opps = sorted([x for x in opps if x["gain"] > 0.0005], key=lambda x: -x["gain"])[:3]

    # ---- 설비별 가용률 · 병목 (컨베이어는 연동 정지 피해자라 제외)
    per_eq = [{"name": n, "availability": r["eq_run"][n] / r["elapsed"] if r["elapsed"] else None,
               "bad": r["eq_bad"][n], "linked": n == CONVEYOR} for n in EQUIPMENT]
    cand = [e for e in per_eq if not e["linked"] and e["availability"] is not None]
    worst = min(cand, key=lambda e: e["availability"], default=None)
    if worst and worst["availability"] > 0.995:
        worst = None

    # ---- 7일 추이 + 요일 × 시간 지도 (날마다 교대 시간)
    trend, heat, hours = [], [], []
    for d, (a, b, cur) in days:
        day = calc(a, cur)
        trend.append({"date": d.isoformat(), "dow": "월화수목금토일"[d.weekday()], "md": f"{d.month}/{d.day}",
                      "today": d == datetime.date.fromtimestamp(now), **_oee(day)})
        cells = []
        h = a
        conv = day["segs"][CONVEYOR]
        while h < b:
            he = min(h + 3600, b)
            if h >= cur:
                cells.append(None)
            else:
                e = min(he, cur)
                hi = [i for i in day["insp"] if h <= i["ts"] < e]
                cells.append(_oee_parts(_run(conv, h, e), e - h, len(hi), sum(i["result"] == "불량" for i in hi))[3]
                             if e - h > 300 else None)
            h = he
        heat.append({"label": "오늘" if d == datetime.date.fromtimestamp(now) else f"{'월화수목금토일'[d.weekday()]} {d.day}", "cells": cells})
    if days:
        a0 = days[-1][1][0]
        hours = [datetime.datetime.fromtimestamp(a0 + i * 3600).strftime("%H") for i in range(len(heat[-1]["cells"]))]
    # 가장 낮은 시간대 (지도 전체 평균)
    low = None
    if heat and hours:
        cols = []
        for j in range(len(hours)):
            vs = [row["cells"][j] for row in heat if j < len(row["cells"]) and row["cells"][j] is not None]
            if len(vs) >= 2:
                cols.append((sum(vs) / len(vs), hours[j]))
        if cols:
            v, hh = min(cols)
            low = {"hour": hh, "oee": v}
    tv = [t["oee"] for t in trend if t["oee"] is not None]

    return {
        "kind": kind, "label": label, "span": span, "now": now,
        "target": TARGET, "world": WORLD, "cycle": C, "lot_good": lot_good,
        **o, "prev": prev, "total": r["total"], "defects": r["defects"], "run": r["run"], "elapsed": r["elapsed"],
        "stop_sec": stops, "avg_cycle": r["run"] / r["total"] if r["total"] else None,
        "waterfall": waterfall, "opps": opps, "per_eq": per_eq, "worst": worst,
        "trend": trend, "trend_avg": sum(tv) / len(tv) if tv else None, "trend_hit": sum(v >= TARGET for v in tv),
        "heat": {"hours": hours, "rows": heat, "low": low},
        # 가정 시뮬레이터 기준 (교대 하루 길이로 환산)
        "sim": {"safety_sec": r["loss"]["안전 정지"], "shift_sec": (_at(datetime.date.today(), SHIFT_END) - _at(datetime.date.today(), SHIFT_START)) % 86400 or 86400},
    }
