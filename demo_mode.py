"""시연 모드 (10/07): 발표 때 버튼 하나로 보여 줄 상황을 만든다 (/demo 페이지 · 어느 페이지에서나 Shift+D 리모컨)

원칙
  - 카메라 이벤트(게이트 · 프레스 · 품질)는 '가짜 검출 상자'를 카메라 워커에 넣어서 진짜 판정 로직을 그대로 탄다
    → 안전 정지 · 연동 정지 · 5초 자동 재가동 · 스냅샷 · 사건 배너 · 검사 기록이 실제와 똑같이 생긴다
    → 카메라가 꺼져 있어도(NO CAMERA) 똑같이 시연 가능. 카메라가 켜져 있으면 실제 검출 + 가짜 검출을 함께 판정
  - 생산 · 정비 이벤트는 DB에 바로 기록 (source = 'demo', 정비 요청 글은 '[시연]'으로 시작) → '시연 기록 지우기'로 한 번에 삭제
  - 시연 모드를 끄거나 '모두 원래대로'를 누르면 진행 중인 이벤트를 모두 멈추고 설비를 가동으로 되돌린다
  - 비상 정지 · 정비 잠금은 다시 누르면 해제, 깜빡해도 HOLD_SEC(90초) 뒤 자동 해제
켜기: /demo 에서 관리자 PIN (config.py ADMIN_PIN)
"""
import collections
import random
import threading
import time
import config
import db
from state import state, workers

HOLD_SEC = 90                     # 비상 정지 · 정비 잠금 자동 해제 (시연용 안전장치)
LOCK_WHO = "시연 정비원"
TAG = "[시연]"

_lock = threading.RLock()
_on = False
_gen = 0                          # 모두 원래대로 → 숫자가 바뀌면 진행 중인 예약 작업은 스스로 멈춤
_inject = collections.defaultdict(list)   # key → [(t0, t1, make(frame) → dets)]
_last_inject = {}                 # key → 마지막 가짜 검출 시각 (품질 기록을 source='demo'로 남기기 위해)
_holds = {}                       # "estop" / "lock" → 해제 예정 시각
LOG = collections.deque(maxlen=40)
_started = False


# ---------------------------------------------------------------- 가짜 검출 상자
def _px(frame, r):
    h, w = frame.shape[:2]
    return [int(r[0] * w), int(r[1] * h), int(r[2] * w), int(r[3] * h)]


def _box_center(frame, roi, fw, fh):
    """판정 구역 roi(비율)의 가운데에 폭 fw · 높이 fh(비율) 상자"""
    cx, cy = (roi[0] + roi[2]) / 2, (roi[1] + roi[3]) / 2
    return tuple(_px(frame, (cx - fw / 2, cy - fh / 2, cx + fw / 2, cy + fh / 2)))


def _det(cls, box, conf=None):
    return {"cls": cls, "conf": conf or round(random.uniform(0.86, 0.95), 2), "box": box, "demo": True}


def _gate_sec():
    return float(getattr(config, "GATE_HOLD_SEC", 1.0))


def _safety_hit(cls):
    def make(frame):
        return [_det(cls, _box_center(frame, config.SAFETY_ROI, 0.08, 0.12))]
    return make


def _safety_warn(cls):
    def make(frame):
        from modules.safety import WARN_ROI
        a, w = config.SAFETY_ROI, WARN_ROI
        gap = max(0.01, a[0] - w[0])                          # 경고구역 왼쪽 띠 (위험구역과 안 겹치게)
        x = w[0] + gap * 0.5
        bw = min(0.06, gap * 0.7)
        cy = (a[1] + a[3]) / 2
        return [_det(cls, tuple(_px(frame, (x - bw / 2, cy - 0.06, x + bw / 2, cy + 0.06))))]
    return make


def _gate(items):
    def make(frame):
        boxes = {"helmet": (0.42, 0.08, 0.58, 0.24), "vest": (0.36, 0.30, 0.64, 0.62), "gloves": (0.30, 0.60, 0.40, 0.72)}
        return [_det(k, tuple(_px(frame, boxes[k]))) for k in items]
    return make


