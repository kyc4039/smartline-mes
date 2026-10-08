# SMART LINE MES

AI가 작업자를 지키고, 제품을 검사하고, 고장 정비를 배정하는 작업라인 관제 웹입니다.
비전 AI 3종(안전게이트 · 프레스 안전 · 품질검사)과 자연어 AI 1종(설비보전)을 Flask MES 하나로 묶었습니다.

| 담당 | 기능 | 모델 |
|---|---|---|
| 김태원 | ① 안전게이트: 안전모 · 조끼 · 장갑 확인 후 입장 | YOLOv8n |
| 유장오 | ② 프레스 안전: 금형부에 손 · 공구가 들어오면 정지 | YOLO11s |
| 백임수 | ③ 품질검사: 캔 양품 / 흠집 / 찌그러짐 판정 | YOLOv8 |
| 김영창 | ④ 설비보전: 고장 보고 문장 → 담당 분야 · 조치 시점 + MES 통합 | KLUE 앙상블 |

모델 학습 기록은 [smartline-models](https://github.com/kyc4039/smartline-models) 저장소에 있습니다.

## 실행

[uv](https://docs.astral.sh/uv/getting-started/installation/)만 설치하면 됩니다 (파이썬도 uv가 받습니다).

```bash
git clone https://github.com/kyc4039/smartline-mes.git
cd smartline-mes
uv sync                     # 처음 한 번: .venv 생성 (몇 분 · 2~3GB)
cp config_local.example.py config_local.py    # Windows: copy config_local.example.py config_local.py
uv run app.py               # → http://localhost:5000
```

- 카메라나 모델 파일이 없어도 **더미 모드**로 모든 화면 · 디지털 트윈 · 시연 모드가 동작합니다.
- 맥은 AirPlay가 5000번 포트를 쓰는 경우가 많아 `config_local.py`에 `PORT = 5001`을 넣으세요.
- RealSense 카메라를 쓰면 `uv sync --extra realsense`.

## 모델 파일 (저장소에 없음)

가중치는 아직 개선 중이라 저장소에 올리지 않았습니다. 받은 파일을 아래 위치에 넣으면 실제 판정으로 바뀝니다.

```
model_files/
├── gate/best.pt          안전게이트
├── quality/best.pt       품질검사
├── safety/best.pt        프레스 안전
└── maintenance/          설비보전 (smartline-models에서 tools/export_maint_model.py로 복사)
```

설비보전 모델이 `model_files/maintenance`에 없으면 옆 폴더 `../smartline-models/maintenance`에서 불러오고,
그것도 없으면 더미 분류기로 동작합니다.

## 설정

| 파일 | 내용 | 깃 |
|---|---|---|
| `config.py` | 공통 기준값 (판정 구역 · 택트 · 정비 계획 등) | 올림 |
| `config_local.py` | PC마다 다른 값 (카메라 번호 · 관리자 PIN · SECRET_KEY · 포트) | **안 올림** |

`config_local.py`에 적은 값이 `config.py`를 덮어씁니다. 카메라 번호는 **시스템 점검 > 카메라 번호 찾기**에서 확인하세요.

## 화면

| 주소 | 화면 |
|---|---|
| `/` | 관제 대시보드 |
| `/twin` | 디지털 트윈 |
| `/gate` | 안전 게이트 (입장) |
| `/production` | 생산 관리 (LOT · 팔레트 · 트럭) |
| `/quality` | 품질 관리 |
| `/safety` | 설비 안전 제어 |
| `/maintenance` | 설비 보전 (고장 보고 · 정비 티켓) |
| `/oee` | 설비 종합 효율 |
| `/demo` | 시연 제어판 (어느 화면에서나 Shift+D 리모컨) |
| `/system` | 시스템 점검 (카메라 · 모델 · 발표 준비 점수) |
| `/timeline` · `/report` · `/feedback` | 타임라인 · 교대 보고서 · AI 학습 피드백 (메뉴에서는 숨김) |

## 폴더 구조

```
smartline-mes/
├── app.py                서버 시작
├── config.py             공통 설정
├── config_local.example.py   PC별 설정 예시
├── camera_worker.py · realsense.py · streaming.py   카메라 · 영상
├── db.py · state.py · rules.py                      DB · 공유 상태 · 모듈 간 연동 규칙
├── line_flow.py · production.py · demo_sim.py       제품 흐름 · 생산 장부 · 생산 시뮬레이터
├── *_info.py · analytics.py · incidents.py          화면별 데이터
├── maint_model.py        설비보전 분류기 (model_files/maintenance)
├── demo_mode.py          시연 모드
├── modules/              core · gate · quality · safety · maintenance (Flask 블루프린트)
├── templates/ · static/  화면 HTML · CSS · JS (디지털 트윈: static/twin.js)
├── tools/                점검 · 모델 복사 · 압축 도구
├── model_files/          모델 가중치 (깃에 없음)
└── docs/                 업데이트 기록
```

## 주의

- `app.py`의 `use_reloader=False`를 바꾸지 마세요. 자동 재시작이 켜지면 카메라 워커가 두 번 실행되어 카메라가 충돌합니다.
- `smartline.db`(기록)와 `safety_snaps/`(사진)는 실행하면 생기며 깃에 올리지 않습니다.
