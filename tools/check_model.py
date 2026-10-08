"""팀원용: 내 모델 파일이 서버에서 쓸 수 있는 상태인지 확인
사용법 (EM_model 폴더에서):
  uv run python web/tools/check_model.py web/model_files/gate/best.pt          ← 클래스 이름 확인
  uv run python web/tools/check_model.py web/model_files/gate/best.pt 0        ← 웹캠 0번으로 실시간 확인 (q로 종료)
  uv run python web/tools/check_model.py web/model_files/gate/best.pt test.mp4 ← 테스트 영상으로 확인
"""
import sys
import cv2
from ultralytics import YOLO

if len(sys.argv) < 2:
    sys.exit(__doc__)
model = YOLO(sys.argv[1])
print("모델 불러오기 성공")
print("클래스 이름:", model.names)
print("→ 이 이름들을 web/modules/<기능>.py 상단의 클래스 이름 설정과 똑같이 맞춰 주세요.")

if len(sys.argv) >= 3:
    src = int(sys.argv[2]) if sys.argv[2].isdigit() else sys.argv[2]
    cap = cv2.VideoCapture(src)
    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break
        r = model(frame, conf=0.5, verbose=False)[0]
        cv2.imshow("check_model (q: 종료)", r.plot())
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()
