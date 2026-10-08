"""실시간 영상 전송 (MJPEG): 화면에서 <img src="/gate/video"> 한 줄로 표시"""
import time
from flask import Response
from config import FPS
from state import state


def mjpeg(key):
    """카메라가 없을 때는 워커가 만든 회색 'NO CAMERA' 화면이 그대로 전송된다"""
    def gen():
        while True:
            f = state.get_frame(key)
            if f:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + f + b"\r\n"
            time.sleep(1.0 / FPS)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
