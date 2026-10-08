"""web/pyproject.toml 의 라이브러리 버전을 '지금 잘 돌아가는 환경'과 똑같이 고정 (10/07)

왜: 설비 보전 모델 파일(baseline.joblib · bilstm.keras)은 학습할 때의 scikit-learn · TensorFlow 버전과 다르면
    안 열리거나 경고가 날 수 있다. 새 PC에서 uv sync 할 때 같은 버전이 깔리도록 고정한다.

실행 (지금 서버를 돌리는 환경으로):
  cd D:\\EM_model
  uv run python web/tools/make_pyproject.py
그다음 (같은 PC에서 확인하거나 다른 PC로 옮긴 뒤):
  cd <web 폴더> ; uv sync ; uv run app.py
"""
import os
import sys
from importlib.metadata import version, PackageNotFoundError

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (pyproject에 쓸 이름, 이 환경에서 찾아볼 설치 이름들, 없을 때 기본 조건)
PKGS = [
    ("flask", ["flask"], ">=3.0"),
    ("numpy", ["numpy"], ">=1.26"),
    ("opencv-python", ["opencv-python", "opencv-contrib-python", "opencv-python-headless"], ">=4.9"),
    ("ultralytics", ["ultralytics"], ">=8.3"),
    ("torch", ["torch"], ">=2.3"),
    ("torchvision", ["torchvision"], None),          # ultralytics가 씀 · torch와 짝이 맞아야 함
    ("transformers", ["transformers"], ">=4.44"),
    ("tensorflow", ["tensorflow", "tensorflow-cpu", "tensorflow-intel"], ">=2.16"),
    ("keras", ["keras"], None),                      # bilstm.keras 형식 (Keras 3)
    ("scikit-learn", ["scikit-learn"], ">=1.4"),
    ("joblib", ["joblib"], ">=1.3"),
    ("kiwipiepy", ["kiwipiepy"], ">=0.18"),
    ("psutil", ["psutil"], ">=5.9"),
]


def found(names):
    for n in names:
        try:
            return n, version(n)
        except PackageNotFoundError:
            continue
    return None, None


def main():
    deps, notes = [], []
    for name, cands, default in PKGS:
        dist, v = found(cands)
        if v:
            pub = v.split("+")[0]                # 2.5.1+cu121 → 2.5.1 (CUDA 표시는 빼고 같은 버전)
            if "+" in v:
                notes.append(f"{name} {v}: GPU용(CUDA) 빌드였어요 → 새 PC에는 CPU용 {pub}이 깔려요 (GPU가 필요하면 말씀하세요)")
            if dist != name and name == "tensorflow" and dist == "tensorflow-intel":
                dist = "tensorflow"              # 윈도우 옛 버전은 tensorflow가 tensorflow-intel을 깔아 줌
            deps.append(f'    "{dist}=={pub}",')
            print(f"  ● {dist:<24} {v}")
        elif default:
            deps.append(f'    "{name}{default}",')
            print(f"  ▲ {name:<24} 이 환경에 없음 → {default} 로 둠")
    rs_dist, rs_v = found(["pyrealsense2", "pyrealsense2-macosx"])
    rs = f'pyrealsense2=={rs_v.split("+")[0]}' if rs_dist == "pyrealsense2" and rs_v else "pyrealsense2>=2.55"
    if rs_v:
        print(f"  ● {rs_dist:<24} {rs_v} (realsense 선택 설치)")
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    text = f'''# SMART LINE MES — web 폴더 단독 실행 환경
#   이 파일은 tools/make_pyproject.py 가 '잘 돌아가던 환경'의 버전으로 만들었음 (Python {py})
#   처음:      web 폴더에서  uv sync                    → web/.venv 생성 (몇 분 · 2~3GB)
#   RealSense: web 폴더에서  uv sync --extra realsense
#   실행:      web 폴더에서  uv run app.py              → http://localhost:5000
[project]
name = "smartline-web"
version = "1.0.0"
description = "SMART LINE MES 관제 웹 (Flask + YOLO 카메라 3대 + 설비 보전 AI 분류기)"
requires-python = ">={py},<{sys.version_info.major}.{sys.version_info.minor + 1}"
dependencies = [
{chr(10).join(deps)}
]

[project.optional-dependencies]
realsense = [
    "{rs}; sys_platform == 'win32' or (sys_platform == 'linux' and platform_machine == 'x86_64')",
]

[tool.uv]
package = false          # 설치할 패키지가 아니라 실행하는 앱
'''
    with open(os.path.join(WEB, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(WEB, ".python-version"), "w", encoding="utf-8") as f:
        f.write(py + "\n")
    print(f"\n저장: {os.path.join(WEB, 'pyproject.toml')}  (+ .python-version = {py})")
    for n in notes:
        print("  ▲ " + n)
    print("\n다음: web 폴더로 가서  uv sync  →  uv run app.py")


if __name__ == "__main__":
    main()
