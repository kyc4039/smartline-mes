"""품질 검사 페이지 데이터: 생산 정보 · AI 판정 상세 · 시간별 불량률 · 불량 원인 · 검사 이력 · 불량품 처리

데이터 근거
  - DB inspections (품질 카메라 판정 + 카메라가 없을 때 시뮬레이터 기록)
    conf(신뢰도) · box(검출 위치) · judge_sec(판정 시간) · model(사용 모델)은 modules/quality.py가 판정 때 함께 저장
  - LOT 번호 · 목표 생산량은 production.py (트럭 1대 = LOT 1개)와 같은 규칙
설정 (config.py에 없으면 기본값)
  PRODUCT_NAME = "알루미늄 캔 355ml"
  WORK_ORDER   = "WO-1006-01"    # 없으면 오늘 날짜로 자동
  LINE_NAME    = "LINE A"
"""
import collections
import datetime
import json
import time
import config
import db
import production
from config import DEFECT_RATE_LIMIT, QUALITY_ROI

PRODUCT_NAME = getattr(config, "PRODUCT_NAME", "알루미늄 캔 355ml")
LINE_NAME = getattr(config, "LINE_NAME", "LINE A")

# 불량 유형 → (한글 이름, 추정 원인, 점검할 곳, 정비 요청을 보낼 설비)
#   AI가 원인을 아는 것이 아니라, 유형별로 미리 정한 점검표 (팀원과 함께 고쳐 쓰기)
DEFECT_INFO = {
    "marked_can":  ("표면 흠집", "이송 중 가이드·다른 캔과 마찰 · 금형 표면 흠", "가이드 레일 · 로봇 그리퍼 패드 · 금형 표면 점검", "컨베이어"),
    "crushed_can": ("찌그러짐", "프레스 압력 과다 · 금형 정렬 불량 · 적재 시 충격", "프레스 압력 · 금형 정렬 · 로봇 놓는 높이 점검", "프레스 #1"),
}
CURRENT_TYPES = list(DEFECT_INFO)        # 지금 모델의 불량 유형 (파레토에 0건이라도 표시)
# 예전 종이컵 모델 기록이 DB에 남아 있어도 한글 이름이 나오도록 (파레토에는 기록이 있을 때만 표시)
DEFECT_INFO.update({
    "scratch":  ("긁힘(이전 모델)", "컨베이어 가이드 마찰 · 금형 표면 흠", "가이드 레일 · 금형 표면 점검", "컨베이어"),
    "wrinkled": ("구김(이전 모델)", "프레스 압력 불균일", "유압 압력 점검", "프레스 #1"),
})
UNSUPPORTED = ["뚜껑 불량", "인쇄 불량"]       # 지금 모델에 없는 유형 (학습 데이터 추가 필요) → 화면에 회색으로 안내
REPEAT_N, REPEAT_SEC = 3, 600            # 같은 유형이 10분에 3번 넘으면 정비 요청 추천


def _midnight(ts):
    return datetime.datetime.combine(datetime.date.fromtimestamp(ts), datetime.time()).timestamp()


def work_order(now):
    return getattr(config, "WORK_ORDER", None) or datetime.date.fromtimestamp(now).strftime("WO-%m%d-01")


def location(box):
    """검출 상자 가운데가 판정 구역의 어디쯤인지 → '오른쪽 위' 같은 말"""
    if not box:
        return ""
    b = json.loads(box) if isinstance(box, str) else box
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    a, t, c, d = QUALITY_ROI
    fx = min(0.999, max(0.0, (cx - a) / (c - a))) if c > a else 0.5
    fy = min(0.999, max(0.0, (cy - t) / (d - t))) if d > t else 0.5
    h = ["왼쪽", "가운데", "오른쪽"][int(fx * 3)]
    v = ["위", "가운데", "아래"][int(fy * 3)]
    return "가운데" if h == v == "가운데" else f"{h} {v}" if v != "가운데" else h


def _row(i, lot):
    types = [t for t in (i.get("defect_type") or "").split(", ") if t]
    return {"id": i["id"], "ts": i["ts"], "lot": lot, "result": i["result"], "types": types,
            "type_kr": ", ".join(DEFECT_INFO.get(t, (t,))[0] for t in types),
            "conf": i.get("conf"), "box": json.loads(i["box"]) if i.get("box") else None, "where": location(i.get("box")),
            "judge_sec": i.get("judge_sec"), "model": i.get("model") or "", "source": i.get("source") or "camera",
            "disposition": i.get("disposition") or "", "disp_ts": i.get("disp_ts")}


