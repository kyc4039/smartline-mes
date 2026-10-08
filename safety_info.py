"""설비 안전 제어 페이지용 집계 · 정비 잠금(LOTO) · 교대 전 안전 점검

- info(): 오늘 안전 KPI · 시간대별 침입/경고 · 아차사고 기록 · 점검표 · 잠금 상태 (/api/safety/info)
- 정비 잠금: 정비하는 동안 프레스가 절대 켜지지 않게 잠금 (notes 테이블 'safety_lock'에 저장 → 서버를 다시 켜도 유지)
- 안전 점검: 교대 전 점검 항목 체크 (notes 'safety_check_YYYYMMDD')
설정 (config.py에 없으면 기본값)
  SAFETY_CHECKLIST = ["비상 정지 버튼 동작 확인", ...]   # 점검 항목
  SAFETY_SINCE = "2026-09-25"     # 무재해 시작일 (없으면 DB 첫 기록 날짜)
"""
import datetime
import json
import os
import time
import config
import db

PRESS = "프레스 #1"
SNAP_DIR = os.path.join(config.BASE, "safety_snaps")
CHECKLIST = list(getattr(config, "SAFETY_CHECKLIST", None) or [
    "비상 정지 버튼 동작 확인",
    "위험구역 카메라 시야 · 조명 확인",
    "손 넣기 시험 → 정지 확인",
    "금형 고정 볼트 점검",
])


def _midnight(ts):
    return datetime.datetime.combine(datetime.date.fromtimestamp(ts), datetime.time()).timestamp()


def _detail(e):
    try:
        return json.loads(e.get("detail") or "{}")
    except ValueError:
        return {}


# ---------------------------------------------------------------- 정비 잠금 (LOTO)
_lock_cache = {"t": 0, "v": None}


def get_lock(fresh=False):
    """{"who", "ts", "note"} 또는 None. 카메라 워커가 1초에 10번 부르므로 1초 동안 기억해 둠"""
    if fresh or time.time() - _lock_cache["t"] > 1:
        try:
            txt = db.get_note("safety_lock")
            _lock_cache["v"] = json.loads(txt) if txt else None
        except Exception:
            _lock_cache["v"] = None
        _lock_cache["t"] = time.time()
    return _lock_cache["v"]


def set_lock(who, note=""):
    v = {"who": who or "작업자", "ts": time.time(), "note": note}
    db.set_note("safety_lock", json.dumps(v, ensure_ascii=False))
    _lock_cache.update(t=time.time(), v=v)
    db.log_event("safety", "정비 잠금", who=v["who"], note=note)
    return v


def clear_lock(who=""):
    old = get_lock(fresh=True)
    db.set_note("safety_lock", "")
    _lock_cache.update(t=time.time(), v=None)
    if old:
        db.log_event("safety", "정비 잠금 해제", who=who or "관리자", locked_by=old.get("who"),
                     dur=round(time.time() - old.get("ts", time.time())))


# ---------------------------------------------------------------- 교대 전 안전 점검
def _check_key(now=None):
    return "safety_check_" + datetime.date.fromtimestamp(now or time.time()).strftime("%Y%m%d")


def checklist(now=None):
    try:
        done = json.loads(db.get_note(_check_key(now)) or "{}")
    except ValueError:
        done = {}
    return [{"i": i, "text": t, **(done.get(str(i)) or {})} for i, t in enumerate(CHECKLIST)]


def toggle_check(i, who=""):
    key = _check_key()
    try:
        done = json.loads(db.get_note(key) or "{}")
    except ValueError:
        done = {}
    k = str(int(i))
    if k in done:
        done.pop(k)
    else:
        done[k] = {"ts": time.time(), "who": who or "작업자"}
        db.log_event("safety", "안전 점검", item=CHECKLIST[int(i)] if int(i) < len(CHECKLIST) else k, who=who or "작업자")
    db.set_note(key, json.dumps(done, ensure_ascii=False))
    return checklist()


# ---------------------------------------------------------------- 스냅샷
def snap_path(name):
    p = os.path.join(SNAP_DIR, os.path.basename(name))
    return p if os.path.exists(p) else None


