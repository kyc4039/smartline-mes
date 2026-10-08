"""시연용 생산 시뮬레이터 — 품질 카메라가 없을 때 생산 기록을 대신 만든다

왜 필요한가
  생산 관리 · 관제 대시보드 생산 현황 · 디지털 트윈 출하장(팔레트·트럭)은 모두 DB 검사 기록(inspections)으로 계산한다.
  그런데 검사 기록은 품질 카메라가 캔을 판정할 때만 생기므로, 카메라가 없으면 세 화면이 모두 멈춘다.
동작
  - 품질 카메라가 켜져 있으면: 캔을 판정하는 동안(검사 중 · 정상 · 불량)만 쉬고,
    READY(대기)로 돌아오면 RESUME_SEC(3초) 뒤 다시 라인을 이어감 → NG 뒤에도 로봇 적재기 · 트럭이 계속 움직임 (10/07)
  - 품질 카메라가 없으면: 카메라 기록(source = camera)이 SILENT_SEC(2분) 넘게 없을 때 켜진다
  - 컨베이어가 '가동'일 때만 목표 사이클(TARGET_CYCLE_SEC, 기본 4초)마다 제품 1개를 기록한다
    → 프레스 안전 정지 → 컨베이어 연동 정지 동안은 기록하지 않아 생산량이 실제처럼 줄어든다
  - 불량은 DEMO_DEFECT_RATE(기본 3%) 확률, 불량 종류는 품질 모듈의 DEFECT_CLASSES 중 하나
  - 기록에는 source = 'sim' 표시 (OEE · 교대 보고서 · 생산 관리 계산에는 포함, 시스템 점검 페이지에서 한 번에 지울 수 있음)
검사기 정지 방식 (10/07 · FLOW_V2 = True일 때)
  - 상자가 비전 검사기에 들어오면 INSPECT_SEC(5초) 멈춰 검사 → 그 5초 동안 불량 기록(카메라 · 시연)이 없으면
    검사가 끝나는 순간 '정상'(또는 DEMO_DEFECT_RATE 확률로 불량) 1건 기록 → 기록 수 = 투입 수
  - 불량 기록이 그 5초 안에 오면 그 상자가 불량 → 시뮬레이터는 그 상자 몫을 기록하지 않음 (양품 1개 감소)
  - 시연 빨리감기(트럭 출발 · 팔레트 · 속도 ×3) 중에는 카메라 상태와 상관없이 같은 규칙으로 빠르게 기록 (source = demo)
설정 (config.py에 없으면 기본값)
  DEMO_PRODUCTION = True      # False면 시뮬레이터를 켜지 않음
  DEMO_DEFECT_RATE = 0.03
  DEMO_SILENT_SEC = 120       # 카메라가 없을 때: 마지막 카메라 기록 뒤 이만큼 지나면 이어받음
  DEMO_RESUME_SEC = 3         # 카메라가 켜져 있을 때: 판정이 끝나 READY가 된 뒤 이만큼 지나면 이어받음
"""
import random
import threading
import time
import config
import db
from analytics import TARGET_CYCLE_SEC

ENABLED = bool(getattr(config, "DEMO_PRODUCTION", True))
DEFECT_RATE = float(getattr(config, "DEMO_DEFECT_RATE", 0.03))
SILENT_SEC = float(getattr(config, "DEMO_SILENT_SEC", 120))   # 카메라 기록이 이만큼 없으면 시뮬레이터가 대신 기록
RESUME_SEC = float(getattr(config, "DEMO_RESUME_SEC", 3))     # 카메라가 READY로 돌아온 뒤 이만큼 지나면 이어감
BUSY = ("검사 중", "정상", "불량")                              # 품질 카메라가 캔을 판정 중인 상태
CONVEYOR = "컨베이어"
status = {"enabled": ENABLED, "active": False, "made": 0, "reason": "시작 전"}
_started = False
FLOW_V2 = bool(getattr(config, "FLOW_V2", True))
_forced = []                        # 시연 '불량 N연속': 다음 상자들의 판정 (불량 종류)
_flock = threading.Lock()


def force(types):
    """다음 상자들을 차례로 불량으로 판정 (시연)"""
    with _flock:
        _forced.extend(types)


def clear_force():
    with _flock:
        _forced.clear()


