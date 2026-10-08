"""SMART LINE MES 공통 설정 — 팀원은 자기 기능 칸만 수정한다.  (10/08 · 교육장 최신 + 맥 라인 흐름 값 합침)

PC마다 다른 값(카메라 번호 · 관리자 PIN · SECRET_KEY)은 이 파일이 아니라 config_local.py에 적는다.
  → config_local.example.py를 config_local.py로 복사해서 고치기 (config_local.py는 깃에 올라가지 않음)
  → config_local.py에 적은 값이 이 파일의 값을 덮어씀

source: 웹캠 번호(0, 1, 2 …), 테스트 영상 파일 경로, 또는 None(카메라 끔)
        어느 번호가 어느 카메라인지는 시스템 점검 > 카메라 번호 찾기 (썸네일)로 확인
        노트북 내장 카메라가 있으면 보통 0번이 내장 카메라 → 외장 웹캠은 1, 2, 3
model : model_files/ 아래 모델 파일 경로 (없으면 '더미 모드'로 동작해서 화면은 뜬다)
        분석 크기를 줄이려면 "imgsz": 480 추가 (화면 해상도는 그대로, 추론만 빨라짐)
size  : (선택) 웹캠 해상도. 예: "size": (1280, 720). 없으면 카메라 기본값(보통 640×480)
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "smartline.db")
PORT = 5000             # 웹 주소 포트 (맥은 AirPlay가 5000을 쓰는 경우가 많아 config_local.py에서 5001로)
MODEL_DIR = os.path.join(BASE, "model_files")

# ---------------------------------------------------------------- 카메라 · 모델
CAMERAS = {
    "gate":    {"source": 0, "model": "gate/best.pt"},      # 김태원: 안전 게이트 (보호구 3종)
    "quality": {"source": 1, "model": "quality/best.pt"},   # 백임수: 품질 검사 (can · marked_can · crushed_can)
    "safety":  {"source": 2, "model": "safety/best.pt"},    # 유장오: 프레스 금형부 (hand · screwdriver · balldriver · spanner)
}
FPS = 10                 # 카메라 워커 분석 속도 (초당 프레임)
JPEG_QUALITY = 70        # 화면 전송 화질
CONF = 0.3               # YOLO 최소 확신도 — 낮을수록 잘 잡지만 오검출도 늘어남 (헛정지 · 헛불량이 잦으면 0.4~0.5)

# RealSense를 다시 쓰려면: source를 "realsense"로 + 아래 두 줄 (uv sync --extra realsense 필요)
# REALSENSE_SIZE = (1280, 720)
# REALSENSE_FPS = 15
# AUTO_BALANCE = True          # CPU가 모자라면 안전 카메라 우선 (품질 → 게이트 순서로 분석 횟수 줄임). 끄기 False

# ---------------------------------------------------------------- 품질 검사
DEFECT_WINDOW = 50       # 최근 몇 개로 불량률을 계산할지
DEFECT_RATE_LIMIT = 0.03 # 이 불량률을 넘으면 정비 요청 알림
QUALITY_ROI = (0.15, 0.10, 0.85, 0.90)  # 판정 구역 (화면 비율: 왼쪽, 위, 오른쪽, 아래) · 중심 0.5, 0.5
QUALITY_SETTLE_SEC = 1.0      # 캔이 이 시간 동안 결함 없이 보이면 '정상'
QUALITY_DEFECT_HOLD_SEC = 0.6 # 판정 구역 안에서 결함이 합계 이 시간 이상 보이면 '불량' (0.5~1초 권장)
QUALITY_LEAVE_SEC = 0.5       # 제품이 이 시간 동안 안 보여야 '빠졌다'고 봄 (깜빡임 방지)
PRODUCT_NAME = "캔 355ml"

# ---------------------------------------------------------------- 프레스 안전
SAFETY_ROI = (0.33, 0.27, 0.67, 0.73)        # 위험구역 (빨강): 들어오면 즉시 안전 정지
SAFETY_WARN_ROI = (0.14, 0.08, 0.86, 0.92)   # 경고구역 (노랑): 정지 없이 경고만
SAFETY_AUTO_RELEASE_SEC = 5.0   # 위험구역이 이 시간 동안 비면 자동 재가동 (비상 정지는 관리자 수동 재가동)
SAFETY_SINCE = "2026-09-25"     # 무재해 시작일 (없으면 DB 첫 기록 날짜)
SAFETY_GOAL_DAYS = 30
SAFETY_CHECKLIST = ["비상 정지 버튼 동작 확인", "위험구역 카메라 시야 · 조명 확인", "손 넣기 시험 → 정지 확인", "금형 고정 볼트 점검"]

# ---------------------------------------------------------------- 안전 게이트 · 관리자
GATE_HOLD_SEC = 2        # 보호구 3종이 이 시간 동안 계속 보여야 입장 (1~2초 권장)
ADMIN_PIN = "0000"       # 관리자 우회 입장 · 수동 재가동 · 시연 모드 PIN → 실제 PIN은 config_local.py에
SECRET_KEY = None        # 서버를 다시 켜도 입장 상태 유지 → config_local.py에 (없으면 켤 때마다 새로 만듦)

# ---------------------------------------------------------------- 생산 · 라인 흐름 (10/07 검사기 정지 방식)
FLOW_V2 = True             # 세 화면 같은 장부 · 검사기 정지 방식 (False = 예전 방식)
INSPECT_SEC = 4.0          # 상자가 비전 검사기에서 멈춰 검사하는 시간
TARGET_CYCLE_SEC = 5.0     # 제품 1개 = 검사 4초 + 이동 1초
PALLET_SIZE = 8            # 팔레트당 양품 수 (그림이 8칸이라 그대로)
TRUCK_PALLETS = 7          # 트럭 1대 팔레트 수 → 약 4분 45초마다 출발 (발표 날은 4 → 약 2분 45초)
SHIFT_START = "08:00"      # 교대 시작 (생산 계획 · OEE 기준)
SHIFT_END = "16:00"        # 교대 끝 (22:00~06:00 같은 야간 교대도 가능)
# WORK_ORDER = "WO-1006-01"  # 고정하고 싶을 때만. 없으면 날짜로 자동
OEE_TARGET = 0.75          # OEE 우리 목표 (세계 수준 85%는 고정)

# ---------------------------------------------------------------- 시연용 생산 시뮬레이터
DEMO_PRODUCTION = True     # 품질 카메라 기록이 DEMO_SILENT_SEC 동안 없으면 시연용 생산 기록 생성 (끄기 False)
DEMO_DEFECT_RATE = 0.03    # 시뮬레이터 불량 비율 (0이면 불량 없음)
DEMO_SILENT_SEC = 120      # 품질 카메라 기록이 이 시간 없으면 시뮬레이터가 이어받음

# ---------------------------------------------------------------- 설비 보전
PM_PLAN = [("프레스 #1", "금형 점검", 1), ("프레스 #1", "유압유 점검", 7), ("컨베이어", "벨트 장력", 3),
           ("로봇 적재기", "그리퍼 점검", 5), ("비전 검사기", "렌즈 청소", 7), ("자재 투입기", "롤러 윤활", 7)]   # (설비, 할 일, 며칠마다)
PM_START = "2026-10-01"    # 주기 계산 기준일
SHELF_REFILL = 1500        # 트윈 자재 선반 재고(추정): 보충 1회 수량
AMR_BATTERY_HOURS = 4.0    # 트윈 AMR 배터리(추정): 1회 충전 사용 시간
# 설비 보전 AI 분류기: model_files/maintenance 를 먼저 씀 (tools/export_maint_model.py로 복사 · 확인한 것)
# 거기 없으면 학습 폴더(옆의 smartline-models/maintenance)에서 불러옴 → 둘 다 없으면 더미 분류기
EM_MODEL_DIR = os.environ.get("EM_MODEL_DIR", os.path.join(os.path.dirname(BASE), "smartline-models", "maintenance"))
MAINT_SRC = os.path.join(EM_MODEL_DIR, "src")

# ---------------------------------------------------------------- 화면
# 메뉴에서 숨길 페이지 (주소로 직접 들어가면 열림). 이 줄이 없으면 기본: 타임라인 · 교대 보고서 · AI 학습 숨김
# HIDE_PAGES = ["timeline", "report", "feedback", "demo"]   # 시연 제어판 탭까지 청중에게 숨기기 (/demo 주소로는 열림)
# TWIN_FEATURES = ["layers", "sim", "replay"]               # 트윈 추가 기능 전부 (기본: 리플레이만)

EQUIPMENT = ["프레스 #1", "컨베이어", "로봇 적재기", "비전 검사기", "자재 투입기"]

# ---------------------------------------------------------------- PC별 설정 (맨 끝에서 덮어쓰기)
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
MAINT_SRC = os.path.join(EM_MODEL_DIR, "src")   # config_local.py에서 EM_MODEL_DIR을 바꿨을 때 같이 맞춤
