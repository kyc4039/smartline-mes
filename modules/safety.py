"""[팀원3] 프레스 안전 인터록: 위험구역(ROI)에 손·공구(드라이버·볼드라이버·스패너)가 들어오면 안전 정지
수정할 곳: DANGER_CLASSES (위험 대상 클래스 이름 → 화면 이름), judge()
안전 정지는 '잠김' 상태가 되고, 위험구역에서 SAFETY_AUTO_RELEASE_SEC(기본 5초) 동안
위험 대상이 안 보이면 자동 재가동한다. 손이 다시 보이면 5초를 처음부터 다시 센다.
그 동안 모든 화면에 '기계에서 떨어지세요' 경고가 뜬다 (static/app.js의 dangerAlert).

2단계 구역 (10/07 추가)
  - 위험구역(SAFETY_ROI, 빨강): 들어오면 즉시 안전 정지 → 모든 화면 빨간 경고
  - 경고구역(위험구역 바깥 테두리, 노랑): 들어오면 정지하지 않고 알림만 → 모든 화면 노란 경고
    크기: SAFETY_WARN_ROI = (왼, 위, 오른, 아래) 를 직접 쓰거나, SAFETY_WARN_MARGIN(기본 0.08)만큼 위험구역을 넓힘
재가동을 막는 조건 (10/07 추가)
  - 비상 정지 버튼: 손이 없어도 자동 재가동하지 않음 → 관리자 PIN으로 '수동 재가동'
  - 정비 잠금(LOTO): 정비하는 동안 프레스가 켜지지 않음 → 잠금 해제(PIN) 뒤 5초 비면 재가동
정지·경고 순간 화면은 safety_snaps/ 폴더에 저장 (아차사고 기록)
"""
import time
import cv2
from flask import Blueprint, render_template, jsonify, request, send_file, abort
import config
import db
import safety_info
from camera_worker import CameraWorker
from config import SAFETY_ROI, SAFETY_AUTO_RELEASE_SEC

# 수신호 재가동을 없앴으므로 자동 재가동은 항상 켜 둔다 (config에서 None이면 5초)
AUTO_SEC = float(SAFETY_AUTO_RELEASE_SEC or 5.0)
from streaming import mjpeg
from state import state, workers

# 팀원3: 위험 대상 클래스 이름(모델) → 화면에 보일 이름. 대소문자는 무시함 (Hand = hand)
DANGER_CLASSES = {"hand": "손", "screwdriver": "드라이버", "balldriver": "볼드라이버", "spanner": "스패너"}


def _cls(name):
    return str(name).strip().lower()


def _kr(name):
    return DANGER_CLASSES.get(_cls(name), str(name))


def _warn_roi():
    r = getattr(config, "SAFETY_WARN_ROI", None)
    if r:
        return tuple(r)
    m = float(getattr(config, "SAFETY_WARN_MARGIN", 0.08))
    a, b, c, d = SAFETY_ROI
    return max(0.0, a - m), max(0.0, b - m), min(1.0, c + m), min(1.0, d + m)


WARN_ROI = _warn_roi()
WARN_COOLDOWN = 3.0      # 경고구역 접근 기록 간격 (같은 접근을 여러 번 세지 않게)


def _overlap(box, roi):
    x1, y1, x2, y2 = box
    rx1, ry1, rx2, ry2 = roi
    return x1 < rx2 and x2 > rx1 and y1 < ry2 and y2 > ry1