def _quality(defect=None):
    def make(frame):
        from modules.quality import PRODUCT_CLASS
        r = config.QUALITY_ROI
        out = [_det(PRODUCT_CLASS, _box_center(frame, r, 0.18, 0.40))]
        if defect:
            cx, cy = (r[0] + r[2]) / 2 + 0.03, (r[1] + r[3]) / 2 - 0.06
            out.append(_det(defect, tuple(_px(frame, (cx - 0.04, cy - 0.04, cx + 0.04, cy + 0.04)))))
        return out
    return make


def inject(key, delay, dur, make):
    t0 = time.time() + delay
    with _lock:
        _inject[key].append((t0, t0 + dur, make))


def dets(key, frame):
    """카메라 워커가 매 프레임 부름 → 지금 넣을 가짜 검출 목록.
    예약된 시연이 없으면 None, 있지만 지금은 빈 구간이면 [] (화면에 시연 표시는 계속)"""
    if not _on:
        return None
    now = time.time()
    with _lock:
        items = [x for x in _inject.get(key, []) if x[1] + 3 > now]    # 끝나고 3초까지는 '시연 중'으로 봄
        _inject[key] = items
        if not items:
            return None
        cur = [d for t0, t1, mk in items if t0 <= now <= t1 for d in mk(frame)]
    if cur:
        _last_inject[key] = now
    return cur


def engaged(key):
    """이 카메라에 예약된 시연이 있나 (부작용 없음 · 점검 페이지용)"""
    now = time.time()
    return _on and any(x[1] + 3 > now for x in _inject.get(key, []))


def active(key, within=6.0):
    """방금 가짜 검출이 있었나 (품질 기록을 시연 기록으로 남길 때)"""
    return _on and time.time() - _last_inject.get(key, 0) < within


# ---------------------------------------------------------------- 공통 도우미
def _log(text, lv="b"):
    LOG.appendleft({"ts": time.time(), "text": text, "lv": lv})


def _later(delay, fn):
    """delay초 뒤 fn() — 그 사이에 '모두 원래대로'를 누르면 실행 안 함"""
    g = _gen

    def run():
        if g == _gen and _on:
            try:
                fn()
            except Exception as e:
                _log(f"오류: {e}", "r")
    t = threading.Timer(delay, run)
    t.daemon = True
    t.start()


def _add_inspections(n, gap, defect_rate=0.0, types=None):
    """검사 기록 n개를 gap초 간격으로 (source='demo')"""
    g = _gen

    def run():
        for i in range(n):
            if g != _gen or not _on:
                return
            bad = (types and i < len(types)) or random.random() < defect_rate
            t = (types[i] if types and i < len(types) else random.choice(_defect_types())) if bad else ""
            iid = db.add_inspection("불량" if bad else "정상", t, source="demo", conf=round(random.uniform(0.8, 0.96), 3),
                                    model="시연")
            if bad:
                db.log_event("quality", "불량 검출", defect_type=t, inspection=iid, demo=True)
            time.sleep(gap)
    threading.Thread(target=run, daemon=True).start()


def _defect_types():
    try:
        from modules.quality import DEFECT_CLASSES
        return sorted(DEFECT_CLASSES)
    except Exception:
        return ["marked_can", "crushed_can"]


def _classify(equipment, text, force_stop):
    """정비 요청: AI 분류 → 티켓 (처음엔 분류기를 불러오느라 수십 초 걸릴 수 있어 백그라운드)"""
    g = _gen
    if force_stop:
        db.set_equipment(equipment, "고장 정지", reason=f"{TAG} {text[:20]}")

    def run():
        from modules import maintenance
        try:
            r = maintenance.get_classifier()(text)
        except Exception as e:
            r = {"type": "기계 고장", "urgency": "상", "need_review": False, "error": str(e)}
        if g != _gen:
            return
        tid = db.create_ticket(equipment, f"{TAG} {text}", r)
        db.log_event("maintenance", "정비 요청 접수", ticket=tid, equipment=equipment, type=r.get("type"),
                     urgency=r.get("urgency"), demo=True)
        if r.get("urgency") == "상" and equipment:
            db.set_equipment(equipment, "고장 정지", reason=f"정비 요청 #{tid}")
        _log(f"AI 분류 #{tid} {equipment} → {r.get('type_name') or r.get('type')} · {r.get('urgency_name') or r.get('urgency')}", "b")
    threading.Thread(target=run, daemon=True).start()


