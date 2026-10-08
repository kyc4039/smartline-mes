"""새 PC 환경 점검 (10/07) — web 폴더에서:  uv run python tools/check_env.py

확인하는 것
  1) 파이썬 · 라이브러리 버전
  2) 모델 파일 위치 (YOLO 3개 · 설비 보전 모델)
  3) YOLO 모델 3개를 실제로 불러와서 클래스 이름 확인
  4) 설비 보전 분류기를 불러와서 문장 4개 판정
     → 모델을 만든 버전과 지금 버전이 달라 경고 · 오류가 나면 "이 버전으로 맞추세요" 명령을 알려 줌
  5) 웹캠 번호 0~4 (열리는지 · 해상도)
"""
import json
import os
import sys
import time
import warnings
import zipfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
OK, WARN, BAD = "●", "▲", "■"
fixes = []


def ver(name):
    from importlib.metadata import version, PackageNotFoundError
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def head(t):
    print(f"\n── {t} " + "─" * max(0, 50 - len(t)))


def main():
    import config
    head("1. 파이썬 · 라이브러리")
    print(f"  {OK} Python {sys.version.split()[0]}")
    for n in ["flask", "numpy", "opencv-python", "ultralytics", "torch", "transformers", "tensorflow", "keras",
              "scikit-learn", "joblib", "kiwipiepy", "psutil"]:
        v = ver(n)
        print(f"  {OK if v else BAD} {n:<14} {v or '설치 안 됨 → uv sync 다시'}")

    head("2. 모델 파일 위치")
    for k, c in config.CAMERAS.items():
        p = os.path.join(config.MODEL_DIR, c["model"]) if c.get("model") else None
        print(f"  {OK if p and os.path.exists(p) else BAD} {k:<8} {p}")
    import maint_model
    md = maint_model.MODELS
    need = ["v5_final.json", "v5_baseline/baseline.joblib", "v5_bilstm/bilstm.keras", "v5_bilstm/meta.json",
            "v5_klue/model.pt", "v5_klue/meta.json", "v5_klue/config.json", "VERIFIED.txt"]
    for n in need:
        ex = os.path.exists(os.path.join(md, n))
        print(f"  {OK if ex else BAD} 설비 보전 {n}")
    if not os.path.exists(os.path.join(md, "VERIFIED.txt")):
        print(f"  {WARN} VERIFIED.txt가 없으면 서버가 이 폴더 모델을 안 씀 → 교육 PC의 web/model_files/maintenance 폴더를 통째로 복사")

    head("3. YOLO 모델 (클래스 이름)")
    try:
        from ultralytics import YOLO
        for k, c in config.CAMERAS.items():
            p = os.path.join(config.MODEL_DIR, c["model"])
            if not os.path.exists(p):
                print(f"  {BAD} {k}: 파일 없음")
                continue
            t = time.time()
            m = YOLO(p)
            print(f"  {OK} {k:<8} {list(m.names.values())}  ({time.time() - t:.1f}초)")
    except Exception as e:
        print(f"  {BAD} YOLO 불러오기 실패: {e}")

    head("4. 설비 보전 분류기")
    try:   # 모델을 만든 Keras 버전 (bilstm.keras 안의 metadata.json)
        with zipfile.ZipFile(os.path.join(md, "v5_bilstm", "bilstm.keras")) as z:
            kv = json.loads(z.read("metadata.json")).get("keras_version")
        now = ver("keras")
        print(f"  {OK if kv and now and kv.split('.')[0] == now.split('.')[0] else WARN} BiLSTM: 만든 Keras {kv} · 지금 {now}")
    except Exception as e:
        print(f"  {WARN} BiLSTM 버전 확인 못 함: {e}")
    if maint_model.available() or os.path.exists(os.path.join(md, "v5_final.json")):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                t = time.time()
                maint_model.load()
                print(f"  {OK} 불러오기 {time.time() - t:.1f}초 · {maint_model.INFO['models']} · KLUE 인터넷 없이: {maint_model.INFO['klue_offline']}")
                for s in maint_model.SAMPLES:
                    print("  " + maint_model.line(s, maint_model.classify(s)).replace("\n", "\n  "))
            except Exception as e:
                print(f"  {BAD} 불러오기 실패: {e}")
                msg = str(e)
                if "sklearn" in msg or "scikit" in msg:
                    fixes.append("scikit-learn 버전 문제 → 교육 PC에서 버전 확인: uv pip show scikit-learn")
                if "keras" in msg.lower() or "tensorflow" in msg.lower():
                    fixes.append("TensorFlow/Keras 버전 문제 → 교육 PC에서: uv pip show tensorflow keras")
            for x in w:      # scikit-learn: "Trying to unpickle estimator ... from version 1.5.2 when using version 1.7.2"
                m = str(x.message)
                if "unpickle" in m and "from version" in m:
                    old = m.split("from version")[1].split()[0]
                    fixes.append(f"scikit-learn을 모델 만든 버전으로:  uv add scikit-learn=={old}")
        print(f"  {WARN if fixes else OK} 결과는 교육 PC의 export_maint_model.py 결과와 같아야 정상 (확률까지)")
    else:
        print(f"  {BAD} 설비 보전 모델 없음 → 서버는 더미 분류기로 동작")

    head("5. 웹캠 번호")
    import cv2
    api = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    for i in range(5):
        cap = cv2.VideoCapture(i, api)
        ok, img = (cap.read() if cap.isOpened() else (False, None))
        cap.release()
        print(f"  {OK if ok else '○'} {i}번: " + (f"{img.shape[1]}×{img.shape[0]}" if ok else "없음"))
    use = {k: c["source"] for k, c in config.CAMERAS.items()}
    print(f"  config.py: {use}  → 맞는 번호인지 확인 (서버 켠 뒤 시스템 점검 > 카메라 번호 찾기에서 썸네일로)")

    head("결과")
    if fixes:
        for f in dict.fromkeys(fixes):
            print(f"  {WARN} {f}")
        print("  고친 뒤 이 점검을 다시 실행하세요.")
    else:
        print(f"  {OK} 문제 없음 → run.bat (또는 uv run app.py) 로 서버 실행 → http://localhost:5000")


if __name__ == "__main__":
    main()
