"""다른 컴퓨터로 옮길 web 폴더 압축 (10/07)

실행 (web 폴더에서):  uv run python tools/pack_web.py            → web 옆에 SmartLine_web_날짜.zip
                      uv run python tools/pack_web.py --db       → 지금까지 쌓인 기록(smartline.db)도 같이
빼는 것: .venv(새 PC에서 uv sync로 다시 만듦) · __pycache__ · 불량/안전 스냅샷 사진 · (기본) DB
새 PC에서:  압축 풀기 → web 폴더에서  uv sync  →  uv run app.py
"""
import os
import sys
import time
import zipfile

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".venv", "__pycache__", ".git", "safety_snaps", "defect_images", ".pytest_cache"}


def main():
    with_db = "--db" in sys.argv
    out = os.path.join(os.path.dirname(WEB), f"SmartLine_web_{time.strftime('%m%d_%H%M')}.zip")
    n = size = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(WEB):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith((".pyc", ".db-journal", ".db-wal", ".db-shm")) or (f.endswith(".db") and not with_db):
                    continue
                p = os.path.join(root, f)
                z.write(p, os.path.join("web", os.path.relpath(p, WEB)))
                n += 1
                size += os.path.getsize(p)
    print(f"● {out}\n  파일 {n}개 · 원본 {size / 1e6:.0f} MB → 압축 {os.path.getsize(out) / 1e6:.0f} MB"
          + ("" if with_db else "\n  (기록 DB는 뺐어요. 같이 옮기려면 --db)"))
    print("\n새 PC: 압축 풀기 → web 폴더에서  uv sync  →  uv run app.py")


if __name__ == "__main__":
    main()