def _estop(on):
    w = workers.get("safety")
    if on:
        if w:
            w.estop = True
            w.latched, w.last_hit, w.reason = True, time.time(), "비상 정지 버튼"
        db.set_equipment("프레스 #1", "안전 정지", reason="비상 정지 버튼")
        db.log_event("safety", "비상 정지 버튼", who="시연", demo=True)
        _holds["estop"] = time.time() + HOLD_SEC
    else:
        if w:
            w.estop, w.latched = False, False
        db.set_equipment("프레스 #1", "가동", reason="수동 재가동")
        db.log_event("safety", "수동 재가동", who="시연", demo=True)
        _holds.pop("estop", None)


def _loto(on):
    import safety_info
    if on:
        safety_info.set_lock(LOCK_WHO, "시연")
        db.set_equipment("프레스 #1", "안전 정지", reason="정비 잠금")
        _holds["lock"] = time.time() + HOLD_SEC
    else:
        safety_info.clear_lock(LOCK_WHO)
        w = workers.get("safety")
        if w:
            w.last_hit = time.time() - 60     # 잠금만 풀면 바로 재가동 (시연)
        _holds.pop("lock", None)


def is_on(eid):
    if eid == "estop":
        w = workers.get("safety")
        return bool(w and getattr(w, "estop", False)) or "estop" in _holds
    if eid == "lock":
        import safety_info
        return bool(safety_info.get_lock())
    return False


def _maint_done():
    n = 0
    with db._lock, db._conn() as c:
        rows = [dict(r) for r in c.execute("SELECT id, equipment, text, started FROM tickets WHERE status != '완료' AND text LIKE ?",
                                            (TAG + "%",))]
    for t in rows:
        if True:
            if not t.get("started"):
                db.start_ticket(t["id"], LOCK_WHO)
            db.complete_ticket(t["id"], "시연 조치 완료")
            db.log_event("maintenance", "정비 완료", ticket=t["id"], equipment=t["equipment"], demo=True)
            n += 1
    for e in db.get_equipment():
        if e["status"] == "고장 정지":
            db.set_equipment(e["name"], "가동", reason="정비 완료 (시연)")
    return n


FLOW_V2 = bool(getattr(config, "FLOW_V2", True))


def _ff(**kw):
    """검사기 정지 방식: 라인 시계 빨리감기 → 시뮬레이터가 검사 5초마다 판정을 기록 (불량은 평소 확률대로 → 양품이 줄어듦)"""
    import line_flow
    line_flow.fast_forward(**kw)
    return line_flow.flow()["counts"]


def _truck():
    if FLOW_V2:
        # 라인 시계를 ×8로 빨리감기 → 남은 팔레트를 실제로 채우고 출발 (끝나면 자동으로 ×1)
        import line_flow
        c = line_flow.flow()["counts"]
        seq = c["lot_seq"]
        line_flow.fast_forward(8, until_lot=seq, max_sec=240)
        return max(0, seq * line_flow.LOT - c["good_db"])
    import production
    s = production.summary()
    need = max(1, s["truck_pallets"] * s["pallet_size"] - s["current"]["good"])
    _add_inspections(need, 0.06)
    return need


def _more(n):
    """검사 기록 n개가 더 생길 때까지 ×8 빨리감기"""
    import line_flow
    with line_flow._lock:
        have = len(line_flow._build(time.time())["prods"])
    return _ff(k=8, until_count=have + n, max_sec=30)


def _pallet():
    """지금 팔레트가 다 찰 때까지 ×8 빨리감기"""
    import line_flow
    c = line_flow.flow()["counts"]
    return _ff(k=8, until_placed=c["placed"] - c["fill"] + line_flow.PALLET, max_sec=60)


