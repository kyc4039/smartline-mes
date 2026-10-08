"""SMART LINE MES 서버 시작

실행 (이 폴더에서):
  uv sync          처음 한 번 (가상환경 .venv 생성)
  uv run app.py    →  http://localhost:5000  (포트는 config_local.py의 PORT로 바꿈)
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
import db
import config
from config import CAMERAS
from state import workers
from rules import RuleEngine
from modules import core, gate, quality, safety, maintenance

CAMERA_MODULES = {"gate": gate, "quality": quality, "safety": safety}   # 수신호(gesture)는 제거: 프레스는 5초 비움 자동 재가동
PORT = int(os.environ.get("PORT", getattr(config, "PORT", 5000)))


def create_app():
    app = Flask(__name__)
    app.json.ensure_ascii = False
    for m in (core, gate, quality, safety, maintenance):
        app.register_blueprint(m.bp)
    return app


def start_workers():
    for key, mod in CAMERA_MODULES.items():
        cfg = CAMERAS[key]
        workers[key] = mod.Worker(key, cfg["source"], cfg["model"])
        workers[key].start()
    RuleEngine().start()


if __name__ == "__main__":
    db.init()
    start_workers()
    # use_reloader=False: 자동 재시작 기능이 켜지면 카메라 워커가 두 번 실행되어 카메라 충돌이 남
    create_app().run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
