"""공통 페이지: 공정 현황 대시보드와 전체 상태 API"""
import datetime
from flask import Blueprint, render_template, jsonify
import db
import incidents
import analytics
import os
import time
import config
from flask import request
from state import workers
from config import EQUIPMENT
from modules.safety import AUTO_SEC
from state import state

bp = Blueprint("core", __name__)

# ----------------------------------------------------------------------
# 화면 단순화: 메뉴에서 숨길 페이지, 디지털 트윈에서 보일 추가 기능
#   config.py에 아래 두 줄을 넣으면 바꿀 수 있다 (없으면 이 기본값)
#     HIDE_PAGES = ["timeline", "report", "feedback"]   # 숨김 없음: []
#     TWIN_FEATURES = ["replay"]                         # 전부: ["layers", "sim", "replay"]
#   숨긴 페이지도 주소(/timeline 등)로 직접 들어가면 열린다. 코드는 지우지 않았다.
# ----------------------------------------------------------------------
HIDE_PAGES = set(getattr(config, "HIDE_PAGES", ["timeline", "report", "feedback"]))
TWIN_FEATURES = set(getattr(config, "TWIN_FEATURES", ["replay"]))
FLOW_V2 = bool(getattr(config, "FLOW_V2", True))     # 새 라인 흐름 (검사 기록 1줄 = 상자 1개). 예전 방식: config.py FLOW_V2 = False


@bp.app_context_processor
def ui_options():
    """모든 화면(템플릿)에서 hide_pages, twin_features를 쓸 수 있게 넘겨줌"""
    import analytics
    return {"hide_pages": HIDE_PAGES, "twin_features": TWIN_FEATURES, "flow_v2": FLOW_V2,
            "takt": f"{analytics.TARGET_CYCLE_SEC:g}", "inspect_sec": f"{analytics.INSPECT_SEC:g}"}


@bp.route("/")
def dashboard():
    return render_template("dashboard.html")


@bp.route("/api/dashboard/summary")
def api_dashboard_summary():
    """관제 대시보드 요약 (각 페이지의 핵심 숫자 · 지금 할 일 · 오늘 설비 상태 띠)"""
    import dash_info
    return jsonify(dash_info.summary())


@bp.route("/api/state")
def api_state():
    """화면이 1초마다 물어보는 주소: 모든 기능의 최신 상태 + 설비 상태 + 최근 이벤트"""
    return jsonify({"modules": state.get(), "equipment": db.get_equipment(),
                    "events": db.recent_events(15), "tickets": db.list_tickets(30)})


@bp.route("/api/dashboard")
def api_dashboard():
    """관제 대시보드 지표: 오늘 검사 수(DB 기준이라 서버를 다시 켜도 유지), 이번 교대 OEE"""
    now = time.time()
    midnight = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
    insp = db.inspections_between(midnight, now + 1)
    o = analytics.oee("shift")
    return jsonify({"inspections_today": len(insp), "defects_today": sum(i["result"] == "불량" for i in insp),
                    "oee": {k: o[k] for k in ("oee", "availability", "performance", "quality")},
                    "oee_window": o["window"]})


@bp.route("/twin")
def twin():
    """디지털 트윈: 비스듬히 내려다본 입체 공정 라인"""
    return render_template("twin.html")


@bp.route("/api/twin")
def api_twin():
    """설비별 상세 (오늘 정지 횟수, 관련 이벤트, 미완료 정비 요청)"""
    midnight = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
    return jsonify({name: db.equipment_detail(name, midnight) for name in EQUIPMENT})


@bp.route("/api/twin/eq")
def api_twin_eq():
    """트윈에서 설비를 눌렀을 때 오른쪽 메뉴의 '그 설비만의' 숫자"""
    import twin_info
    return jsonify(twin_info.info(request.args.get("name", "")))


@bp.route("/api/twin/layers")
def api_twin_layers():
    """① 레이어(정지 빈도 · OEE · 정비 요청) + ② 오늘 불량 배출 · 위험구역 진입 요약"""
    import twin_data
    k = request.args.get("range", "shift")
    return jsonify(twin_data.layers(k if k in ("shift", "today") else "shift"))


@bp.route("/api/twin/replay")
def api_twin_replay():
    """③ 리플레이: 기간 안의 설비 상태 구간, 사건 표식, 불량 시각"""
    import twin_data
    k = request.args.get("range", "hour")
    return jsonify(twin_data.replay(k if k in ("hour", "shift", "today") else "hour"))


# ======================================================================
# 생산관리: LOT(1시간 = 1 LOT, config의 LOT_MINUTES로 변경) 생산 · 출하
# ======================================================================
@bp.route("/production")
def production_page():
    return render_template("production.html")


