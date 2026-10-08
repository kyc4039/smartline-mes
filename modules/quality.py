"""[팀원2] 품질 검사: 판정 구역 안에서 결함(marked_can, crushed_can)이 일정 시간 보이면 불량

판정 방식
  1) 판정 구역(QUALITY_ROI) 안에 중심이 들어온 것만 본다
     - 제품(PRODUCT_CLASS = can)
     - 결함(DEFECT_CLASSES = marked_can 표면 흠집, crushed_can 찌그러짐)
     찌그러진 캔처럼 '캔'으로 잡히지 않고 결함 라벨만 잡혀도 검사 대상이 된다.
  2) 구역 안에서 결함이 보인 시간을 누적해서 QUALITY_DEFECT_HOLD_SEC(기본 0.6초) 이상이면 '불량'
     (누적이라 YOLO가 한두 프레임 놓쳐도 이어서 센다. 순간 오검출은 시간이 모자라 무시된다)
  3) 캔이 QUALITY_SETTLE_SEC(기본 1초) 동안 결함 시간이 기준에 못 미치면 '정상'
     (결함 라벨만 있고 캔이 안 보이는 경우는 정상으로 확정하지 않고 계속 지켜본다)
  4) 판정은 구역이 빌 때까지 유지 → 제품 하나당 정확히 한 번 집계

상태 흐름: 대기 → 검사 중 → 정상/불량 → (구역 비움) → 대기
수정할 곳: PRODUCT_CLASS, DEFECT_CLASSES (모델의 클래스 이름과 글자까지 똑같이)
"""
import datetime
import os
import time
from collections import Counter, deque
import cv2
from flask import Blueprint, render_template, jsonify, send_from_directory, abort
import db
from camera_worker import CameraWorker
from config import (DEFECT_RATE_LIMIT, DEFECT_WINDOW, QUALITY_ROI, QUALITY_SETTLE_SEC, QUALITY_DEFECT_HOLD_SEC,
                    QUALITY_LEAVE_SEC)
from streaming import mjpeg
from state import state

PRODUCT_CLASS = "can"                              # 팀원2: 제품 클래스 이름
DEFECT_CLASSES = {"marked_can", "crushed_can"}     # 팀원2: 결함 클래스 이름 (모델 철자 그대로!)

# 불량 사진: 불량 판정 순간의 검사 카메라 화면(판정 상자 포함)을 검사 번호.jpg 로 저장
DEFECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defect_images")
DEFECT_KEEP = 1000          # 사진은 최근 이 개수만 남기고 오래된 것부터 지움
SAVE_DEFECT_IMAGES = False  # 지금은 불량함 메뉴에서 사진을 쓰지 않으므로 저장 안 함 (True로 바꾸면 다시 저장)


def save_defect_image(iid, jpeg):
    if not jpeg:
        return
    os.makedirs(DEFECT_DIR, exist_ok=True)
    with open(os.path.join(DEFECT_DIR, f"{iid}.jpg"), "wb") as f:
        f.write(jpeg)
    files = sorted((n for n in os.listdir(DEFECT_DIR) if n.endswith(".jpg")), key=lambda n: int(n[:-4]) if n[:-4].isdigit() else 0)
    for n in files[:-DEFECT_KEEP]:
        try:
            os.remove(os.path.join(DEFECT_DIR, n))
        except OSError:
            pass


def _center_in(box, area):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


