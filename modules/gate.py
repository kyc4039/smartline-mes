"""[팀원1] 안전 게이트: 보호구 3종(안전모·조끼·장갑)이 확인되어야 MES에 입장(로그인)

동작
  - 입장하지 않은 브라우저는 어느 주소로 가든 /gate(입장 화면)로 이동
  - 보호구 3종이 GATE_HOLD_SEC(기본 1초) 이상 계속 확인되면 자동 입장 → 원래 가려던 페이지로
  - 입장 후 상단 '퇴장' 버튼으로 나감. 세션은 GATE_SESSION_HOURS(기본 8시간) 유지
  - 카메라·모델이 없을 때를 위한 관리자 우회 입장 (ADMIN_PIN, 기본 0000 → config.py에서 꼭 바꾸기)
설정 (config.py에 없으면 아래 기본값 사용)
  GATE_REQUIRED = True        False면 로그인 없이 모든 페이지 접근 (개발용)
  GATE_HOLD_SEC = 1.0
  GATE_SESSION_HOURS = 8
  ADMIN_PIN = "0000"
  SECRET_KEY = "..."          없으면 서버를 켤 때마다 새로 만듦 (재시작하면 다시 입장해야 함)
수정할 곳(팀원1): REQUIRED (모델의 클래스 이름과 맞추기)
"""
import datetime
import secrets
import time
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
import config
import db
from camera_worker import CameraWorker
from streaming import mjpeg
from state import state

# 모델 클래스 이름 → 화면 표시 이름 (팀원1: 자기 모델의 클래스 이름으로 수정)
REQUIRED = {"helmet": "안전모", "vest": "조끼", "gloves": "장갑"}
# 모델마다 이름이 조금씩 달라서 대소문자는 무시하고, 아래 별명도 같은 것으로 본다 (예: Helmet · Hardhat → helmet)
# 다른 이름을 쓰는 모델이면 여기에 "모델 이름(소문자)": "helmet/vest/gloves" 를 추가하거나 config.py에 GATE_ALIASES = {...}
ALIASES = {"hardhat": "helmet", "hard-hat": "helmet", "hard_hat": "helmet", "safety helmet": "helmet", "safety_helmet": "helmet",
           "helmets": "helmet", "safety vest": "vest", "safety_vest": "vest", "safety-vest": "vest", "vests": "vest",
           "reflective vest": "vest", "glove": "gloves", "safety gloves": "gloves", "safety_gloves": "gloves"}
ALIASES.update({str(k).lower(): v for k, v in getattr(config, "GATE_ALIASES", {}).items()})


def _norm(name):
    n = str(name).strip().lower()
    return ALIASES.get(n, n)

GATE_REQUIRED = getattr(config, "GATE_REQUIRED", True)
GATE_HOLD_SEC = getattr(config, "GATE_HOLD_SEC", 1.0)
SESSION_HOURS = getattr(config, "GATE_SESSION_HOURS", 8)
ADMIN_PIN = str(getattr(config, "ADMIN_PIN", "0000"))
OPEN_PATHS = {"/gate", "/gate/video", "/api/gate", "/api/gate/enter", "/api/gate/bypass", "/gate/exit"}


class Worker(CameraWorker):
    def expected_classes(self):
        # 시스템 점검 페이지용: 모델에 같은 뜻의 이름이 있으면 그 이름을 보여 줌 (예: Helmet)
        have = {_norm(c): c for c in getattr(self, "model_classes", [])}
        return [have.get(k, k) for k in REQUIRED]

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.since = None          # 보호구 3종이 모두 보이기 시작한 시각

    def judge(self, frame, dets):
        now = time.time()
        seen = {_norm(d["cls"]) for d in dets}
        found = {k: k in seen for k in REQUIRED}
        all_on = all(found.values())
        self.since = (self.since or now) if all_on else None
        hold = now - self.since if self.since else 0.0
        ready = all_on and hold >= GATE_HOLD_SEC
        missing = [REQUIRED[k] for k, ok in found.items() if not ok]
        return {"items": found, "labels": REQUIRED, "missing": missing, "all_on": all_on, "allowed": ready,
                "hold_seconds": round(hold, 1), "hold_target": GATE_HOLD_SEC,
                "status": "입장 허용" if ready else ("확인 유지 중" if all_on else "착용 확인 중")}

    def on_change(self, old, new, result):
        pass                       # 기록은 실제로 입장할 때(/api/gate/enter) 남김