class Worker(CameraWorker):
    def expected_classes(self):
        have = {_cls(c): c for c in getattr(self, "model_classes", [])}     # 시스템 점검: 모델 쪽 철자로 표시
        return [have.get(k, k) for k in DANGER_CLASSES]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.latched = False      # 안전 정지 잠김
        self.last_hit = 0.0       # 위험구역에서 마지막으로 위험 대상을 본 시각
        self.estop = False        # 비상 정지 버튼 (수동 재가동 전까지 유지)
        self.warn_on, self.warn_since, self.warn_last = False, 0.0, 0.0
        self.snap = None          # 다음 draw()에서 저장할 스냅샷 [종류, 이벤트, 상세]
        self.stop_since = None

    def _px(self, frame, r):
        h, w = frame.shape[:2]
        a, b, c, d = r
        return int(a * w), int(b * h), int(c * w), int(d * h)

    def _roi_px(self, frame):
        return self._px(frame, SAFETY_ROI)

    def judge(self, frame, dets):
        roi, wroi = self._roi_px(frame), self._px(frame, WARN_ROI)
        danger = [d for d in dets if _cls(d["cls"]) in DANGER_CLASSES]
        hits = [d for d in danger if _overlap(d["box"], roi)]
        near = [d for d in danger if d not in hits and _overlap(d["box"], wroi)]
        now = time.time()
        lock = safety_info.get_lock()
        if hits:
            if not self.latched:                     # 새로 침입 → 아차사고 기록 + 스냅샷
                b = max(hits, key=lambda d: d["conf"])
                self.snap = ["hit", f"위험구역 {_kr(b['cls'])} 침입 → 안전 정지", {"cls": b["cls"], "conf": round(b["conf"], 2)}]
            self.latched = True
            self.last_hit = now
            self.reason = ", ".join(sorted({_kr(d["cls"]) for d in hits}))
        if self.estop and not self.latched:
            self.latched, self.reason = True, "비상 정지 버튼"
        if lock and not self.latched:                # 가동 중에 정비 잠금 → 바로 정지
            self.latched, self.reason, self.last_hit = True, "정비 잠금", now
        hold = "estop" if self.estop else "lock" if lock else None
        clear_sec = now - self.last_hit if self.latched and not hits else 0.0

        # 자동 재가동: 위험구역이 정해진 시간 동안 계속 비어 있으면 잠김 해제 (비상 정지 · 정비 잠금 중에는 안 함)
        if self.latched and not hold and clear_sec >= AUTO_SEC:
            self.latched = False
            db.log_event("safety", f"위험구역 {AUTO_SEC:.0f}초 비어 있음 → 자동 재가동")

        # 경고구역 접근 (가동 중일 때만): 들어온 순간 한 번 기록
        warn = bool(near) and not self.latched
        if warn and not self.warn_on:
            self.warn_since = now
            if now - self.warn_last > WARN_COOLDOWN:
                b = max(near, key=lambda d: d["conf"])
                self.snap = ["warn", f"경고구역 {_kr(b['cls'])} 접근", {"cls": b["cls"], "conf": round(b["conf"], 2)}]
        if warn:
            self.warn_last = now
        self.warn_on = warn

        best = max(hits or near, key=lambda d: d["conf"], default=None)
        remaining = max(0.0, AUTO_SEC - clear_sec) if self.latched and not hold else None
        return {"status": "안전 정지" if self.latched else "가동", "zone_clear": not hits,
                "reason": getattr(self, "reason", "") if self.latched else "",
                "clear_seconds": round(clear_sec, 1), "auto_release_sec": AUTO_SEC,
                "auto_release_in": None if remaining is None or hits else round(remaining, 1),
                "warn": warn, "warn_sec": round(now - self.warn_since, 1) if warn else 0,
                "hold": hold, "estop": self.estop,
                "lock_by": (lock or {}).get("who", ""), "lock_ts": (lock or {}).get("ts"),
                "det": {"cls": best["cls"], "name": _kr(best["cls"]), "conf": round(best["conf"], 2),
                        "zone": "danger" if best in hits else "warn"} if best else None,
                "stop_since": self.stop_since if self.latched else None}

    def draw(self, frame, dets, result):
        x1, y1, x2, y2 = self._px(frame, WARN_ROI)                       # 경고구역 (노랑)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (68, 181, 245), 1)
        x1, y1, x2, y2 = self._roi_px(frame)                              # 위험구역
        color = (0, 0, 255) if result["status"] == "안전 정지" else (0, 200, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, "STOP" if result["status"] == "안전 정지" else "RUN", (x1 + 5, y1 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        frame = super().draw(frame, dets, result)
        if self.snap:                                                     # 정지 · 경고 순간 화면 저장
            kind, ev, d = self.snap
            self.snap = None
            db.log_event("safety", ev, snap=safety_info.save_snap(frame, kind), **d)
        return frame

    def on_change(self, old, new, result):
        self.stop_since = time.time() if new == "안전 정지" else None
        db.set_equipment("프레스 #1", "안전 정지" if new == "안전 정지" else "가동",
                         reason=result.get("reason", ""))


bp = Blueprint("safety", __name__)


@bp.route("/safety")
def page():
    return render_template("safety.html", auto_sec=AUTO_SEC, roi=SAFETY_ROI, warn_roi=WARN_ROI)


@bp.route("/safety/video")
def video():
    return mjpeg("safety")


@bp.route("/api/safety")
def api():
    return jsonify({"safety": state.get("safety")})


@bp.route("/api/safety/info")
def api_info():
    return jsonify(safety_info.info())


@bp.route("/safety/snap/<name>")
def snap(name):
    p = safety_info.snap_path(name)
    if not p:
        abort(404)
    return send_file(p, mimetype="image/jpeg")


def _body():
    return request.get_json(silent=True) or {}


def _pin_ok():
    return str(_body().get("pin", "")) == str(getattr(config, "ADMIN_PIN", "0000"))


@bp.route("/api/safety/estop", methods=["POST"])
def api_estop():
    """화면의 비상 정지 버튼: 프레스를 즉시 안전 정지 (관리자가 수동 재가동할 때까지 유지)"""
    w = workers.get("safety")
    if w:
        w.estop = True
        w.latched, w.last_hit, w.reason = True, time.time(), "비상 정지 버튼"
    db.set_equipment("프레스 #1", "안전 정지", reason="비상 정지 버튼")
    db.log_event("safety", "비상 정지 버튼", who=_body().get("who", ""))
    return jsonify({"ok": True})


@bp.route("/api/safety/restart", methods=["POST"])
def api_restart():
    """수동 재가동 (관리자 PIN): 위험구역이 비어 있고 정비 잠금이 없을 때만"""
    if not _pin_ok():
        return jsonify({"ok": False, "msg": "PIN이 맞지 않아요"}), 403
    if safety_info.get_lock(fresh=True):
        return jsonify({"ok": False, "msg": "정비 잠금 중이에요. 잠금을 먼저 해제하세요"}), 409
    s = state.get("safety") or {}
    if s.get("zone_clear") is False:
        return jsonify({"ok": False, "msg": "위험구역에 아직 손이 보여요"}), 409
    w = workers.get("safety")
    if w:
        w.estop, w.latched = False, False
    db.set_equipment("프레스 #1", "가동", reason="수동 재가동")
    db.log_event("safety", "수동 재가동", who=_body().get("who", "") or "관리자")
    return jsonify({"ok": True})


@bp.route("/api/safety/lock", methods=["POST"])
def api_lock():
    """정비 잠금 (누구나 걸 수 있음 · 안전 쪽이므로) / 해제는 관리자 PIN"""
    b = _body()
    if b.get("on"):
        v = safety_info.set_lock(b.get("who", ""), b.get("note", ""))
        db.set_equipment("프레스 #1", "안전 정지", reason="정비 잠금")
        return jsonify({"ok": True, "lock": v})
    if not _pin_ok():
        return jsonify({"ok": False, "msg": "PIN이 맞지 않아요"}), 403
    safety_info.clear_lock(b.get("who", ""))
    w = workers.get("safety")
    if w:
        w.last_hit = time.time()          # 잠금 해제 뒤에도 위험구역이 AUTO_SEC 동안 비어야 재가동
    return jsonify({"ok": True})


@bp.route("/api/safety/check", methods=["POST"])
def api_check():
    b = _body()
    return jsonify({"ok": True, "check": safety_info.toggle_check(b.get("i", 0), b.get("who", ""))})
