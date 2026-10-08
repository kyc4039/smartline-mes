"""공유 상태: 카메라 워커가 분석한 최신 결과와 영상을 담아 두는 현황판
여러 스레드가 동시에 읽고 쓰므로 잠금(lock)으로 보호한다.
"""
import copy
import threading
import time


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}      # {"gate": {...}, "quality": {...}, ...}
        self._frames = {}    # {"gate": jpeg bytes, ...}

    def update(self, key, **values):
        with self._lock:
            d = self._data.setdefault(key, {})
            d.update(values)
            d["updated"] = time.time()

    def get(self, key=None):
        with self._lock:
            return copy.deepcopy(self._data.get(key, {}) if key else self._data)

    def set_frame(self, key, jpeg):
        with self._lock:
            self._frames[key] = jpeg

    def get_frame(self, key):
        with self._lock:
            return self._frames.get(key)


state = SharedState()
workers = {}   # {"gate": GateWorker 객체, ...}  연동 규칙에서 다른 워커를 찾을 때 사용
