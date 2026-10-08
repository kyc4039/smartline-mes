# model_files

AI 모델 가중치를 넣는 곳입니다. 가중치는 아직 개선 중이라 저장소에 올리지 않습니다 (`.gitignore`).

| 폴더 | 모델 | 담당 | 넣을 파일 |
|---|---|---|---|
| gate/ | ① 안전게이트 | 김태원 | best.pt |
| safety/ | ② 프레스 안전 | 유장오 | best.pt |
| quality/ | ③ 품질검사 | 백임수 | best.pt |
| maintenance/ | ④ 설비보전 | 김영창 | `uv run python tools/export_maint_model.py`로 복사 |

파일이 없으면 해당 기능은 더미 모드로 동작합니다.