# ---------------------------------------------------------------- 이벤트 목록
#  id: (그룹, 이름, 설명, 색 r/y/g/b, 실행 함수, 다시 누르면 해제?)
def _ev():
    v2 = FLOW_V2
    return {
        "gate_ok":      ("gate", "보호구 3종 착용 → 입장", "게이트 화면(미리보기)에서 3종 확인 → 입장 완료", "g",
                         lambda: inject("gate", 0, _gate_sec() + 3, _gate(["helmet", "vest", "gloves"])), False),
        "gate_nohelmet": ("gate", "안전모 미착용", "입장 거부 · '안전모가 안 보여요'", "y",
                          lambda: inject("gate", 0, 6, _gate(["vest", "gloves"])), False),
        "gate_novest":  ("gate", "조끼 미착용", "2/3 확인 · 부족한 보호구 깜빡임", "y",
                         lambda: inject("gate", 0, 6, _gate(["helmet", "gloves"])), False),
        "warn_tool":    ("safety", "경고구역 접근 · 드라이버", "전체 화면 노란 경고 · 정지 안 함", "y",
                         lambda: inject("safety", 0, 4, _safety_warn("screwdriver")), False),
        "hit_hand":     ("safety", "위험구역 침입 · 손", "안전 정지 → 컨베이어 연동 정지 · 5초 비면 재가동", "r",
                         lambda: inject("safety", 0, 2.5, _safety_hit("hand")), False),
        "hit_spanner":  ("safety", "위험구역 침입 · 스패너", "공구도 똑같이 정지", "r",
                         lambda: inject("safety", 0, 2.5, _safety_hit("spanner")), False),
        "estop":        ("safety", "비상 정지", "자동 재가동 안 됨 · 다시 누르면 수동 재가동", "r",
                         lambda: _estop(not is_on("estop")), True),
        "lock":         ("safety", "정비 잠금 (LOTO)", "정비 중 프레스 켜지지 않음 · 다시 누르면 해제", "b",
                         lambda: _loto(not is_on("lock")), True),
        "defect_marked": ("quality", "불량 · 표면 흠집", "marked_can · 불량함으로 배출", "r",
                          lambda: inject("quality", 0, 1.6, _quality("marked_can")), False),
        "defect_crushed": ("quality", "불량 · 찌그러짐", "crushed_can · 불량함으로 배출", "r",
                           lambda: inject("quality", 0, 1.6, _quality("crushed_can")), False),
        "defect_6":     ("quality", "불량 6연속", "다음 상자 6개가 검사기에서 차례로 불량 → 관리 한계 이탈" if v2 else "최근 50개 불량률 → 관리 한계 이탈", "y",
                         (lambda: __import__("demo_sim").force(["crushed_can", "marked_can"] * 3)) if v2 else
                         (lambda: _add_inspections(6, 0.8, types=["crushed_can", "marked_can"] * 3)), False),
        "good_can":     ("quality", "정상 캔 1개 (카메라)", "판정 구역에 캔 → OK 판정", "g",
                         lambda: inject("quality", 0, 1.6, _quality()), False),
        "good_10":      ("quality", "검사 10개 빨리감기" if v2 else "정상 캔 10개", "라인 ×8 → 상자 10개 검사" if v2 else "검사 기록 빠르게 쌓기", "g",
                         (lambda: _more(10)) if v2 else
                         (lambda: _add_inspections(10, 0.4)), False),
        "conveyor_fault": ("maint", "컨베이어 고장 정지", "사건 배너 · AI 정비 요청 자동 생성", "r",
                           lambda: _classify("컨베이어", "컨베이어 벨트가 끊어져서 라인이 멈췄어요", True), False),
        "robot_fault":  ("maint", "로봇 적재기 고장", "적재 멈춤 · 트윈 로봇 빨간 램프", "r",
                         lambda: _classify("로봇 적재기", "로봇 그리퍼가 캔을 못 잡고 떨어뜨려요", True), False),
        "report_ai":    ("maint", "작업자 신고 → AI 분류", "'프레스에서 기름이 새요' → 위험도 판정", "b",
                         lambda: _classify("프레스 #1", "프레스 바닥에 기름이 새서 고였어요", False), False),
        "maint_done":   ("maint", "정비 완료", "시연 정비 요청 완료 · 설비 재가동", "g", _maint_done, False),
        "pallet":       ("prod", "팔레트 1개 채우기", "지금 팔레트가 찰 때까지 라인 ×8" if v2 else "양품 +8 · 로봇 적재 빨리감기", "b",
                         (lambda: _pallet()) if v2 else (lambda: _add_inspections(8, 0.5)), False),
        "truck":        ("prod", "트럭 출발", "빨리감기 ×8 → 남은 팔레트를 채움 → 지게차 → 출발", "b", _truck, False),
        "speed3":       ("prod", "생산 속도 ×3 (1분)", "라인 전체 ×3 빨리감기 1분" if v2 else "숫자가 빠르게 바뀌는 모습", "b",
                         (lambda: _ff(k=3, max_sec=60)) if v2 else
                         (lambda: _add_inspections(45, 1.33, defect_rate=0.03)), False),
    }