bp = Blueprint("gate", __name__)


@bp.record_once
def _setup(st):
    app = st.app
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = getattr(config, "SECRET_KEY", None) or secrets.token_hex(16)
    app.permanent_session_lifetime = datetime.timedelta(hours=SESSION_HOURS)
    app.json.sort_keys = False      # 보호구 순서(안전모 → 조끼 → 장갑)를 JSON에서도 그대로 유지


def _safe_next(path):
    """입장 후 돌아갈 주소 (같은 사이트 안의 경로만 허용)"""
    return path if path and path.startswith("/") and not path.startswith("//") and not path.startswith("/gate") else "/"


@bp.before_app_request
def require_entry():
    """입장하지 않았으면 게이트로 보냄 (모든 페이지·API 공통)"""
    if not GATE_REQUIRED or session.get("entered"):
        return None
    p = request.path
    if p in OPEN_PATHS or p.startswith("/static/"):
        return None
    if p.startswith("/api/"):
        return jsonify({"error": "안전 게이트 입장이 필요합니다."}), 401
    return redirect(url_for("gate.page", next=request.full_path.rstrip("?")))


def _enter(how):
    session.permanent = True
    session["entered"], session["entered_at"], session["by"] = True, time.time(), how


@bp.route("/gate")
def page():
    """입장 전용 화면. 이미 입장했거나 게이트를 끈 경우에는 관제 대시보드로"""
    if GATE_REQUIRED and not session.get("entered"):
        return render_template("gate_login.html", next=_safe_next(request.args.get("next")),
                               hold=GATE_HOLD_SEC, labels=list(REQUIRED.values()), bye=bool(request.args.get("bye")), preview=False)
    if request.args.get("preview"):
        # 시연용 미리보기 (10/07): 이미 입장한 사람도 게이트 화면을 그대로 볼 수 있음.
        # 보호구 3종이 확인되면 '입장 완료' 화면만 보여 주고 (로그인 상태는 그대로) 관제 대시보드로 이동
        return render_template("gate_login.html", next=_safe_next(request.args.get("next")),
                               hold=GATE_HOLD_SEC, labels=list(REQUIRED.values()), bye=False, preview=True)
    return redirect("/")


@bp.route("/gate/video")
def video():
    return mjpeg("gate")


@bp.route("/api/gate")
def api():
    return jsonify(state.get("gate"))


@bp.route("/api/gate/enter", methods=["POST"])
def enter():
    """게이트 화면이 '입장 허용'을 보면 호출. 서버가 카메라 판정을 다시 확인한 뒤 입장 처리"""
    g = state.get("gate")
    fresh = time.time() - g.get("updated", 0) < 3
    if not (g.get("allowed") and fresh):
        return jsonify({"ok": False, "reason": "보호구 3종이 아직 확인되지 않았습니다."}), 403
    _enter("ppe")
    db.log_event("gate", "작업자 입장 승인", items=list(REQUIRED.values()))
    return jsonify({"ok": True})


@bp.route("/api/gate/bypass", methods=["POST"])
def bypass():
    pin = str((request.get_json(silent=True) or {}).get("pin", ""))
    if pin != ADMIN_PIN:
        db.log_event("gate", "관리자 우회 입장 실패")
        return jsonify({"ok": False, "reason": "PIN이 맞지 않습니다."}), 403
    _enter("admin")
    db.log_event("gate", "관리자 우회 입장")
    return jsonify({"ok": True})


@bp.route("/gate/exit", methods=["POST"])
def exit_():
    if session.get("entered"):
        db.log_event("gate", "작업자 퇴장")
    session.clear()
    return redirect(url_for("gate.page", bye=1))   # 퇴장 직후에는 바로 다시 자동 입장하지 않도록