PENDING = "자동 격리"     # 불량함에 들어갔지만 아직 사람이 확인하지 않은 상태 (기능이 생기기 전 기록은 빈칸이라 세지 않음)


def _roi_xy(box):
    """검출 상자 가운데 → 판정 구역 안 위치 (0~1, 0~1)"""
    b = json.loads(box) if isinstance(box, str) else box
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    a, t, c, d = QUALITY_ROI
    return (round(min(1, max(0, (cx - a) / (c - a))), 3), round(min(1, max(0, (cy - t) / (d - t))), 3))


def _cell_name(col, row):
    """9칸 중 (열, 행) → '오른쪽 위' 같은 말"""
    h, v = ["왼쪽", "가운데", "오른쪽"][col], ["위", "가운데", "아래"][row]
    return "가운데" if h == v == "가운데" else h if v == "가운데" else f"{h} {v}" if h != "가운데" else f"가운데 {v}"


def info(filt="bad", lot=None, now=None, limit=80):
    now = now or time.time()
    m = _midnight(now)
    day = datetime.date.fromtimestamp(now).strftime("%Y%m%d")
    insp = db.inspections_between(m, now + 1)
    lots = production.lot_ids(insp, day)
    prod = production.summary(now)
    c = prod["current"]
    total = len(insp)
    defects = sum(i["result"] == "불량" for i in insp)
    pbar = defects / total if total else 0.0                      # 오늘 평균 불량률 (관리도 중심선)

    # ③ p 관리도: 시간별 불량률 + 관리 한계 UCL = p̄ + 3·√(p̄(1-p̄)/n)  (검사 수 n이 적을수록 한계가 넓어짐)
    hours = collections.OrderedDict()
    for i in insp:
        h = datetime.datetime.fromtimestamp(i["ts"]).hour
        t, b = hours.get(h, (0, 0))
        hours[h] = (t + 1, b + (i["result"] == "불량"))
    trend = []
    for h, (t, b) in list(hours.items())[-13:]:
        p = b / t if t else 0
        ucl = min(1.0, pbar + 3 * (pbar * (1 - pbar) / t) ** 0.5) if t else None
        trend.append({"hour": h, "total": t, "defects": b, "rate": p, "ucl": ucl,
                      "out": bool(ucl is not None and p > ucl), "warn": p > DEFECT_RATE_LIMIT})

    # ④ 불량 유형 파레토 (많은 순 + 누적 비율) · 추정 원인 · 최근 10분 반복 경고
    cnt, recent = collections.Counter(), collections.Counter()
    for i in insp:
        if i["result"] == "불량":
            for t in (i.get("defect_type") or "").split(", "):
                if t:
                    cnt[t] += 1
                    if i["ts"] >= now - REPEAT_SEC:
                        recent[t] += 1
    order = sorted(set(CURRENT_TYPES) | set(cnt), key=lambda t: -cnt.get(t, 0))
    ssum, run, causes = sum(cnt.values()) or 1, 0, []
    for t in order:
        run += cnt.get(t, 0)
        causes.append({"type": t, "name": DEFECT_INFO.get(t, (t, "", "", ""))[0], "count": cnt.get(t, 0),
                       "cum": run / ssum, "cause": DEFECT_INFO.get(t, ("", "점검표 없음"))[1],
                       "check": DEFECT_INFO.get(t, ("", "", "-"))[2], "equipment": DEFECT_INFO.get(t, ("", "", "", "비전 검사기"))[3],
                       "recent": recent.get(t, 0), "alert": recent.get(t, 0) >= REPEAT_N})

    # 불량 위치 지도: 오늘 불량의 판정 구역 안 위치 (최근 400개) + 9칸 비율
    pts, cells = [], collections.Counter()
    for i in insp:
        if i["result"] == "불량" and i.get("box"):
            x, y = _roi_xy(i["box"])
            t = (i.get("defect_type") or "").split(", ")[0]
            pts.append([x, y, t])
            cells[(min(2, int(x * 3)), min(2, int(y * 3)))] += 1
    pts = pts[-400:]
    ncell = sum(cells.values())
    hot = [{"col": k[0], "row": k[1], "count": v, "ratio": v / ncell,
            "where": _cell_name(k[0], k[1])}
           for k, v in cells.most_common(3)] if ncell else []
    for hcell in hot:      # 그 칸에서 가장 많은 유형
        tc = collections.Counter(p[2] for p in pts if min(2, int(p[0] * 3)) == hcell["col"] and min(2, int(p[1] * 3)) == hcell["row"])
        hcell["type"] = tc.most_common(1)[0][0] if tc else ""

    # ⑤ 검사 이력 (최신 순, 거르기: all / bad / pending(자동 격리 후 확인 전) / lot)
    rows = []
    for i, l in zip(reversed(insp), reversed(lots)):
        if filt == "bad" and i["result"] != "불량":
            continue
        if filt == "pending" and i.get("disposition") != PENDING:
            continue
        if lot and l != lot:
            continue
        rows.append(_row(i, l))
        if len(rows) >= limit:
            break

    last = insp[-1] if insp else None
    lot_of = dict(zip((i["id"] for i in insp), lots))
    last50 = insp[-50:]
    r50 = sum(i["result"] == "불량" for i in last50) / len(last50) if last50 else 0
    plan = prod.get("plan", {})
    return {
        "info": {"lot": c["id"], "product": PRODUCT_NAME, "work_order": work_order(now), "line": LINE_NAME,
                 "equipment": "④ 비전 검사기 · CAM 2", "lot_good": c["good"], "lot_target": prod["lot_good"],
                 "today_total": total, "today_target": plan.get("target", 0), "sim": prod["sim"],
                 # 카드용: 트럭 출발 예상 · 계획 대비 (지금 시각까지 만들었어야 할 양과 비교)
                 "eta_sec": c.get("eta_sec"), "left_pallets": c.get("left_pallets"),
                 "plan_done": plan.get("done", 0), "plan_target": plan.get("target", 0), "forecast": plan.get("forecast", 0),
                 "plan_label": plan.get("label", ""),
                 "plan_expected": int(plan.get("target", 0) * max(0.0, min(1.0, (now - plan["start"]) / max(1, plan["end"] - plan["start"])))) if plan else 0},
        "last": _row(last, lot_of.get(last["id"], "")) if last else None,
        "recent": [i["result"] == "불량" for i in reversed(insp[-30:])],          # 최신이 앞
        "trend": trend, "limit": DEFECT_RATE_LIMIT, "pbar": pbar,
        "causes": causes, "unsupported": UNSUPPORTED,
        "heat": {"points": pts, "hot": hot, "count": ncell},
        "today": {"total": total, "good": total - defects, "defects": defects, "rate50": r50, "n50": len(last50),
                  "ucl50": min(1.0, pbar + 3 * (pbar * (1 - pbar) / 50) ** 0.5) if total else None,
                  "pending": sum(1 for i in insp if i.get("disposition") == PENDING),
                  "false": sum(1 for i in insp if i.get("disposition") == "오판 · 정상품")},
        "rows": rows, "filter": filt, "lot_filter": lot, "lots": sorted(set(lots), reverse=True)[:10],
    }