EVENTS = _ev()
GROUPS = [("gate", "🛡 안전 게이트", "팀원1"), ("safety", "⚠ 프레스 안전", "팀원3"), ("quality", "🔍 품질 검사", "팀원2"),
          ("maint", "🔧 설비 보전", "팀원4"), ("prod", "🚚 생산 · 출하", "")]


def trigger(eid):
    if not _on:
        return False, "시연 모드가 꺼져 있어요"
    ev = EVENTS.get(eid)
    if not ev:
        return False, "없는 이벤트"
    was = is_on(eid)
    out = ev[4]()
    name = ev[1] + (" 해제" if ev[5] and was else "")
    if eid == "truck":
        name += f" (남은 양품 {out}개)"
    _log(name, ev[3] if not (ev[5] and was) else "g")
    return True, name


# ---------------------------------------------------------------- 발표 시나리오
#  (제목, 볼 화면, 걸리는 초, [(몇 초 뒤, 이벤트)])
SCENARIO = [
    ("보호구 착용 → 게이트 입장", "/gate?preview=1", 15, [(1, "gate_ok")]),
    ("정상 생산 · 캔 검사", "/", 25, [(0, "good_can"), (5, "good_can"), (9, "pallet")]),
    ("공구 경고 → 손 침입 → 자동 재가동", "/twin", 25, [(0, "warn_tool"), (6, "hit_hand")]),
    ("찌그러진 캔 불량 → 배출", "/quality", 15, [(0, "defect_crushed")]),
    ("불량 연속 → 관리 한계 이탈", "/quality", 20, [(0, "defect_6")]),
    ("컨베이어 고장 → AI 정비 요청", "/maintenance", 30, [(0, "conveyor_fault")]),
    ("정비 완료 → 트럭 출발", "/twin", 30, [(0, "maint_done"), (3, "truck")]),
    ("OEE 변화 확인 · 마무리", "/oee", 15, []),
]
SC = {"idx": -1, "running": False, "t": 0.0, "pe": 0.0}


def _run_step(i):
    SC["idx"], SC["t"], SC["pe"] = i, time.time(), 0.0
    title, page, dur, acts = SCENARIO[i]
    _log(f"시나리오 {i + 1}/{len(SCENARIO)} · {title}", "b")
    for d, eid in acts:
        if d == 0:
            trigger(eid)
        else:
            _later(d, lambda e=eid: trigger(e))


def scenario(cmd, i=None):
    if not _on:
        return False
    with _lock:
        if cmd == "goto" and i is not None and 0 <= int(i) < len(SCENARIO):
            SC["running"] = True
            _run_step(int(i))
        elif cmd == "start":
            SC["running"] = True
            _run_step(0)
        elif cmd == "next":
            if SC["idx"] + 1 < len(SCENARIO):
                SC["running"] = SC["running"] or SC["idx"] < 0
                _run_step(SC["idx"] + 1)
            else:
                SC.update(idx=-1, running=False)
        elif cmd == "pause":
            SC["running"], SC["pe"] = False, time.time() - SC["t"]
        elif cmd == "play":
            SC["running"] = True
            if SC["idx"] < 0:
                _run_step(0)
        elif cmd == "stop":
            SC.update(idx=-1, running=False)
    return True


# ---------------------------------------------------------------- 켜기 · 끄기 · 원래대로
def set_on(on):
    global _on
    if on and not _on:
        _on = True
        _log("시연 모드 켜짐", "y")
        db.log_event("demo", "시연 모드 켜짐")
    elif not on and _on:
        reset(quiet=True)
        _on = False
        _log("시연 모드 꺼짐", "y")
        db.log_event("demo", "시연 모드 꺼짐")
    _publish()