class Worker(CameraWorker):
    def expected_classes(self):
        return [PRODUCT_CLASS] + sorted(DEFECT_CLASSES)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.history = deque(maxlen=DEFECT_WINDOW)   # 최근 판정 (True=불량)
        self.total = self.defects = 0
        self.type_counts = Counter()                 # 결함 유형별 개수 (화면 막대용)
        self.phase = "대기"
        self.enter_t = self.last_seen = self.prev_t = 0.0
        self.defect_time = 0.0      # 검사 중 결함이 보인 누적 시간
        self.seen_types = set()
        self.verdict_type = ""
        self.cup = None
        self.frame_defects = []
        # AI 판정 상세 (품질 검사 페이지): 검사 중 가장 확신이 높았던 결함 · 제품 확신도, 판정까지 걸린 시간
        self.best_defect = None       # {"cls", "conf", "box"} 판정 구역 안에서 본 결함 중 conf 최대
        self.best_cup = 0.0
        self.judge_sec = None
        self.frame_wh = (1, 1)

    def _roi_px(self, frame):
        h, w = frame.shape[:2]
        a, b, c, d = QUALITY_ROI
        return int(a * w), int(b * h), int(c * w), int(d * h)

    def judge(self, frame, dets):
        now = time.time()
        dt = min(now - self.prev_t, 0.5) if self.prev_t else 0.0   # 프레임 간격 (멈췄다 재개 시 과대 방지)
        self.prev_t = now
        roi = self._roi_px(frame)
        self.frame_wh = (frame.shape[1], frame.shape[0])
        inside = [d for d in dets if _center_in(d["box"], roi)]
        cups = [d for d in inside if d["cls"] == PRODUCT_CLASS]
        defects = [d for d in inside if d["cls"] in DEFECT_CLASSES]
        self.cup = max(cups, key=lambda d: d["conf"]) if cups else None
        self.frame_defects = defects
        present = bool(cups or defects)
        if present:
            self.last_seen = now

        if self.phase == "대기":
            if present:
                self.phase, self.enter_t = "검사 중", now
                self.defect_time, self.seen_types = 0.0, set()
                self.best_defect, self.best_cup, self.judge_sec = None, 0.0, None
        elif self.phase == "검사 중":
            if self.cup:
                self.best_cup = max(self.best_cup, self.cup["conf"])
            if defects:
                self.defect_time += dt
                self.seen_types |= {d["cls"] for d in defects}
                top = max(defects, key=lambda d: d["conf"])
                if not self.best_defect or top["conf"] > self.best_defect["conf"]:
                    self.best_defect = top
            if self.defect_time >= QUALITY_DEFECT_HOLD_SEC:
                self.phase = "불량"
                self.verdict_type = ", ".join(sorted(self.seen_types))
                self.judge_sec = now - self.enter_t
            elif cups and now - self.enter_t >= QUALITY_SETTLE_SEC:
                self.phase, self.verdict_type = "정상", ""
                self.judge_sec = now - self.enter_t
            elif not present and now - self.last_seen >= QUALITY_LEAVE_SEC:
                self.phase = "대기"                          # 판정 전에 빠져나감 → 집계 안 함
        else:                                                # 정상/불량 확정 → 구역이 빌 때까지 유지
            if not present and now - self.last_seen >= QUALITY_LEAVE_SEC:
                self.phase, self.verdict_type = "대기", ""

        return {"status": self.phase, "defect_type": self.verdict_type,
                "defect_seconds": round(self.defect_time, 2) if self.phase == "검사 중" else None,
                **self._stats()}

    def on_change(self, old, new, result):
        if old == "검사 중" and new in ("정상", "불량"):      # 제품 하나당 한 번만 집계
            self.history.append(new == "불량")
            self.total += 1
            self.defects += new == "불량"
            # OEE·교대 보고서용 생산 기록 + AI 판정 상세 (불량: 결함 신뢰도·위치 / 정상: 제품 신뢰도)
            w, h = self.frame_wh
            bd = self.best_defect if new == "불량" else None
            import demo_mode                               # 시연 모드의 가짜 캔이면 시연 기록으로 (지울 수 있게)
            iid = db.add_inspection(
                new, result.get("defect_type") or "", source="demo" if demo_mode.active(self.key) else "camera",
                conf=round(bd["conf"], 3) if bd else (round(self.best_cup, 3) if self.best_cup else None),
                box=[bd["box"][0] / w, bd["box"][1] / h, bd["box"][2] / w, bd["box"][3] / h] if bd else None,
                judge_sec=round(self.judge_sec, 2) if self.judge_sec else None,
                model=os.path.basename(self.model_path) if getattr(self, "model_path", None) and self.model else "더미 모드")
            if new == "불량":
                if SAVE_DEFECT_IMAGES:
                    save_defect_image(iid, state.get_frame(self.key))  # 방금 화면(NG 표시 포함)을 불량 사진으로
                db.log_event("quality", "불량 검출", defect_type=result.get("defect_type"), inspection=iid)
                for t in (result.get("defect_type") or "").split(", "):
                    if t:
                        self.type_counts[t] += 1
            state.update(self.key, **self._stats())

    def draw(self, frame, dets, result):
        x1, y1, x2, y2 = self._roi_px(frame)
        color = {"불량": (0, 0, 255), "정상": (0, 200, 0), "검사 중": (0, 200, 255)}.get(self.phase, (255, 160, 0))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)                # 판정 구역 (상태에 따라 색)
        frame = super().draw(frame, dets, result)
        text = {"불량": "NG", "정상": "OK", "검사 중": f"CHECK {self.defect_time:.1f}s"}.get(self.phase, "READY")
        cv2.putText(frame, text, (x1 + 5, y1 + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        return frame

    def _stats(self):
        rate = sum(self.history) / len(self.history) if self.history else 0.0
        return {"total": self.total, "defects": self.defects, "defect_rate": round(rate, 4),
                "window": len(self.history), "recent": list(self.history)[-20:][::-1],   # 최신이 앞
                "type_counts": dict(self.type_counts)}


bp = Blueprint("quality", __name__)


@bp.route("/quality")
def page():
    return render_template("quality.html", hold_sec=QUALITY_DEFECT_HOLD_SEC, rate_limit=DEFECT_RATE_LIMIT)


@bp.route("/quality/video")
def video():
    return mjpeg("quality")


@bp.route("/api/quality")
def api():
    return jsonify(state.get("quality"))


@bp.route("/defect-image/<int:iid>.jpg")
def defect_image(iid):
    """불량 사진 (디지털 트윈 불량함 메뉴에서 사용)"""
    if not os.path.exists(os.path.join(DEFECT_DIR, f"{iid}.jpg")):
        abort(404)
    return send_from_directory(DEFECT_DIR, f"{iid}.jpg", max_age=3600)


@bp.route("/api/defects")
def api_defects():
    """오늘 불량 목록 (최신 순) + 종류별 개수 — 디지털 트윈 불량함 메뉴"""
    now = time.time()
    midnight = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
    rows = db.defects_between(midnight, now + 1, limit=200)
    counts = Counter(t for r in rows for t in (r["defect_type"] or "").split(", ") if t)
    for r in rows:
        r["image"] = f"/defect-image/{r['id']}.jpg" if os.path.exists(os.path.join(DEFECT_DIR, f"{r['id']}.jpg")) else None
    return jsonify({"count": len(rows), "types": dict(counts.most_common()), "rows": rows[:60]})
