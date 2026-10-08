"""[팀장] 설비 보전: 고장 메모 → 담당 분야·조치 시점 판정 → 정비 티켓
분류기: web/model_files/maintenance (maint_model.py) → 없으면 config.EM_MODEL_DIR의 src/predict.py → 둘 다 안 되면 더미 분류기.
"""
import os
import sys
import csv
import datetime
import io
from flask import Blueprint, render_template, jsonify, request, Response
import time
import db
import maint_info
from config import MAINT_SRC, EM_MODEL_DIR, EQUIPMENT

TYPES = ["기계", "전기", "유압공압", "센서"]
URGS = ["상", "중", "하"]

import threading
_classify = None
_load_lock = threading.Lock()
CLASSIFIER = {"state": "not_loaded", "error": "", "path": EM_MODEL_DIR, "source": ""}   # 시스템 점검 페이지용


def get_classifier():
    """처음 요청 때 한 번만 불러온다 (KLUE 때문에 수 초 걸림 · 서버 시작 때 미리 불러옴: config.py MAINT_PRELOAD)
    1순위: web/model_files/maintenance (maint_model.py · tools/export_maint_model.py로 복사 · 확인한 것)
    2순위: 학습 폴더 EM_MODEL_DIR/src/predict.py (예전 방식)
    둘 다 안 되면 더미 분류기"""
    global _classify
    if _classify is not None:
        return _classify
    with _load_lock:
        if _classify is not None:
            return _classify
        t0 = time.time()
        try:
            import maint_model
            if maint_model.available():
                maint_model.load()
                _classify = maint_model.classify
                CLASSIFIER.update(state="loaded", error="", source="web", path=maint_model.MODELS,
                                  load_sec=round(time.time() - t0, 1), models=maint_model.INFO["models"],
                                  klue_offline=maint_model.INFO["klue_offline"])
                print(f"[maintenance] v5 분류기 불러옴 · web 폴더 모델 ({maint_model.MODELS}, {CLASSIFIER['load_sec']}초)")
                return _classify
        except Exception as e:
            print(f"[maintenance] web 폴더 모델 불러오기 실패 → 학습 폴더로: {e}")
            CLASSIFIER["web_error"] = str(e)[:200]
        cwd = os.getcwd()
        try:
            if MAINT_SRC not in sys.path:
                sys.path.insert(0, MAINT_SRC)
            os.chdir(EM_MODEL_DIR)        # predict.py가 'models/...' 경로로 모델을 찾으므로 잠시 이동
            from predict import classify
            _classify = classify
            CLASSIFIER.update(state="loaded", error="", source="em_model", path=EM_MODEL_DIR, load_sec=round(time.time() - t0, 1))
            print(f"[maintenance] v5 분류기 불러옴 · 학습 폴더 ({EM_MODEL_DIR})")
        except Exception as e:
            print(f"[maintenance] 분류기 불러오기 실패 → 더미 분류기: {e}")
            CLASSIFIER.update(state="dummy", error=str(e)[:200], source="dummy")
            _classify = lambda text: {"type": "기계", "type_name": "기계 정비", "urgency": "하",
                                      "urgency_name": "정기 점검", "urgency_probs": {}, "type_probs": {},
                                      "danger_rule_applied": False, "need_review": True,
                                      "review_reasons": ["더미 분류기"], "collab": None}
        finally:
            os.chdir(cwd)                 # 웹 서버 폴더로 복귀
    return _classify


def preload():
    """서버 시작 때 백그라운드로 미리 불러오기 → 첫 정비 요청이 바로 판정됨 (끄기: config.py MAINT_PRELOAD = False)"""
    import threading
    import config as _cfg
    if getattr(_cfg, "MAINT_PRELOAD", True):
        threading.Thread(target=get_classifier, daemon=True, name="maint-preload").start()


bp = Blueprint("maintenance", __name__)


@bp.route("/maintenance")
def page():
    return render_template("maintenance.html", equipment=EQUIPMENT)


# 문장에서 설비를 찾기 위한 이름·별칭 (현장 줄임말 포함). 필요하면 추가
EQUIP_ALIASES = {
    "프레스 #1": ["프레스", "press", "램", "금형", "상사점"],
    "컨베이어": ["컨베이어", "컨베어", "콘베어", "벨트", "스프로킷"],
    "로봇 적재기": ["로봇", "적재기", "그리퍼", "티칭"],
    "비전 검사기": ["비전", "검사기", "비전pc"],
    "자재 투입기": ["투입기", "자재투입", "호퍼", "피더"],
}


def detect_equipment(text):
    """문장에 언급된 설비 목록 (띄어쓰기·대소문자 무시)"""
    t = text.replace(" ", "").lower()
    return [eq for eq, aliases in EQUIP_ALIASES.items() if any(a.replace(" ", "").lower() in t for a in aliases)]


