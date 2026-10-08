"""Intel RealSense 카메라 (D415 · D435 · D455 등)를 일반 웹캠처럼 쓰기 위한 어댑터

왜 필요한가
  RealSense는 웹캠처럼 cv2.VideoCapture(번호)로도 열리지만 그러면 640×480 기본 화질로 나오고,
  여러 대를 꽂으면 번호가 섞인다. 전용 라이브러리 pyrealsense2로 열면
  - 원하는 해상도(1280×720 · 1920×1080)로 컬러 영상을 받고
  - 시리얼 번호로 '어느 카메라가 어느 기능인지' 고정할 수 있다.
사용 (config.py의 CAMERAS 'source')
  "realsense"               연결된 RealSense 중 아직 안 쓴 첫 번째
  "realsense:123456789012"  시리얼 번호로 지정 (여러 대일 때 추천)
  시리얼 번호 확인: uv run python web/realsense.py
설정 (config.py에 없으면 기본값)
  REALSENSE_SIZE = (1280, 720)   # 컬러 해상도. D435 컬러는 1920×1080 · 1280×720 · 848×480 · 640×480 지원
  REALSENSE_FPS = 30             # 6 · 15 · 30 (해상도에 따라 가능한 값이 다름)
  REALSENSE_DEPTH = False        # True면 깊이 영상도 같이 받음 (worker.depth_at(x, y)로 거리(m) 확인)
설치
  uv pip install pyrealsense2     (Windows · Linux. Mac은 pyrealsense2-macosx)
  + 카메라는 USB 3 포트(파란색)에 꽂아야 고해상도가 나옴
"""
import threading
import numpy as np
import config

SIZE = tuple(getattr(config, "REALSENSE_SIZE", (1280, 720)))
FPS = int(getattr(config, "REALSENSE_FPS", 30))
DEPTH = bool(getattr(config, "REALSENSE_DEPTH", False))

_used = set()                 # 이미 다른 워커가 연 시리얼 번호
_lock = threading.Lock()
_said = set()                 # 같은 오류를 5초마다 반복 출력하지 않도록


def _log(msg):
    if msg not in _said:
        _said.add(msg)
        print(f"[realsense] {msg}")


def is_realsense(source):
    return isinstance(source, str) and source.lower().startswith("realsense")


def devices():
    """연결된 RealSense 목록 [(이름, 시리얼, USB 종류)]"""
    import pyrealsense2 as rs
    out = []
    for d in rs.context().query_devices():
        info = lambda k: d.get_info(k) if d.supports(k) else ""
        out.append((info(rs.camera_info.name), info(rs.camera_info.serial_number), info(rs.camera_info.usb_type_descriptor)))
    return out