def save_snap(frame, kind):
    """정지·경고 순간 화면을 저장 → 파일 이름 (오래된 것부터 300장 넘으면 지움)"""
    try:
        import cv2
        os.makedirs(SNAP_DIR, exist_ok=True)
        name = f"{kind}_{int(time.time() * 1000)}.jpg"
        cv2.imwrite(os.path.join(SNAP_DIR, name), frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        files = sorted(os.listdir(SNAP_DIR))
        for f in files[:-300]:
            os.remove(os.path.join(SNAP_DIR, f))
        return name
    except Exception as e:
        print(f"[safety] 스냅샷 저장 실패: {e}")
        return ""


# ---------------------------------------------------------------- 집계
def _stops(a, b):
    """[a, b) 동안 프레스 '안전 정지' 구간 목록"""
    import analytics
    segs = analytics.segments({"start": a, "cur": b}).get(PRESS, [])
    return [s for s in segs if s["status"] == "안전 정지"]


def _kind(reason):
    r = reason or ""
    if "비상" in r:
        return "estop"
    if "정비 잠금" in r:
        return "lock"
    return "hit"


def _safe_days(now):
    since = getattr(config, "SAFETY_SINCE", None)
    try:
        d0 = datetime.date.fromisoformat(since) if since else None
    except ValueError:
        d0 = None
    if d0 is None:
        try:
            first = db.events_between(0, now + 1)[:1]
            d0 = datetime.date.fromtimestamp(first[0]["ts"]) if first else datetime.date.fromtimestamp(now)
        except Exception:
            d0 = datetime.date.fromtimestamp(now)
    return max(0, (datetime.date.fromtimestamp(now) - d0).days)


def info(now=None):
    import analytics
    from analytics import TARGET_CYCLE_SEC
    now = now or time.time()
    m = _midnight(now)
    stops = _stops(m, now)
    y_stops = _stops(m - 86400, m)
    evs = db.events_between(m, now + 1, "safety")
    warns = [e for e in evs if e["event"].startswith("경고구역 접근")]
    hits_ev = [e for e in evs if e["event"].startswith("위험구역 침입")]
    auto_n = sum(1 for e in evs if "자동 재가동" in e["event"])
    manual_n = sum(1 for e in evs if e["event"].startswith("수동 재가동"))
    real = [s for s in stops if _kind(s["reason"]) != "lock"]            # 정비 잠금은 '사고성 정지'에서 뺌
    down = sum(s["end"] - s["start"] for s in stops)
    closed = [s["end"] - s["start"] for s in real if not s.get("open")]

    # 시간대별 (교대 시간, 지금이 교대 밖이면 오늘 08시 ~ 지금)
    w = analytics.window("shift", now)
    h0 = datetime.datetime.fromtimestamp(min(w["start"], now)).replace(minute=0, second=0, microsecond=0).timestamp()
    h1 = max(w["end"], now)
    hours = []
    h = h0
    while h < h1 and len(hours) < 24:
        hours.append({"h": datetime.datetime.fromtimestamp(h).hour, "start": h, "future": h > now,
                      "stops": sum(1 for s in real if h <= s["start"] < h + 3600),
                      "warns": sum(1 for e in warns if h <= e["ts"] < h + 3600)})
        h += 3600
    peak = max(hours, key=lambda x: x["stops"] * 2 + x["warns"], default=None)

    # 아차사고 기록: 정지(침입 · 비상 정지 · 정비 잠금) + 경고구역 접근, 최신 순
    def snap_near(ts, pool):
        best = min(pool, key=lambda e: abs(e["ts"] - ts), default=None)
        return _detail(best).get("snap", "") if best and abs(best["ts"] - ts) < 3 else ""
    how_ev = [e for e in evs if "재가동" in e["event"]]
    rows = []
    for s in stops:
        k = _kind(s["reason"])
        nxt = next((e for e in how_ev if s["end"] - 2 <= e["ts"] <= s["end"] + 2), None)
        how = "" if s.get("open") else ("수동 재가동" if nxt and nxt["event"].startswith("수동") else "자동 재가동")
        d = _detail(next((e for e in hits_ev if abs(e["ts"] - s["start"]) < 3), {}))
        rows.append({"ts": s["start"], "kind": k, "dur": round(s["end"] - s["start"]), "open": bool(s.get("open")),
                     "cls": d.get("cls", ""), "conf": d.get("conf"), "how": how, "reason": s["reason"],
                     "snap": snap_near(s["start"], hits_ev) if k == "hit" else ""})
    for e in warns:
        d = _detail(e)
        rows.append({"ts": e["ts"], "kind": "warn", "cls": d.get("cls", ""), "conf": d.get("conf"),
                     "dur": d.get("dur"), "snap": d.get("snap", "")})
    rows.sort(key=lambda r: -r["ts"])

    last = max((s["start"] for s in real), default=None)
    return {
        "now": now,
        "kpi": {"stops": len(real), "stops_y": len([s for s in y_stops if _kind(s["reason"]) != "lock"]),
                "warns": len(warns), "down_sec": round(down), "loss": int(down / TARGET_CYCLE_SEC),
                "avg_restart": round(sum(closed) / len(closed)) if closed else None,
                "auto": auto_n, "manual": manual_n, "estops": sum(1 for s in stops if _kind(s["reason"]) == "estop"),
                "safe_days": _safe_days(now), "safe_goal": int(getattr(config, "SAFETY_GOAL_DAYS", 30)),
                "last_stop": last},
        "hours": hours,
        "peak": peak if peak and (peak["stops"] or peak["warns"]) else None,
        "rows": rows[:30],
        "lock": get_lock(fresh=True),
        "check": checklist(now),
    }
