"""시스템 점검 (/system) 데이터 — 10/07 개편
  ① 발표 준비 점수 (정상 항목 / 전체)와 고칠 것 목록
  ② 카메라 3대 동시 부하: 카메라별 입력 해상도 · 분석 FPS · 추론 시간 · 한 바퀴 시간 · 자동 조절 단계 + CPU · 메모리 · GPU
  ③ 카메라 번호 찾기 (scan_cameras): 0~5번을 열어 보고 썸네일 · 해상도 · 사용 중인 기능
  ④ 판정 구역 (안전 위험 · 경고, 품질)
  ⑤ 팀원 모듈: 모델 클래스 ↔ 판정에 쓰는 이름(한글) 일치
  ⑥ 설정 · 데이터 (제품 이름 · PIN · RealSense 라이브러리 · 이전 모델 기록 · 시연 모드 · DB)
"""
import base64
import os
import sys
import time
import cv2
import numpy as np
import config
import db
import analytics
from state import state, workers

LEGACY_TYPES = ("scratch", "wrinkled")        # 종이컵 모델 시절 불량 이름


def _lv(ok, warn=False):
    return "ok" if ok else ("warn" if warn else "fail")


def _names(key):
    """판정에 쓰는 클래스 → 화면 이름 (모델 철자와 대소문자 무시로 비교)"""
    try:
        if key == "gate":
            from modules import gate
            return {k: v for k, v in gate.REQUIRED.items()}, gate._norm
        if key == "quality":
            from modules.quality import PRODUCT_CLASS, DEFECT_CLASSES
            from quality_info import DEFECT_INFO
            d = {PRODUCT_CLASS.lower(): "제품"}
            d.update({c.lower(): DEFECT_INFO.get(c, (c,))[0] for c in DEFECT_CLASSES})
            return d, lambda c: str(c).strip().lower()
        if key == "safety":
            from modules.safety import DANGER_CLASSES, _cls
            return dict(DANGER_CLASSES), _cls
    except Exception:
        pass
    return {}, lambda c: str(c).strip().lower()


def _host():
    out = {"cpu": None, "cores": os.cpu_count(), "mem_used": None, "mem_total": None, "proc_mem": None,
           "device": "CPU", "device_note": "", "psutil": False}
    try:
        import psutil
        out["psutil"] = True
        out["cpu"] = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        out["mem_used"], out["mem_total"] = round(vm.used / 1e9, 1), round(vm.total / 1e9, 1)
        out["proc_mem"] = round(psutil.Process().memory_info().rss / 1e9, 2)
    except Exception:
        pass
    torch = sys.modules.get("torch")            # 모델을 불러올 때 이미 import된 경우만 (점검 때문에 느려지지 않게)
    if torch is not None:
        try:
            if torch.cuda.is_available():
                out["device"], out["device_note"] = "GPU", torch.cuda.get_device_name(0)
            else:
                out["device_note"] = "CUDA 없음 · CPU로 추론"
        except Exception:
            pass
    else:
        out["device_note"] = "모델을 아직 안 불러옴"
    return out


def _realsense():
    try:
        from importlib.metadata import version
        v = version("pyrealsense2")
    except Exception:
        try:
            from importlib.metadata import version
            v = version("pyrealsense2-macosx")
        except Exception:
            v = None
    uses = any(str((config.CAMERAS.get(k) or {}).get("source", "")).lower().startswith("realsense") for k in config.CAMERAS)
    return {"version": v, "used": uses}


def _rel(p):
    """긴 절대 경로 → model_files/gate/best.pt 처럼 짧게"""
    try:
        return os.path.relpath(p, os.path.dirname(config.MODEL_DIR)).replace("\\", "/")
    except Exception:
        return str(p)