class RealSenseCapture:
    """cv2.VideoCapture와 같은 모양 (isOpened · read · set · release) → camera_worker가 그대로 사용"""

    def __init__(self, source):
        self.pipe, self.serial, self.error, self.depth = None, None, "", None
        self.kind, self.fmt, self.size, self.info = "color", None, None, None
        self.align = None
        try:
            import pyrealsense2 as rs
        except ImportError:
            self.error = "pyrealsense2가 설치되지 않음 (uv pip install pyrealsense2)"
            _log(self.error)
            return
        want = source.split(":", 1)[1].strip() if ":" in source else None
        with _lock:
            serials = [s for _, s, _ in devices()]
            if want:
                serial = want if want in serials else None
            else:
                serial = next((s for s in serials if s not in _used), None)
            if not serial:
                self.error = f"RealSense를 찾지 못함 (요청: {want or '아무거나'}, 연결됨: {serials or '없음'})"
                _log(self.error)
                return
            _used.add(serial)
        self.serial = serial
        self.kind = "color"            # 컬러가 없는 모델(D401·D421 등)은 "ir"(흑백 적외선)
        try:
            dev = next(d for d in rs.context().query_devices() if d.get_info(rs.camera_info.serial_number) == serial)
            name = dev.get_info(rs.camera_info.name)
            usb = dev.get_info(rs.camera_info.usb_type_descriptor) if dev.supports(rs.camera_info.usb_type_descriptor) else "?"
            plan = self._plan(rs, dev)
        except Exception as e:
            self._fail(f"RealSense 정보 읽기 실패: {e}")
            return
        if not plan:
            self._fail(f"{name}: 쓸 수 있는 컬러·적외선 영상이 없음 (USB {usb})")
            return
        last = None
        for kind, w, h, fps, fmt in plan[:6]:          # 좋은 설정부터 차례로 시도
            try:
                cfg = rs.config()
                cfg.enable_device(serial)
                if kind == "color":
                    cfg.enable_stream(rs.stream.color, w, h, fmt, fps)
                else:
                    cfg.enable_stream(rs.stream.infrared, 1, w, h, fmt, fps)
                use_depth = DEPTH and kind == "color"
                if use_depth:
                    cfg.enable_stream(rs.stream.depth, rs.format.z16, fps)
                self.pipe = rs.pipeline()
                self.pipe.start(cfg)
                self.kind, self.fmt = kind, fmt
                self.align = rs.align(rs.stream.color) if use_depth else None
                self.size = (w, h)
                self.info = {"name": name, "serial": serial, "usb": usb, "size": [w, h], "fps": fps, "kind": kind,
                             "wanted": [SIZE[0], SIZE[1], FPS]}
                warn = ""
                if (w, h, fps) != (SIZE[0], SIZE[1], FPS):
                    warn = f"  (요청 {SIZE[0]}×{SIZE[1]}@{FPS}는 이 연결에서 안 됨" + (" — USB 2로 연결됨, 파란 USB 3 포트에 꽂으면 고해상도 가능" if usb.startswith("2") else "") + ")"
                print(f"[realsense] {name} ({serial}) USB {usb} · {'컬러' if kind == 'color' else '적외선(흑백)'} {w}×{h} @{fps}fps"
                      + (" + 깊이" if use_depth else "") + warn)
                return
            except Exception as e:
                last = e
                try:
                    self.pipe.stop()
                except Exception:
                    pass
                self.pipe = None
        self._fail(f"{name} 시작 실패 (USB {usb}): {last}")

    def _plan(self, rs, dev):
        """이 카메라가 실제로 지원하는 영상 목록에서 요청(REALSENSE_SIZE·FPS)에 가장 가까운 순서로 정렬"""
        ok_fmt = {rs.format.bgr8: 0, rs.format.rgb8: 1, rs.format.yuyv: 2}
        color, ir = set(), set()
        for sen in dev.query_sensors():
            for p in sen.get_stream_profiles():
                try:
                    v = p.as_video_stream_profile()
                except Exception:
                    continue
                if p.stream_type() == rs.stream.color and p.format() in ok_fmt:
                    color.add((v.width(), v.height(), p.fps(), p.format()))
                elif p.stream_type() == rs.stream.infrared and p.format() == rs.format.y8 and p.stream_index() in (0, 1):
                    ir.add((v.width(), v.height(), p.fps(), p.format()))
        area = SIZE[0] * SIZE[1]

        def key(t):
            w, h, fps, fmt = t
            return ((w, h, fps) == (SIZE[0], SIZE[1], FPS),   # 요청과 똑같은 것
                    w * h <= area,                             # 요청보다 크지 않은 것
                    fps >= min(FPS, 15),                       # 너무 느리지 않은 것
                    w * h, -abs(fps - FPS), -ok_fmt.get(fmt, 9))
        out = [("color",) + t for t in sorted(color, key=key, reverse=True)]
        out += [("ir",) + t for t in sorted(ir, key=key, reverse=True)]
        return out

    def _fail(self, msg):
        self.error = msg
        _log(msg)
        self.pipe = None
        with _lock:
            _used.discard(self.serial)

    def isOpened(self):
        return self.pipe is not None

    def read(self):
        if self.pipe is None:
            return False, None
        try:
            frames = self.pipe.wait_for_frames(1000)          # 1초 안에 안 오면 이번 프레임은 건너뜀 (워커가 마지막 화면 유지)
            if self.align is not None:
                frames = self.align.process(frames)
                d = frames.get_depth_frame()
                self.depth = d if d else None
            c = frames.get_color_frame() if self.kind == "color" else frames.get_infrared_frame(1)
            if not c:
                return False, None
            img = np.asanyarray(c.get_data())
            import cv2
            import pyrealsense2 as rs
            if self.kind == "ir":
                return True, cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            if self.fmt == rs.format.rgb8:
                return True, cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            if self.fmt == rs.format.yuyv:
                return True, cv2.cvtColor(img, cv2.COLOR_YUV2BGR_YUYV)
            return True, img.copy()
        except Exception as e:
            self.error = str(e)[:200]
            return False, None

    def depth_at(self, x, y):
        """컬러 화면 (x, y) 픽셀까지의 거리(m). 깊이를 안 켰거나 값이 없으면 None"""
        try:
            v = self.depth.get_distance(int(x), int(y)) if self.depth is not None else 0
            return v or None
        except Exception:
            return None

    def set(self, *_):
        return False

    def release(self):
        try:
            if self.pipe is not None:
                self.pipe.stop()
        except Exception:
            pass
        self.pipe = None
        with _lock:
            _used.discard(self.serial)


if __name__ == "__main__":
    # 연결된 RealSense 시리얼 번호 확인용:  uv run python web/realsense.py
    try:
        ds = devices()
    except ImportError:
        print("pyrealsense2가 없습니다 →  uv pip install pyrealsense2")
        raise SystemExit(1)
    if not ds:
        print("연결된 RealSense가 없습니다 (USB 3 포트 · 케이블 확인, Intel RealSense Viewer로도 확인 가능)")
    for name, serial, usb in ds:
        print(f"{name}  시리얼 {serial}  USB {usb}" + ("  ← USB 2로 연결됨: 고해상도가 안 나올 수 있음" if usb.startswith("2") else ""))
        try:
            import pyrealsense2 as rs
            dev = next(d for d in rs.context().query_devices() if d.get_info(rs.camera_info.serial_number) == serial)
            modes = sorted({(w, h, f) for k, w, h, f, _ in RealSenseCapture._plan(None, rs, dev) if k == "color"}, reverse=True)
            print("   컬러 지원:", ", ".join(f"{w}×{h}@{f}" for w, h, f in modes[:12]) or "없음 (적외선 흑백으로 사용)")
        except Exception as e:
            print("   지원 목록 읽기 실패:", e)
        print(f'   config.py 예:  "quality": {{"source": "realsense:{serial}", "model": "quality/best.pt"}},')
