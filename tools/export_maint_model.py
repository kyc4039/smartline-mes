"""설비 보전 모델을 학습 폴더(EM_model)에서 web/model_files/maintenance 로 복사 (처음 한 번만, 모델을 다시 학습했을 때도)

실행 (EM_model의 가상환경으로):
  cd D:\\EM_model
  uv run python web/tools/export_maint_model.py

하는 일
  1) EM_model/models 에서 판정에 필요한 것만 복사: v5_final.json · v5_baseline · v5_bilstm · v5_klue
  2) KLUE 구조(config.json)를 v5_klue 폴더에 저장 → 이후 인터넷 · 허깅페이스 캐시 없이 동작
  3) 확인: 학습 폴더의 src/predict.py 결과와 web 폴더 분류기 결과를 같은 문장 4개로 비교 (글자 그대로 같아야 정상)
"""
import os
import shutil
import subprocess
import sys
import time

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WEB)
import config  # noqa: E402

SRC = os.path.join(config.EM_MODEL_DIR, "models")
import maint_model  # noqa: E402
DST = maint_model.MODELS
NEED = ["v5_final.json", "v5_baseline", "v5_bilstm", "v5_klue"]


def size(p):
    if os.path.isfile(p):
        return os.path.getsize(p)
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)


def main():
    print(f"학습 폴더 모델: {SRC}\n복사할 곳:     {DST}\n")
    miss = [n for n in NEED if not os.path.exists(os.path.join(SRC, n))]
    if miss:
        print(f"■ 학습 폴더에 없음: {miss} → config.py EM_MODEL_DIR 확인")
        sys.exit(1)
    os.makedirs(DST, exist_ok=True)
    total = 0
    for n in NEED:
        s, d = os.path.join(SRC, n), os.path.join(DST, n)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        total += size(d)
        print(f"  ● {n:<16} {size(d) / 1e6:8.1f} MB")
    print(f"  합계 {total / 1e6:.1f} MB\n")

    # KLUE 구조 저장 (이 PC의 허깅페이스 캐시에서 · 없으면 인터넷에서 한 번 받음)
    import json
    kd = os.path.join(DST, "v5_klue")
    with open(os.path.join(kd, "meta.json"), encoding="utf-8") as f:
        name = json.load(f)["model_name"]
    from transformers import AutoConfig
    AutoConfig.from_pretrained(name).save_pretrained(kd)
    print(f"  ● KLUE 구조 저장: {name} → v5_klue/config.json (이제 인터넷 없이 동작)\n")

    # 확인 1: web 폴더 분류기
    t0 = time.time()
    new = [maint_model.line(t, maint_model.classify(t)) for t in maint_model.SAMPLES]
    print(f"web 폴더 분류기: 불러오기 {maint_model.INFO['load_sec']}초 · 모델별 {maint_model.INFO['models']}")
    print(f"  (전체 {time.time() - t0:.1f}초)\n")

    # 확인 2: 학습 폴더 predict.py (따로 실행해서 비교)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", TF_CPP_MIN_LOG_LEVEL="2")
    r = subprocess.run([sys.executable, os.path.join("src", "predict.py")], cwd=config.EM_MODEL_DIR,
                       capture_output=True, text=True, encoding="utf-8", env=env)
    old_lines = [l for l in r.stdout.splitlines() if l.strip()]
    ok = True
    for blk in new:
        t, res = blk.split("\n")
        try:
            i = old_lines.index(t)
            old = old_lines[i + 1]
        except (ValueError, IndexError):
            old = "(학습 폴더 결과를 못 읽음)"
        same = old.strip() == res.strip()
        ok &= same
        print(f"{'●' if same else '■'} {t}\n    web   {res.strip()}\n    학습  {old.strip()}")
    if r.returncode != 0:
        print("\n학습 폴더 predict.py 실행 오류:\n" + r.stderr[-800:])
    mark = os.path.join(DST, "VERIFIED.txt")
    if ok:      # 확인 표시가 있을 때만 서버가 web 폴더 모델을 씀 (다르면 계속 학습 폴더 모델)
        with open(mark, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " 학습 폴더 predict.py와 결과 일치 확인\n")
    elif os.path.exists(mark):
        os.remove(mark)
    print("\n결과:", "● 두 결과가 똑같아요. 이제 서버를 다시 켜면 web 폴더 모델을 써요."
          if ok else "▲ 다른 줄이 있어요. 서버는 계속 학습 폴더 모델을 써요. 위 내용을 캡처해서 보내 주세요.")


if __name__ == "__main__":
    main()