@bp.route("/api/detect_equipment")
def api_detect():
    """입력 중인 문장에서 설비 찾기 → 화면이 드롭다운을 자동 선택하는 데 사용"""
    return jsonify({"detected": detect_equipment(request.args.get("text", ""))})


def _confirm_reason(found, selected, result):
    """접수 전에 설비 확인이 필요한 경우와 그 이유"""
    if len(found) > 1:
        return f"문장에 여러 설비({', '.join(found)})가 나와요. 고장 난 설비를 골라 주세요."
    if len(found) == 1 and found[0] != selected:
        return f"문장에서 찾은 설비는 '{found[0]}', 선택한 설비는 '{selected}'입니다. 어느 설비로 접수할까요?"
    if not found and result["urgency"] == "상":
        return f"즉시 조치로 판정되어 선택한 설비({selected})가 멈춥니다. 문장에 설비 이름이 없으니 맞는지 확인해 주세요."
    return None


@bp.route("/api/classify", methods=["POST"])
def api_classify():
    """confirmed=false: 판정 후 설비 확인이 필요하면 티켓을 만들지 않고 확인 요청을 돌려줌
       confirmed=true : 사용자가 확인한 설비로 티켓 생성"""
    body = request.get_json(force=True)
    text = (body.get("text") or "").strip()
    equipment = body.get("equipment") or ""
    if not text:
        return jsonify({"error": "고장 내용을 입력하세요."}), 400
    result = get_classifier()(text)
    found = detect_equipment(text)

    if not body.get("confirmed"):
        reason = _confirm_reason(found, equipment, result)
        if reason:
            options = list(dict.fromkeys(found + [equipment]))      # 문장 속 설비 먼저, 선택한 설비 마지막
            return jsonify({"needs_confirm": True, "reason": reason, "options": options, **result,
                            "similar": maint_info.similar(equipment, result["type"]),
                            "steps": maint_info.steps(result["type"], equipment)})

    ticket_id = db.create_ticket(equipment, text, result)
    db.log_event("maintenance", "정비 요청 접수", ticket=ticket_id, equipment=equipment,
                 type=result["type"], urgency=result["urgency"])
    if result["urgency"] == "상" and equipment:          # 연동 규칙: 즉시 조치면 해당 설비 정지
        db.set_equipment(equipment, "고장 정지", reason=f"정비 요청 #{ticket_id}")
    return jsonify({"ticket_id": ticket_id, "equipment": equipment, **result,
                    "similar": maint_info.similar(equipment, result["type"], exclude=ticket_id),   # 비슷한 지난 정비
                    "steps": maint_info.steps(result["type"], equipment)})                         # 추천 점검 순서


@bp.route("/api/tickets")
def api_tickets():
    return jsonify(db.list_tickets(30))


@bp.route("/api/tickets/<int:tid>/complete", methods=["POST"])
def api_complete(tid):
    """정비 완료 처리: 티켓을 완료로 바꾸고, 그 설비에 남은 즉시 조치 티켓이 없으면 재가동"""
    t = db.get_ticket(tid)
    if not t:
        return jsonify({"error": "없는 티켓입니다."}), 404
    if t["status"] == "완료":
        return jsonify({"ticket_id": tid, "status": "완료", "restarted": False})
    fb = (request.get_json(silent=True) or {}).get("feedback")   # {"true_type", "true_urgency", "note"} 또는 없음
    if fb and fb.get("true_type") in TYPES and fb.get("true_urgency") in URGS:
        db.save_feedback(t, fb["true_type"], fb["true_urgency"], (fb.get("note") or "")[:200])
    db.complete_ticket(tid, ((request.get_json(silent=True) or {}).get("action") or "")[:200])
    db.log_event("maintenance", "정비 완료", ticket=tid, equipment=t["equipment"],
                 feedback=("맞음" if fb and fb["true_type"] == t["type"] and fb["true_urgency"] == t["urgency"]
                           else "수정" if fb else "없음"))
    unlocked = _release_lock(tid)                      # 이 티켓으로 건 정비 잠금이면 같이 해제
    restarted = False
    eq = t["equipment"]
    if eq and db.open_urgent_tickets(eq) == 0:
        status = {e["name"]: e["status"] for e in db.get_equipment()}.get(eq)
        if status == "고장 정지":                       # 고장 정지만 풀어 줌 (안전 정지 등은 각자 규칙으로)
            restarted = db.set_equipment(eq, "가동", reason=f"정비 완료 #{tid}")
    return jsonify({"ticket_id": tid, "status": "완료", "restarted": restarted, "unlocked": unlocked})


# ---------------------------------------------------------------- 정비 진행 (10/07)
LOCKABLE = {"프레스 #1"}          # 정비 잠금(LOTO)이 연결된 설비 (설비 안전 제어 페이지와 같은 잠금)