def reset(quiet=False):
    """진행 중인 시연을 모두 멈추고 설비를 가동으로"""
    global _gen
    with _lock:
        _gen += 1
        _inject.clear()
        SC.update(idx=-1, running=False)
    w = workers.get("safety")
    if w:
        w.estop, w.latched = False, False
        w.last_hit = time.time() - 60
    try:
        import safety_info
        lk = safety_info.get_lock()
        if lk and lk.get("who") == LOCK_WHO:
            safety_info.clear_lock(LOCK_WHO)
    except Exception:
        pass
    _holds.clear()
    try:
        import line_flow
        line_flow.ff_stop()
        __import__("demo_sim").clear_force()
    except Exception:
        pass
    for e in db.get_equipment():          # 컨베이어 '연동 정지'는 연동 규칙이 알아서 풂
        if e["status"] != "가동" and not (e["name"] == "컨베이어" and e["status"] == "연동 정지"):
            db.set_equipment(e["name"], "가동", reason="시연 원래대로")
    if not quiet:
        _log("모두 원래대로", "y")


def clear_records():
    """시연 기록 지우기: 검사 기록(source='demo') · 시연 이벤트 · [시연] 정비 요청"""
    with db._lock, db._conn() as c:
        a = c.execute("DELETE FROM inspections WHERE source = 'demo'").rowcount
        b = c.execute("DELETE FROM events WHERE detail LIKE '%\"demo\": true%'").rowcount
        t = c.execute("DELETE FROM tickets WHERE text LIKE ?", (TAG + "%",)).rowcount
    _log(f"시연 기록 지움 · 검사 {a} · 이벤트 {b} · 정비 요청 {t}", "y")
    return {"inspections": a, "events": b, "tickets": t}


def demo_count():
    try:
        return db.count_inspections("demo")
    except Exception:
        return 0


def status():
    i = SC["idx"]
    now = time.time()
    step = None
    if 0 <= i < len(SCENARIO):
        title, page, dur, _ = SCENARIO[i]
        step = {"i": i, "title": title, "page": page, "dur": dur, "elapsed": round(now - SC["t"], 1),
                "next": SCENARIO[i + 1][0] if i + 1 < len(SCENARIO) else None,
                "next_page": SCENARIO[i + 1][1] if i + 1 < len(SCENARIO) else None}
    total = sum(s[2] for s in SCENARIO)
    done = sum(s[2] for s in SCENARIO[:i]) + (min(step["elapsed"], step["dur"]) if step else 0) if i >= 0 else 0
    return {"on": _on, "running": SC["running"], "step": step, "steps": [{"title": s[0], "page": s[1], "dur": s[2]} for s in SCENARIO],
            "total": total, "done": round(done, 1), "toggles": {k: is_on(k) for k in ("estop", "lock")},
            "log": list(LOG)[:20], "count": demo_count()}


def _publish():
    i = SC["idx"]
    state.update("demo", on=_on, running=SC["running"], idx=i, n=len(SCENARIO),
                 title=SCENARIO[i][0] if 0 <= i < len(SCENARIO) else "",
                 page=SCENARIO[i][1] if 0 <= i < len(SCENARIO) else "",
                 next=SCENARIO[i + 1][0] if 0 <= i + 1 < len(SCENARIO) and i >= 0 else (SCENARIO[0][0] if i < 0 else ""),
                 next_page=SCENARIO[i + 1][1] if 0 <= i + 1 < len(SCENARIO) and i >= 0 else (SCENARIO[0][1] if i < 0 else ""))


def _loop():
    while True:
        try:
            now = time.time()
            if _on:
                if SC["running"] and SC["idx"] >= 0:
                    dur = SCENARIO[SC["idx"]][2]
                    if now - SC["t"] >= dur:
                        if SC["idx"] + 1 < len(SCENARIO):
                            _run_step(SC["idx"] + 1)
                        else:
                            SC.update(idx=-1, running=False)
                            _log("시나리오 끝", "g")
                elif not SC["running"] and SC["idx"] >= 0:
                    SC["t"] = now - SC.get("pe", now - SC["t"])   # 일시정지 중에는 단계 시간이 흐르지 않게
                for k, until in list(_holds.items()):       # 깜빡한 비상 정지 · 정비 잠금 자동 해제
                    if now >= until:
                        (_estop if k == "estop" else _loto)(False)
                        _log(f"{'비상 정지' if k == 'estop' else '정비 잠금'} 자동 해제 ({HOLD_SEC}초)", "g")
            _publish()
        except Exception as e:
            print(f"[demo] 오류: {e}")
        time.sleep(0.3)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="demo").start()
