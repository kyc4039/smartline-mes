"""카메라 워커 공통 틀 — 팀원은 이 파일을 수정하지 않고, 자기 모듈에서 judge()만 채운다.

한 워커 = 카메라 한 대. 화면을 보는 사람이 없어도 항상 돌아간다.
반복: 프레임 읽기 → YOLO 추론(detect) → 판정(judge) → 그리기(draw) → 공유 상태 갱신
      → 상태(status)가 바뀌면 on_change() 호출 (DB 기록 등)
카메라나 모델이 없으면 '더미 모드'로 돌아가서, 나머지 기능 개발을 막지 않는다.
"""
import os
import threading
import time
import cv2
import numpy as np
import config
import db
import realsense
import demo_mode
from config import FPS, JPEG_QUALITY, CONF, MODEL_DIR
from state import state

RS_TOLERATE = int(getattr(config, "REALSENSE_TOLERATE", 5))   # RealSense 프레임이 이 횟수 연속 안 오면 그때 다시 연결


class CameraWorker(threading.Thread):
    def __init__(self, key, source, model_file):
        super().__init__(daemon=True, name=f"worker-{key}")
        self.key, self.source = key, source
        self.model_path = os.path.join(MODEL_DIR, model_file) if model_file else None
        self.model = self.load_model()
        self.status = None
        self.cap = None
        self.next_try = 0.0       # 카메라가 없을 때 5초마다 다시 연결 시도

    # ---------------- 모델 ----------------
    # ---------------- 진단 (시스템 점검 페이지용) ----------------
    def expected_classes(self):
        """이 기능이 판정에 쓰는 클래스 이름 (모듈에서 덮어씀). 모델에 없으면 점검 페이지에서 경고"""
        return []

    def diagnostics(self):
        return {"key": self.key, "source": str(self.source),
                "camera_ok": getattr(self, "cap", None) is not None and not getattr(self, "frozen", False),
                "camera_frozen": getattr(self, "frozen", False),
                "model_path": self.model_path, "model_file": bool(self.model_path and os.path.exists(self.model_path)),
                "model_loaded": self.model is not None, "model_error": getattr(self, "model_error", ""),
                "model_classes": getattr(self, "model_classes", []), "expected": self.expected_classes(),
                "fps": round(getattr(self, "fps", 0.0), 1), "last_frame_age": round(time.time() - getattr(self, "last_ts", 0), 1),
                "last_error": getattr(self, "last_error", ""), "status": self.status,
                # 부하 점검 (10/07): 추론 시간 · 한 바퀴 시간 · 실제 해상도 · 자동 조절 단계 · RealSense 정보
                "infer_ms": round(getattr(self, "infer_ms", 0.0), 1), "loop_ms": round(getattr(self, "loop_ms", 0.0), 1),
                "frame_wh": getattr(self, "frame_size", None), "target_fps": FPS, "slow": getattr(self, "slow", 0),
                "imgsz": (config.CAMERAS.get(self.key) or {}).get("imgsz") or getattr(config, "DETECT_IMGSZ", None),
                "cam_info": getattr(getattr(self, "cap", None), "info", None) or getattr(self, "cam_info", None),
                "demo": demo_mode.engaged(self.key)}

    def load_model(self):
        self.model_error, self.model_classes = "", []
        if not self.model_path or not os.path.exists(self.model_path):
            print(f"[{self.key}] 모델 파일 없음 → 더미 모드 ({self.model_path})")
            self.model_error = "모델 파일 없음"
            return None
        try:
            from ultralytics import YOLO
            m = YOLO(self.model_path)
            self.model_classes = [str(v) for v in m.names.values()]
            print(f"[{self.key}] 모델 불러옴: {self.model_path}")
            return m
        except Exception as e:
            print(f"[{self.key}] 모델 불러오기 실패 → 더미 모드: {e}")
            self.model_error = str(e)[:200]
            return None

    def detect(self, frame):
        """YOLO 결과를 공통 형식으로: [{"cls": "helmet", "conf": 0.91, "box": (x1, y1, x2, y2)}, ...]"""
        if self.model is None:
            return []
        imgsz = (config.CAMERAS.get(self.key) or {}).get("imgsz") or getattr(config, "DETECT_IMGSZ", None)
        kw = {"imgsz": int(imgsz)} if imgsz else {}           # 분석 크기 (작을수록 빠름 · 화면 해상도는 그대로)
        t0 = time.time()
        r = self.model(frame, conf=CONF, verbose=False, **kw)[0]
        ms = (time.time() - t0) * 1000
        self.infer_ms = ms if not getattr(self, "infer_ms", 0) else 0.85 * self.infer_ms + 0.15 * ms
        return [{"cls": r.names[int(c)], "conf": float(p), "box": tuple(int(v) for v in b)}
                for b, p, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]

    # ---------------- 팀원이 채우는 부분 ----------------
    def judge(self, frame, dets):
        """판정 로직. 반드시 'status' 키를 포함한 dict를 돌려준다. (모듈에서 덮어씀)"""
        return {"status": "감지 없음" if not dets else f"{len(dets)}개 감지"}

    def on_change(self, old, new, result):
        """status가 바뀔 때 한 번 호출된다. 기본: 이벤트 로그 기록"""
        db.log_event(self.key, f"{old} → {new}")

    # ---------------- 그리기 ----------------
    def draw(self, frame, dets, result):
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            cv2.putText(frame, f"{d['cls']} {d['conf']:.2f}", (x1, max(15, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
        tag = "DUMMY " if self.model is None else ""
        cv2.putText(frame, f"{tag}{self.key.upper()}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return frame

    # ---------------- 카메라 ----------------
    def _open(self):
        """source: 웹캠 번호 / 영상 파일 / "realsense" · "realsense:시리얼" (Intel RealSense, realsense.py)"""
        if self.source is None:
            return None
        if realsense.is_realsense(self.source):
            cap = realsense.RealSenseCapture(self.source)
            if not cap.isOpened():
                self.last_error = cap.error
                return None
            return cap
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            return None
        # 웹캠 해상도: 카메라별 "size": (1280, 720) → 없으면 전체 CAMERA_SIZE → 없으면 카메라 기본값(보통 640×480)
        size = (config.CAMERAS.get(self.key) or {}).get("size") or getattr(config, "CAMERA_SIZE", None)
        if size and isinstance(self.source, int):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0]); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        return cap

    def depth_at(self, x, y):
        """RealSense(깊이 켬)일 때 화면 (x, y)까지 거리(m). 아니면 None — 모듈 judge()에서 거리 판정에 쓸 수 있음"""
        f = getattr(self.cap, "depth_at", None)
        return f(x, y) if f else None

    def _rs_note(self):
        e = getattr(self, "last_error", "") or ""          # 화면 글씨는 영어만 나오므로 짧게 바꿔 표시
        if "설치" in e:
            return "pyrealsense2 not installed -> uv pip install pyrealsense2"
        if "찾지" in e:
            return "RealSense not found -> check USB 3 port / serial (python web/realsense.py)"
        return "RealSense start failed -> see server log" if e else ""

    def _placeholder(self, note=""):
        f = np.full((360, 640, 3), 40, dtype=np.uint8)
        cv2.putText(f, f"NO CAMERA: {self.key} (source={self.source})", (20, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)
        if note:
            cv2.putText(f, note, (20, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1)
        return f

    # ---------------- 멈춘 화면 감지 ----------------
    # OBS 가상 카메라처럼 '카메라인 척하는' 장치는 꺼져 있을 때 똑같은 그림(로고)만 계속 보낸다.
    # 진짜 카메라는 아무것도 안 움직여도 잡음 때문에 화면이 조금씩 변하므로,
    # 화면이 FROZEN_SEC초 넘게 완전히 똑같으면 '카메라 없음'으로 본다 (판정·박스 그리기 안 함).
    FROZEN_SEC = 3.0
    FROZEN_DIFF = 0.05      # 이전 프레임과의 평균 밝기 차이가 이보다 작으면 '똑같음'

    def _is_frozen(self, frame):
        g = cv2.cvtColor(frame[::2, ::2], cv2.COLOR_BGR2GRAY).astype(np.int16)
        prev, self._prev_gray = getattr(self, "_prev_gray", None), g
        if prev is None or prev.shape != g.shape or np.abs(g - prev).mean() >= self.FROZEN_DIFF:
            self._still_since = None
            return False
        self._still_since = getattr(self, "_still_since", None) or time.time()
        return time.time() - self._still_since >= self.FROZEN_SEC

    def read(self):
        if self.cap is None and time.time() >= self.next_try:
            self.cap = self._open()
            if self.cap is None:
                self.next_try = time.time() + 5
        if self.cap is not None:
            ok, frame = self.cap.read()
            if ok:
                self.fail_n, self.last_good = 0, frame
                return frame
            # RealSense(USB 2 · 카메라 여러 대)는 프레임이 가끔 늦게 옴 → 바로 끊지 말고 몇 번은 마지막 화면 유지
            if realsense.is_realsense(self.source):
                self.fail_n = getattr(self, "fail_n", 0) + 1
                if self.fail_n <= RS_TOLERATE and getattr(self, "last_good", None) is not None:
                    return self.last_good
            if isinstance(self.source, str) and not realsense.is_realsense(self.source):   # 테스트 영상이면 처음부터 다시
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
                if ok:
                    return frame
            self.cap.release()
            self.cap = None
        return self._placeholder(self._rs_note() if realsense.is_realsense(self.source) else "")

    # ---------------- 반복 ----------------
    def run(self):
        period = 1.0 / FPS
        while True:
            t0 = time.time()
            try:
                frame = self.read()
                self.frozen = self.cap is not None and self._is_frozen(frame)
                camera = self.cap is not None and not self.frozen      # 진짜 카메라 영상인가
                if camera:
                    self.frame_size = [int(frame.shape[1]), int(frame.shape[0])]
                    if self.cap is not None and not hasattr(self.cap, "info") and not getattr(self, "cam_info", None):
                        try:
                            self.cam_info = {"name": "웹캠", "fps": round(self.cap.get(cv2.CAP_PROP_FPS) or 0)}
                        except Exception:
                            self.cam_info = None
                fake = demo_mode.dets(self.key, frame)                 # 시연 모드: 가짜 검출 (없으면 None)
                self.tick = getattr(self, "tick", 0) + 1
                skip = getattr(self, "slow", 0) and self.tick % (self.slow + 1) and fake is None
                if camera and skip:
                    # 자동 조절(부하가 높을 때): 이번 프레임은 분석을 건너뛰고 화면만 (안전 카메라는 건너뛰지 않음)
                    frame = CameraWorker.draw(self, frame, getattr(self, "last_dets", []), {})
                    result = None
                elif camera or fake is not None:
                    dets = (self.detect(frame) if camera else []) + (fake or [])
                    self.last_dets = dets
                    result = self.judge(frame, dets)
                    frame = self.draw(frame, dets, result)
                    if not camera:
                        cv2.putText(frame, "DEMO (no camera)", (10, frame.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (68, 181, 245), 2)
                else:
                    # 카메라 없음 / 멈춘 화면: 판정은 '아무것도 안 보임'으로, 화면은 회색 NO CAMERA (박스 없음)
                    result = self.judge(frame, [])
                    frame = self._placeholder("no signal - frozen image (virtual camera?)" if self.frozen else "")
                if result is not None:
                    state.update(self.key, **result, dummy=self.model is None, camera=camera, demo=fake is not None)
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                if ok:
                    state.set_frame(self.key, jpg.tobytes())
                now = time.time()                           # 실제 처리 속도(이동 평균)
                lm = (now - t0) * 1000
                self.loop_ms = lm if not getattr(self, "loop_ms", 0) else 0.85 * self.loop_ms + 0.15 * lm
                if getattr(self, "last_ts", 0):
                    self.fps = 0.9 * getattr(self, "fps", 0.0) + 0.1 / max(1e-3, now - self.last_ts)
                self.last_ts = now
                new = result.get("status") if result is not None else self.status
                if new != self.status:
                    if self.status is not None:
                        self.on_change(self.status, new, result)
                    self.status = new
            except Exception as e:                      # 한 프레임 오류로 워커가 죽지 않게
                print(f"[{self.key}] 오류: {e}")
                self.last_error = f"{time.strftime('%H:%M:%S')} {e}"[:200]
                time.sleep(1)
            time.sleep(max(0.0, period - (time.time() - t0)))


# ======================================================================
# 자동 조절 (10/07): CPU가 모자라 안전 카메라가 느려지면, 품질 → 게이트 순서로 분석을 건너뛰게 해서
#   안전 카메라(프레스 인터록)가 항상 목표 FPS에 가깝게 돌도록 한다. 끄기: config.py AUTO_BALANCE = False
#   slow = 0: 매 프레임 분석 / 1: 2프레임에 1번 / 2: 3프레임에 1번 (화면은 계속 나옴)
# ======================================================================
def balance_once(workers):
    if not getattr(config, "AUTO_BALANCE", True):
        for w in workers.values():
            w.slow = 0
        return
    s = workers.get("safety")
    if not s or s.cap is None or getattr(s, "frozen", False):
        for k in ("quality", "gate"):          # 안전 카메라가 없으면 조절할 이유 없음
            if k in workers:
                workers[k].slow = 0
        return
    fps = getattr(s, "fps", 0.0)
    order = [workers[k] for k in ("quality", "gate") if k in workers]
    if fps < FPS * 0.8:                        # 안전 카메라가 느림 → 하나씩 더 건너뛰게
        for w in order:
            if getattr(w, "slow", 0) < 2:
                w.slow = getattr(w, "slow", 0) + 1
                break
    elif fps > FPS * 0.95:                     # 여유 → 게이트부터 원래대로
        for w in reversed(order):
            if getattr(w, "slow", 0) > 0:
                w.slow -= 1
                break


def start_balancer(workers):
    def loop():
        while True:
            time.sleep(3)
            try:
                balance_once(workers)
            except Exception as e:
                print(f"[balance] {e}")
    threading.Thread(target=loop, daemon=True, name="balance").start()