@bp.route("/api/tickets/<int:tid>/start", methods=["POST"])
def api_start(tid):
    """정비 시작: 대기 → 조치 중. lock=true면 프레스 정비 잠금도 같이 건다 (정비하는 동안 기동 금지)"""
    t = db.get_ticket(tid)
    if not t or t["status"] == "완료":
        return jsonify({"error": "없는 티켓이거나 이미 완료됐어요."}), 404
    b = request.get_json(silent=True) or {}
    who = (b.get("who") or "").strip()[:12] or "정비원"
    db.start_ticket(tid, who)
    locked = False
    if b.get("lock") and t["equipment"] in LOCKABLE:
        import safety_info
        if not safety_info.get_lock(fresh=True):
            safety_info.set_lock(who, note=f"정비 #{tid}")
            db.set_equipment(t["equipment"], "안전 정지", reason="정비 잠금")
            locked = True
    db.log_event("maintenance", "정비 시작", ticket=tid, equipment=t["equipment"], who=who, lock=locked)
    return jsonify({"ok": True, "locked": locked})


def _release_lock(tid):
    """정비 완료 시: 이 티켓 번호로 걸린 정비 잠금이면 해제 (건 사람이 푸는 것 = LOTO 원칙).
    해제 뒤에도 위험구역이 비어 있는 몇 초가 지나야 프레스가 다시 작동한다."""
    try:
        import safety_info
        from state import workers
        lk = safety_info.get_lock(fresh=True)
        if not lk or lk.get("note") != f"정비 #{tid}":
            return False
        safety_info.clear_lock(lk.get("who", ""))
        w = workers.get("safety")
        if w:
            w.last_hit = time.time()
        else:                                          # 안전 카메라 모듈이 없으면 바로 가동으로
            db.set_equipment("프레스 #1", "가동", reason=f"정비 잠금 해제 #{tid}")
        return True
    except Exception as e:
        print(f"[maintenance] 정비 잠금 해제 실패: {e}")
        return False


@bp.route("/api/maint/info")
def api_maint_info():
    return jsonify(maint_info.info())


@bp.route("/api/maint/pm", methods=["POST"])
def api_pm():
    b = request.get_json(silent=True) or {}
    maint_info.toggle_pm(b.get("day", ""), b.get("equipment", ""), b.get("task", ""), (b.get("who") or "")[:12])
    return jsonify({"ok": True, "pm": maint_info.pm_week()})


# ======================================================================
# 정비원 피드백 학습 루프: 실제 현장 정확도와 재학습 데이터
# ======================================================================
RETRAIN_MIN_FEEDBACK = 50     # 이만큼 쌓이면 재학습 권장
TREND_WINDOW = 10             # 정확도 추이: 최근 10건 이동 평균


def feedback_stats():
    rows = db.all_feedback()
    n = len(rows)
    t_ok = [r["ai_type"] == r["true_type"] for r in rows]
    u_ok = [r["ai_urgency"] == r["true_urgency"] for r in rows]
    both = [a and b for a, b in zip(t_ok, u_ok)]
    rate = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    trend = [{"i": i + 1, "acc": rate(both[max(0, i + 1 - TREND_WINDOW): i + 1])} for i in range(n)]
    conf = {a: {b: 0 for b in URGS} for a in URGS}                 # 행: 실제, 열: AI
    for r in rows:
        conf[r["true_urgency"]][r["ai_urgency"]] += 1
    corrections = [r for r, ok in zip(rows, both) if not ok][::-1]
    return {
        "n": n, "type_acc": rate(t_ok), "urg_acc": rate(u_ok), "both_acc": rate(both),
        "true_urgent": sum(r["true_urgency"] == "상" for r in rows),
        "missed_urgent": sum(r["true_urgency"] == "상" and r["ai_urgency"] != "상" for r in rows),
        "false_alarm": sum(r["true_urgency"] != "상" and r["ai_urgency"] == "상" for r in rows),
        "corrections_n": len(corrections), "corrections": corrections[:10],
        "trend": trend, "window": TREND_WINDOW, "confusion": conf,
        "retrain_min": RETRAIN_MIN_FEEDBACK,
    }


@bp.route("/feedback")
def feedback_page():
    return render_template("feedback.html")


@bp.route("/api/feedback/stats")
def api_feedback_stats():
    return jsonify(feedback_stats())


@bp.route("/api/feedback/export.csv")
def api_feedback_export():
    """재학습용 데이터: 정비원이 확인한 정답(true_*)을 라벨로 사용. EM_model 학습 데이터와 같은 열 이름(text, type, urgency)"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["text", "type", "urgency", "source", "corrected", "ai_type", "ai_urgency", "equipment", "ticket_id", "date", "note"])
    for r in db.all_feedback():
        corrected = int(r["ai_type"] != r["true_type"] or r["ai_urgency"] != r["true_urgency"])
        w.writerow([r["text"], r["true_type"], r["true_urgency"], "field", corrected, r["ai_type"], r["ai_urgency"],
                    r["equipment"], r["ticket_id"], datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M"),
                    r["note"] or ""])
    name = f"field_feedback_{datetime.date.today():%Y%m%d}.csv"
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})