def false_rows():
    """'오판 · 정상품'으로 표시한 검사 전체 (재학습용 목록)"""
    with db._lock, db._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM inspections WHERE disposition = '오판 · 정상품' ORDER BY id")]


def dispose(iid, action):
    """불량품 확인: confirm(진짜 불량) / false(오판 → 정상품, 재학습 목록) / ticket(정비 요청 작성으로)
    격리는 판정 순간 자동 (불량함으로 분기)"""
    i = db.get_inspection(iid)
    if not i:
        return None, "검사 기록이 없어요"
    if i["result"] != "불량":
        return None, "불량 판정만 처리할 수 있어요"
    label = {"confirm": "불량 확인", "false": "오판 · 정상품", "ticket": "정비 요청"}.get(action)
    if not label:
        return None, "알 수 없는 처리"
    db.set_disposition(iid, label)
    db.log_event("quality", f"불량품 처리: {label}", inspection=iid, defect_type=i.get("defect_type"))
    types = [t for t in (i.get("defect_type") or "").split(", ") if t]
    eq = DEFECT_INFO.get(types[0], ("", "", "", "비전 검사기"))[3] if types else "비전 검사기"
    text = (f"품질 관리 #{iid}에서 {', '.join(DEFECT_INFO.get(t, (t,))[0] for t in types) or '불량'}이(가) 반복 검출돼요. "
            f"{DEFECT_INFO.get(types[0], ('', '', '설비 점검'))[2] if types else '설비 점검'}이 필요해요.")
    return {"id": iid, "disposition": label, "ticket_equipment": eq, "ticket_text": text}, ""