def _station_loop():
    """검사기 정지 방식: 검사기 안 상자의 5초 검사가 끝나는 순간마다 판정 1건 기록"""
    import line_flow
    types = _defect_types()
    last_busy = 0.0
    while True:
        try:
            ff = line_flow.ff_active()
            time.sleep(0.03 if ff else 0.1)
            now = time.time()
            with _flock:
                forced = bool(_forced)
            demo = ff or forced
            if not ENABLED and not demo:
                continue
            if not demo:
                wait, last_busy, why = _camera_busy(now, last_busy)
                if wait:
                    status.update(active=False, reason=why)
                    continue
            tau, due, rate, real = line_flow.next_due(now)
            if rate <= 0:
                status.update(active=False, reason="컨베이어 정지 → 검사기 상자도 멈춤")
                continue
            status.update(active=True, reason=f"검사기 {line_flow.INSPECT:g}초 검사 → {line_flow.CYCLE:g}초에 1개" +
                          (" (빨리감기)" if ff else ""))
            if real is None:
                continue
            last = db.latest_inspection()
            ts = max(now, (last["ts"] + 0.01) if last else now)                 # 지금 (순서는 지킴)
            with _flock:
                t = _forced.pop(0) if _forced else None
            bad = t is not None or random.random() < DEFECT_RATE
            if bad:
                t = t or random.choice(types)
                a, tp, c, d = getattr(config, "QUALITY_ROI", (0.25, 0.2, 0.75, 0.9))
                x, y = random.uniform(a, c - 0.08), random.uniform(tp, d - 0.08)
                box, conf = [x, y, x + 0.07, y + 0.06], round(random.uniform(0.55, 0.95), 2)
            else:
                box, conf = None, round(random.uniform(0.85, 0.97), 2)
            iid = db.add_inspection("불량" if bad else "정상", t if bad else "", source="demo" if demo else "sim",
                                    conf=conf, box=box, judge_sec=round(random.uniform(0.7, 1.3), 2),
                                    model="시연" if demo else "시뮬레이션", ts=ts)
            if bad and demo:
                db.log_event("quality", "불량 검출", defect_type=t, inspection=iid, demo=True)
            status["made"] += 1
        except Exception as e:
            print(f"[demo_sim] 오류: {e}")
            time.sleep(2)


def _defect_types():
    try:
        from modules.quality import DEFECT_CLASSES
        return sorted(DEFECT_CLASSES) or ["marked_can"]
    except Exception:
        return ["marked_can", "crushed_can"]


def _camera_busy(now, last_busy):
    """품질 카메라가 지금 캔을 판정 중인가 → (쉴지, 마지막으로 판정 중이던 시각)"""
    from state import state
    q = state.get("quality") or {}
    live = q.get("camera") and now - q.get("updated", 0) < 3          # 실제 카메라 영상이 들어오는 중
    if live:
        if q.get("status") in BUSY:
            return True, now, "품질 카메라가 판정 중 (실제 기록 사용)"
        if now - last_busy < RESUME_SEC:
            return True, last_busy, f"판정 끝 → {RESUME_SEC - (now - last_busy):.0f}초 뒤 라인 이어감"
        return False, last_busy, None
    last_cam = db.last_inspection_ts("camera")                         # 카메라가 없으면 예전 규칙
    if last_cam and now - last_cam < SILENT_SEC:
        return True, last_busy, "품질 카메라 기록 사용 중"
    return False, last_busy, None


def _loop():
    types = _defect_types()
    next_t = time.time() + TARGET_CYCLE_SEC
    last_busy = 0.0
    while True:
        time.sleep(0.25)
        try:
            now = time.time()
            wait, last_busy, why = _camera_busy(now, last_busy)
            if wait:
                status.update(active=False, reason=why)
                next_t = now + TARGET_CYCLE_SEC
                continue
            conv = next((e for e in db.get_equipment() if e["name"] == CONVEYOR), None)
            if conv and conv["status"] != "가동":
                status.update(active=False, reason=f"컨베이어 {conv['status']} → 생산 멈춤")
                next_t = now + TARGET_CYCLE_SEC          # 다시 가동되면 한 사이클 뒤부터
                continue
            status.update(active=True, reason=f"{TARGET_CYCLE_SEC:g}초마다 1개 기록 중" + (" (카메라 READY 동안)" if (__import__("state").state.get("quality") or {}).get("camera") else ""))
            if now >= next_t:
                bad = random.random() < DEFECT_RATE
                if bad:          # 결함 상자: 판정 구역(QUALITY_ROI) 안 아무 곳, 신뢰도 0.55~0.95
                    a, t, c, d = getattr(config, "QUALITY_ROI", (0.25, 0.2, 0.75, 0.9))
                    x, y = random.uniform(a, c - 0.08), random.uniform(t, d - 0.08)
                    box, conf = [x, y, x + 0.07, y + 0.06], round(random.uniform(0.55, 0.95), 2)
                else:
                    box, conf = None, round(random.uniform(0.85, 0.97), 2)
                db.add_inspection("불량" if bad else "정상", random.choice(types) if bad else "", source="sim",
                                  conf=conf, box=box, judge_sec=round(random.uniform(0.7, 1.3), 2), model="시뮬레이션")
                status["made"] += 1
                next_t += TARGET_CYCLE_SEC
                if now - next_t > TARGET_CYCLE_SEC:      # 오래 밀렸으면(절전 등) 몰아서 찍지 않음
                    next_t = now + TARGET_CYCLE_SEC
        except Exception as e:
            print(f"[demo_sim] 오류: {e}")
            time.sleep(2)


def start():
    global _started
    if _started:
        return
    _started = True
    if FLOW_V2:                     # 시연 빨리감기 · 불량 N연속은 DEMO_PRODUCTION = False여도 동작
        threading.Thread(target=_station_loop, daemon=True, name="demo_sim").start()
        if not ENABLED:
            status["reason"] = "꺼짐 (config.py DEMO_PRODUCTION = False) · 시연 버튼만 동작"
        return
    if not ENABLED:
        status["reason"] = "꺼짐 (config.py DEMO_PRODUCTION = False)"
        return
    threading.Thread(target=_loop, daemon=True, name="demo_sim").start()