@bp.route("/api/production")
def api_production():
    import production
    return jsonify(production.summary())


@bp.route("/api/production/export.csv")
def api_production_csv():
    """오늘 LOT 목록을 엑셀에서 열 수 있는 CSV로 (한글이 깨지지 않게 UTF-8 BOM)"""
    import csv, io, production
    from flask import Response
    d = production.summary(max_rows=10000)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["LOT", "시작", "트럭 출발", "걸린 시간(분)", "생산", "양품", "불량", "불량률(%)", "팔레트",
                "목표 대비 속도(%)", "정지 횟수", "정지 시간(분)", "정지 손실(개)", "시뮬레이션 비율(%)", "상태"])
    t = lambda ts: datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
    for l in reversed(d["lots"]):
        w.writerow([l["id"], t(l["start"]), t(l["end"]), round(l["duration"] / 60, 1), l["total"], l["good"], l["defects"],
                    round((l["rate"] or 0) * 100, 1), l["pallets"], round((l["speed"] or 0) * 100), l["stops"],
                    round(l["down_sec"] / 60, 1), l["loss"], round(l["sim_ratio"] * 100), l["status"]])
    name = f"LOT_{datetime.date.today():%Y%m%d}.csv"
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


# ======================================================================
# 품질 검사 상세: 생산 정보 · AI 판정 상세 · 불량률 추이 · 원인 · 이력 · 불량품 처리 (quality_info.py)
# ======================================================================
@bp.route("/api/quality/info")
def api_quality_info():
    import quality_info
    f = request.args.get("filter", "bad")
    return jsonify(quality_info.info(f if f in ("all", "bad", "pending") else "bad", request.args.get("lot") or None))


@bp.route("/api/quality/false.csv")
def api_quality_false_csv():
    """오판(실제로는 정상품) 목록 → 팀원2 모델 재학습용 CSV"""
    import csv, io, json as _json, quality_info
    from flask import Response
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["검사 ID", "시각", "AI 판정 유형", "신뢰도", "검출 상자 x1", "y1", "x2", "y2", "모델", "출처"])
    for r in quality_info.false_rows():
        b = _json.loads(r["box"]) if r.get("box") else ["", "", "", ""]
        w.writerow([r["id"], datetime.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S"), r.get("defect_type") or "",
                    r.get("conf") or "", *b, r.get("model") or "", r.get("source") or "camera"])
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=quality_false_positives.csv"})


@bp.route("/api/quality/dispose", methods=["POST"])
def api_quality_dispose():
    import quality_info
    body = request.get_json(silent=True) or {}
    out, err = quality_info.dispose(int(body.get("id") or 0), str(body.get("action") or ""))
    return (jsonify(out), 200) if out else (jsonify({"error": err}), 400)


@bp.route("/api/incidents")
def api_incidents():
    """진행 중인 사건과 오늘 끝난 사건 (사건 연쇄 카드용)"""
    return jsonify({**incidents.today(), "auto_sec": AUTO_SEC})


# ======================================================================
# 설비 분석: 타임라인 · OEE · 교대 보고서
# ======================================================================
def _kind():
    k = request.args.get("range", "shift")
    return k if k in ("shift", "today", "prev") else "shift"


@bp.route("/timeline")
def timeline_page():
    return render_template("timeline.html")


@bp.route("/oee")
def oee_page():
    return render_template("oee.html")


@bp.route("/report")
def report_page():
    return render_template("report.html")


@bp.route("/api/timeline")
def api_timeline():
    return jsonify(analytics.timeline(_kind()))


@bp.route("/api/oee")
def api_oee():
    return jsonify(analytics.oee(_kind()))


@bp.route("/api/oee/info")
def api_oee_info():
    """OEE 페이지 전용 (손실 폭포 · 개선 기회 · 7일 추이 · 요일×시간 지도 · 시뮬레이터 기준)"""
    import oee_info
    k = request.args.get("range", "shift")
    return jsonify(oee_info.info(k if k in ("shift", "today", "prev", "week") else "shift"))


@bp.route("/api/report")
def api_report():
    return jsonify(analytics.report(_kind()))


@bp.route("/api/report/memo", methods=["POST"])
def api_report_memo():
    body = request.get_json(silent=True) or {}
    key, text = str(body.get("key", ""))[:40], str(body.get("text", ""))[:2000]
    if not key:
        return jsonify({"ok": False}), 400
    db.set_note(key, text)
    return jsonify({"ok": True})


# ======================================================================
# 시스템 점검: 팀원 모듈 통합 상태 (카메라 · 모델 · 클래스 이름 · 분류기 · 설정)
# ======================================================================
@bp.route("/system")
def system_page():
    return render_template("system.html")