def _module(key, w):
    d = w.diagnostics()
    names, norm = _names(key)
    model_cls = d["model_classes"]
    have = {norm(c) for c in model_cls}
    missing = [f"{k}({v})" for k, v in names.items() if d["model_loaded"] and k not in have]
    chips = [{"name": c, "use": norm(c) in names, "kr": names.get(norm(c), "")} for c in model_cls]
    if not model_cls:
        chips = [{"name": k, "use": True, "kr": v, "unknown": True} for k, v in names.items()]
    tgt = d.get("target_fps") or 10
    fps, ms = d["fps"], d.get("infer_ms") or 0
    cam = d["source"] != "None"
    info = d.get("cam_info") or {}
    rs = str(d["source"]).lower().startswith("realsense")
    tips = []
    if cam and d["camera_ok"]:
        if ms >= 80:
            tips.append(f'추론 {ms:.0f}ms로 느림 → config.py CAMERAS["{key}"]에 "imgsz": 480 추가 (분석 크기만 줄이고 화면은 고해상도 유지)')
        if rs and str(info.get("usb", "")).startswith("2"):
            tips.append("RealSense가 USB 2로 연결됨 → 파란 USB 3 포트에 직접 꽂기")
        if fps < tgt * 0.8 and ms < 80 and not d.get("slow"):
            tips.append("CPU가 바쁨 → 다른 프로그램(OBS · 브라우저 탭) 닫기")
        if d.get("slow"):
            tips.append(f"자동 조절 중: {d['slow'] + 1}프레임에 1번 분석 (안전 카메라 우선)")
    load = "skip" if not (cam and d["camera_ok"]) else ("fail" if ms >= 150 or fps < tgt * 0.5 else "warn" if ms >= 80 or fps < tgt * 0.8 else "ok")
    checks = [
        ("카메라 연결", "skip" if not cam else _lv(d["camera_ok"]),
         "꺼짐 (config.py에서 source = None)" if not cam
         else f"source = {d['source']} · 화면이 멈춰 있음 (OBS 가상 카메라 등)" if d.get("camera_frozen")
         else f"source = {d['source']}" + (f" · {d['last_error']}" if not d["camera_ok"] and d["last_error"] else "")),
        ("모델 파일", _lv(d["model_file"]), (_rel(d["model_path"]) + ("" if d["model_file"] else " 없음")) if d["model_path"] else "-"),
        ("모델 불러오기", _lv(d["model_loaded"]), d["model_error"] or "정상"),
        ("클래스 이름 일치", ("fail" if missing else "ok") if d["model_loaded"] else "skip",
         f"모델에 없는 이름: {', '.join(missing)}" if missing else ("판정에 쓰는 이름이 모두 모델에 있음 (대소문자 무시)" if d["model_loaded"] else "모델을 먼저 불러와야 확인 가능")),
        ("처리 부하", load, f"{fps}/{tgt} FPS · 추론 {ms:.0f}ms" if load != "skip" else "카메라가 켜지면 측정"),
    ]
    if cam:
        checks.append(("최근 프레임", _lv(d["last_frame_age"] < 3), f"{d['last_frame_age']}초 전"))
    return {**d, "names": names, "chips": chips, "missing": missing, "tips": tips, "load": load,
            "checks": [{"name": n, "level": l, "detail": t} for n, l, t in checks]}


def _maint_check():
    """설비 보전 모델: web 폴더에 있으면 학습 폴더(EM_model)가 없어도 됨"""
    import maint_model
    if maint_model.available():
        return ("설비 보전 모델", "ok", f"web 폴더 {_rel(maint_model.MODELS)} · 학습 폴더 없이 동작")
    em = os.path.isdir(os.path.join(getattr(config, "EM_MODEL_DIR", ""), "models"))
    return ("설비 보전 모델", "warn" if em else "fail",
            (f"학습 폴더 {getattr(config, 'EM_MODEL_DIR', '')} 사용 중 → tools/export_maint_model.py로 web 폴더에 복사하면 web 폴더만으로 동작"
             if em else f"모델 없음 ({getattr(config, 'EM_MODEL_DIR', '')}) → 더미 분류기"))


