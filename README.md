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

## 처음 실행하기 (코드를 몰라도 따라 할 수 있게)

> 처음 한 번만 1~5단계를 하면 되고, 다음부터는 **6단계(실행)**만 하면 됩니다.
> 명령어는 한 줄씩 복사해서 붙여넣고 Enter를 누르세요.

### 0. 터미널 열기

| 윈도우 | 맥 |
|---|---|
| 시작 메뉴에서 **PowerShell** 검색 → 실행 | Spotlight(⌘ + Space)에서 **터미널** 검색 → 실행 |

### 1. uv 설치 (파이썬 · 라이브러리 관리 도구)

파이썬을 따로 설치할 필요 없습니다. uv가 알아서 받습니다.

**윈도우 (PowerShell)**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**맥 (터미널)**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

설치가 끝나면 **터미널 창을 닫고 새로 연 다음** 아래를 입력해 버전이 나오면 성공입니다.
```bash
uv --version
```

### 2. 코드 내려받기

먼저 코드를 저장할 폴더를 정하고(예: `D:\projects`, `문서` 폴더 등) 터미널에서 그 폴더로 이동합니다.

```bash
cd 저장할_폴더_경로
```
예) 윈도우 `cd D:\projects` · 맥 `cd ~/Documents`

> **폴더 경로 쉽게 넣는 법**: `cd ` (cd와 띄어쓰기)까지 입력한 뒤, 탐색기(맥은 Finder)에서 그 폴더를 터미널 창으로 **끌어다 놓으면** 경로가 자동으로 입력됩니다.

**방법 A — git이 있으면** (`git --version`이 나오면 있는 것)
```bash
git clone https://github.com/kyc4039/smartline-mes.git
cd smartline-mes
```
> 윈도우에 git이 없으면 https://git-scm.com/download/win 에서 설치하거나 방법 B를 쓰세요.

**방법 B — git 없이**
1. 이 페이지 위쪽 초록색 **Code** 버튼 → **Download ZIP**
2. 정한 폴더에 압축을 풀고, 폴더 이름을 `smartline-mes`로 바꾸기
3. 터미널에서 그 폴더로 이동
```bash
cd smartline-mes
```

### 3. 라이브러리 설치 (처음 한 번 · 5~10분)

```bash
uv sync
```
torch · tensorflow 등을 받느라 시간이 걸립니다(약 2~3GB). 마지막에 오류 없이 끝나면 성공입니다.

### 4. 내 PC 설정 파일 만들기

**윈도우**
```powershell
copy config_local.example.py config_local.py
```
**맥**
```bash
cp config_local.example.py config_local.py
```
메모장(맥은 텍스트 편집기)으로 `config_local.py`를 열어 필요한 것만 고칩니다.
- `ADMIN_PIN`: 팀에서 정한 관리자 PIN (팀장에게 받기)
- `CAMERAS`: 카메라 번호 — 모르면 그대로 두고 실행 후 **시스템 점검 > 카메라 번호 찾기**로 확인
- 맥이면 `# PORT = 5001` 앞의 `# `를 지워서 켜기 (맥은 5000번을 AirPlay가 씀)

### 5. 모델 파일 넣기 (선택)

모델이 없어도 화면 · 디지털 트윈 · 시연은 모두 동작합니다(더미 모드). 실제 AI 판정을 하려면 팀 드라이브에서 받아 넣으세요.

| 받을 파일 | 넣을 위치 |
|---|---|
| 안전게이트 `best.pt` | `model_files/gate/best.pt` |
| 품질검사 `best.pt` | `model_files/quality/best.pt` |
| 프레스 안전 `best.pt` | `model_files/safety/best.pt` |
| `smartline_maintenance_model.zip` | `model_files/` 안에서 압축 풀기 → `model_files/maintenance/VERIFIED.txt`가 보이면 정상 |

### 6. 실행

```bash
uv run app.py
```
`Running on http://127.0.0.1:5000` 같은 글자가 나오면 브라우저(크롬 권장)에서 **http://localhost:5000** 접속 (맥에서 5001로 바꿨으면 5001).

- 첫 화면은 **안전 게이트**입니다. 카메라가 없으면 아래 **관리자 우회 입장**에 PIN을 넣고 들어가세요 (설정 안 했으면 `0000`).
- 끄기: 터미널에서 **Ctrl + C**
- 다음부터는 터미널에서 `smartline-mes` 폴더로 이동(`cd 저장한_폴더_경로/smartline-mes`) 후 `uv run app.py`만 하면 됩니다.

### 7. 최신 버전 받기

```bash
git pull
uv sync
```
(ZIP으로 받았다면 다시 내려받아 덮어쓰되, `config_local.py`와 `model_files/`는 옮겨 두세요.)

### 8. 시연용 기록 넣기 (발표 전 선택)

처음 실행하면 기록이 없어 OEE 7일 추이 · 정비 지표(MTTR · MTBF) · 요일 × 시간 지도가 비어 있습니다. 발표 전에 한 번 실행하면 최근 평일 7일치 기록이 채워집니다.

```bash
# 서버를 끈 상태(Ctrl + C)에서
uv run python tools/seed_demo_data.py
uv run app.py
```
- 기존 `smartline.db`는 `smartline.db.bak_날짜시각`으로 보관되고 새 DB가 만들어집니다. 되돌리려면 서버를 끄고 `smartline.db`를 지운 뒤 백업 파일 이름을 `smartline.db`로 바꾸세요.
- 오늘 기록은 교대 시작부터 실행 3분 전까지만 들어가고, 그 뒤는 카메라 · 시뮬레이터가 이어서 기록합니다. 발표 당일에 실행하는 것이 가장 자연스럽습니다.
- `--days 10` (평일 10일), `--no-today` (오늘은 비워 두기)

### 문제가 생기면

| 증상 | 해결 |
|---|---|
| `uv`를 찾을 수 없음 / 'uv' is not recognized | 터미널을 **닫고 새로 열기**. 그래도 안 되면 1단계 다시 |
| PowerShell에서 "스크립트를 실행할 수 없습니다" | 1단계 명령을 그대로(앞의 `powershell -ExecutionPolicy ByPass` 포함) 다시 실행 |
| `uv sync`가 오래 걸림 | 정상입니다 (처음 5~10분). 인터넷 연결 확인 |
| `Address already in use` / 포트 사용 중 | `config_local.py`에 `PORT = 5001` 넣고 다시 실행 |
| 화면에 `NO CAMERA` | 카메라 번호가 다름 → 시스템 점검 > 카메라 번호 찾기 → `config_local.py`의 `source` 수정 → 다시 실행 |
| 맥에서 카메라가 안 켜짐 | 시스템 설정 > 개인정보 보호 및 보안 > 카메라 → 터미널 허용 |
| 정비 AI가 전부 '정기 점검' | 설비보전 모델 없음 → 5단계 확인 (`model_files/maintenance/maintenance/`처럼 폴더가 두 번 생기지 않았는지) |
| `config_local.py`를 고쳤는데 그대로 | Ctrl + C로 끄고 `uv run app.py` 다시 실행 |

그래도 안 되면 터미널 화면 전체를 캡처해서 팀장에게 보내 주세요.

## 모델 파일 (저장소에 없음)

가중치는 아직 개선 중이라 저장소에 올리지 않습니다. 넣는 위치는 위 **5단계**와 [model_files/README.md](model_files/README.md)를 보세요.
설비보전 모델이 `model_files/maintenance`에 없으면 옆 폴더 `../smartline-models/maintenance`에서 찾고, 그것도 없으면 더미 분류기로 동작합니다.

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