@bp.route("/api/line/flow")
def api_line_flow():
    """라인 흐름 장부 (line_flow.py · FLOW_V2): 트윈 · 대시보드 · 생산 관리 트럭이 같이 씀"""
    import line_flow
    return jsonify(line_flow.flow())


@bp.route("/api/system")
def api_system():
    """점검 페이지 데이터 (system_info.py): 발표 준비 · 부하 · 판정 구역 · 모듈 클래스 · 설정"""
    import system_info
    return jsonify(system_info.report())


@bp.route("/api/system/frame/<key>")
def api_system_frame(key):
    """판정 구역 미리보기용: 그 카메라의 최신 화면 한 장"""
    from flask import Response, abort
    jpg = state.get_frame(key)
    if not jpg:
        abort(404)
    return Response(jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@bp.route("/api/system/scan-cameras", methods=["POST"])
def api_scan_cameras():
    """카메라 번호 찾기: 0~5번 웹캠을 열어 보고 썸네일 (사용 중인 번호는 그 기능 화면)"""
    import system_info
    return jsonify({"cams": system_info.scan_cameras(), "time": time.time()})


# ======================================================================
# 시연 모드 (demo_mode.py): /demo 페이지 · 어느 페이지에서나 Shift+D 리모컨
#   켜기는 관리자 PIN · 켠 브라우저(세션)만 버튼을 누를 수 있음
# ======================================================================
def _demo_ok():
    from flask import session
    return session.get("demo_admin") or session.get("by") == "admin"


@bp.route("/demo")
def demo_page():
    import demo_mode
    return render_template("demo.html", groups=demo_mode.GROUPS,
                           events=[{"id": k, "g": v[0], "name": v[1], "desc": v[2], "lv": v[3], "toggle": v[5]}
                                   for k, v in demo_mode.EVENTS.items()])


@bp.route("/api/demo/status")
def api_demo_status():
    import demo_mode
    return jsonify({**demo_mode.status(), "allowed": bool(_demo_ok())})


@bp.route("/api/demo/on", methods=["POST"])
def api_demo_on():
    from flask import session
    import demo_mode
    body = request.get_json(silent=True) or {}
    if body.get("on"):
        if not _demo_ok() and str(body.get("pin", "")) != str(getattr(config, "ADMIN_PIN", "0000")):
            return jsonify({"ok": False, "msg": "PIN이 맞지 않아요"}), 403
        session["demo_admin"] = True
        demo_mode.set_on(True)
    else:
        if not _demo_ok():
            return jsonify({"ok": False, "msg": "시연을 켠 관리자만 끌 수 있어요"}), 403
        demo_mode.set_on(False)
    return jsonify({"ok": True, **demo_mode.status()})


@bp.route("/api/demo/trigger", methods=["POST"])
def api_demo_trigger():
    import demo_mode
    if not _demo_ok():
        return jsonify({"ok": False, "msg": "시연 제어판에서 PIN으로 먼저 켜 주세요"}), 403
    ok, msg = demo_mode.trigger((request.get_json(silent=True) or {}).get("id", ""))
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp.route("/api/demo/scenario", methods=["POST"])
def api_demo_scenario():
    import demo_mode
    if not _demo_ok():
        return jsonify({"ok": False, "msg": "권한 없음"}), 403
    b = request.get_json(silent=True) or {}
    demo_mode.scenario(b.get("cmd", ""), b.get("i"))
    return jsonify({"ok": True, **demo_mode.status()})


@bp.route("/api/demo/reset", methods=["POST"])
def api_demo_reset():
    import demo_mode
    if not _demo_ok():
        return jsonify({"ok": False, "msg": "권한 없음"}), 403
    demo_mode.reset()
    return jsonify({"ok": True})


@bp.route("/api/demo/clear", methods=["POST"])
def api_demo_clear():
    import demo_mode
    if not _demo_ok():
        return jsonify({"ok": False, "msg": "권한 없음"}), 403
    return jsonify({"ok": True, **demo_mode.clear_records()})


def _sim_status():
    import demo_sim
    return demo_sim.status


@bp.route("/api/system/clear-sim", methods=["POST"])
def api_clear_sim():
    """시연용 시뮬레이터가 만든 검사 기록만 지우기 (카메라 실제 기록은 그대로)"""
    return jsonify({"deleted": db.delete_sim_inspections()})


@bp.route("/api/system/classifier-test", methods=["POST"])
def api_classifier_test():
    from modules import maintenance
    t0 = time.time()
    r = maintenance.get_classifier()("프레스 바닥에 기름이 고여서 미끄러워요")
    return jsonify({"elapsed": round(time.time() - t0, 2), "result": r, "classifier": maintenance.CLASSIFIER})