def report():
    import demo_mode
    import demo_sim
    mods = [_module(k, w) for k, w in workers.items()]
    host = _host()
    rsi = _realsense()
    pin = str(getattr(config, "ADMIN_PIN", "0000"))
    pname = getattr(config, "PRODUCT_NAME", None)
    with db._lock, db._conn() as c:
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("events", "tickets", "inspections", "feedback")}
        legacy = c.execute(f"SELECT COUNT(*) FROM inspections WHERE defect_type IN ({','.join('?' * len(LEGACY_TYPES))})",
                           LEGACY_TYPES).fetchone()[0]
    try:
        size = round(os.path.getsize(config.DB_PATH) / 1e6, 1)
    except Exception:
        size = None
    sim = demo_sim.status
    try:
        import safety_info
        lock = safety_info.get_lock()
        ck = safety_info.checklist()
    except Exception:
        lock, ck = None, []
    sw = workers.get("safety")
    cfg = [
        ("관리자 PIN", "warn" if pin == "0000" else "ok", "기본값 0000 → config.py ADMIN_PIN을 바꾸세요" if pin == "0000" else "설정됨"),
        ("SECRET_KEY", "ok" if getattr(config, "SECRET_KEY", None) else "warn",
         "설정됨" if getattr(config, "SECRET_KEY", None) else "없음 → 서버를 다시 켜면 모두 재입장"),
        ("제품 이름", "warn" if pname and "컵" in str(pname) else "ok",
         f'"{pname}" → 캔 모델로 바뀌었으니 config.py PRODUCT_NAME 확인' if pname and "컵" in str(pname)
         else f'"{pname or "알루미늄 캔 355ml (기본값)"}"'),
        ("이전 모델 기록", "warn" if legacy else "ok",
         f"scratch · wrinkled {legacy:,}건 → DB 새로 시작(이름 바꿔 보관)하면 깔끔" if legacy else "없음"),
        ("RealSense 라이브러리", ("ok" if rsi["version"] else "fail") if rsi["used"] else "skip",
         (f"pyrealsense2 {rsi['version']}" if rsi["version"] else "설치 안 됨 → uv pip install pyrealsense2") if rsi["used"]
         else (f"pyrealsense2 {rsi['version']} (지금은 안 씀)" if rsi["version"] else "RealSense 안 씀")),
        ("시연 모드", "warn" if demo_mode._on else "ok",
         f"켜져 있음 · 시연 기록 {demo_mode.demo_count()}건" if demo_mode._on else f"꺼짐 · 시연 기록 {demo_mode.demo_count()}건"),
        ("프레스 안전 상태", "warn" if (sw and getattr(sw, "estop", False)) or lock else "ok",
         "비상 정지 중 → 설비 안전 제어에서 수동 재가동" if sw and getattr(sw, "estop", False)
         else f"정비 잠금 중 ({lock.get('who', '')})" if lock else "비상 정지 · 정비 잠금 없음"),
        ("교대 전 안전 점검", "ok" if ck and all(x.get("ts") for x in ck) else "warn",
         f"{sum(1 for x in ck if x.get('ts'))}/{len(ck)} 완료"),
        ("시연용 생산 시뮬레이터", "ok" if sim["enabled"] else "skip",
         f"{sim['reason']} · 시뮬레이션 기록 {db.count_inspections('sim'):,}개" if sim["enabled"] else "꺼짐 (DEMO_PRODUCTION = False)"),
        ("교대 · 목표 사이클", "ok", f"{analytics.SHIFT_START} ~ {analytics.SHIFT_END} · {analytics.TARGET_CYCLE_SEC}초/개"),
        ("자동 조절 (안전 우선)", "ok", "켜짐" if getattr(config, "AUTO_BALANCE", True) else "꺼짐 (AUTO_BALANCE = False)"),
        _maint_check(),
    ]
    cfg = [{"name": n, "level": l, "detail": t} for n, l, t in cfg]
    host_checks = []
    if host["cpu"] is not None:
        host_checks.append({"name": "CPU", "level": "ok" if host["cpu"] < 75 else "warn" if host["cpu"] < 92 else "fail",
                            "detail": f"{host['cpu']:.0f}%"})
    # 발표 준비 점수
    from modules import maintenance
    allc = [dict(c, where=m["key"]) for m in mods for c in m["checks"]] + [dict(c, where="config") for c in cfg] + \
           [dict(c, where="host") for c in host_checks]
    scored = [c for c in allc if c["level"] != "skip"]
    ok = sum(1 for c in scored if c["level"] == "ok")
    todo = [c for c in scored if c["level"] == "fail"] + [c for c in scored if c["level"] == "warn"]
    from modules.safety import WARN_ROI
    return {
        "time": time.time(), "modules": mods, "host": host, "host_checks": host_checks, "config": cfg,
        "ready": {"ok": ok, "total": len(scored), "todo": [{"name": c["name"], "level": c["level"], "detail": c["detail"],
                                                              "where": c["where"]} for c in todo[:8]]},
        "roi": {"safety": list(config.SAFETY_ROI), "warn": list(WARN_ROI), "quality": list(config.QUALITY_ROI)},
        "classifier": maintenance.CLASSIFIER, "realsense": rsi,
        "db": {"path": config.DB_PATH, "size_mb": size, "counts": counts},
    }


def _thumb(img, w=192):
    h = int(img.shape[0] * w / img.shape[1])
    ok, jpg = cv2.imencode(".jpg", cv2.resize(img, (w, h)), [cv2.IMWRITE_JPEG_QUALITY, 70])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode() if ok else None


def scan_cameras(n=6):
    """카메라 번호 0~n-1 을 열어 보고 썸네일 · 해상도. 지금 기능이 쓰는 번호는 열지 않고 그 화면을 보여 줌"""
    used = {}
    for k, w in workers.items():
        if isinstance(w.source, int):
            used[w.source] = k
    api = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    out = []
    for i in range(n):
        if i in used:
            jpg = state.get_frame(used[i])
            thumb = None
            if jpg:
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                thumb = _thumb(img) if img is not None else None
            fw = getattr(workers[used[i]], "frame_size", None)
            out.append({"i": i, "ok": True, "use": used[i], "size": fw, "thumb": thumb, "gray": False})
            continue
        cap = cv2.VideoCapture(i, api)
        item = {"i": i, "ok": False, "use": None, "size": None, "thumb": None, "gray": False}
        try:
            if cap.isOpened():
                ok, img = False, None
                for _ in range(5):                    # 첫 프레임은 검게 나오는 카메라가 있어 몇 장 버림
                    ok, img = cap.read()
                if ok and img is not None:
                    b, g, r = cv2.split(img.astype(np.int16))
                    item.update(ok=True, size=[int(img.shape[1]), int(img.shape[0])], thumb=_thumb(img),
                                gray=bool(np.abs(b - g).mean() < 1.5 and np.abs(g - r).mean() < 1.5))
                else:
                    item["note"] = "열리지만 화면이 안 나옴 (다른 프로그램이 사용 중일 수 있음)"
        finally:
            cap.release()
        out.append(item)
    return out
