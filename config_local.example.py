"""PC별 설정 예시 — 이 파일을 config_local.py로 복사해서 고친다 (config_local.py는 깃에 올라가지 않음)

  macOS / Linux:  cp config_local.example.py config_local.py
  Windows:        copy config_local.example.py config_local.py

여기 적은 값만 config.py 값을 덮어씀. 필요 없는 줄은 지워도 됨.
"""

# 관리자 PIN · 세션 키 (팀 안에서만 공유)
ADMIN_PIN = "0000"
SECRET_KEY = "아무-긴-문자열로-바꾸기"

# 이 PC의 카메라 번호 (시스템 점검 > 카메라 번호 찾기로 확인 · 카메라가 없으면 None)
CAMERAS = {
    "gate":    {"source": 0, "model": "gate/best.pt"},
    "quality": {"source": None, "model": "quality/best.pt"},
    "safety":  {"source": None, "model": "safety/best.pt"},
}

# 맥이면 5001 (AirPlay가 5000을 씀)
# PORT = 5001

# 발표 날: 트럭이 더 자주 출발 (약 2분 45초)
# TRUCK_PALLETS = 4

# 설비 보전 학습 폴더가 다른 곳에 있으면
# EM_MODEL_DIR = r"D:\smartline-models\maintenance"
