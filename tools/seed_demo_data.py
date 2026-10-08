"""시연용 과거 기록 만들기 — 그래프 · 추이 · OEE · 정비 지표가 비어 보이지 않게 (10/08)

실행 (smartline-mes 폴더에서, 서버를 끈 상태로):
  uv run python tools/seed_demo_data.py              최근 평일 7일(오늘 포함) 기록으로 새 DB 만들기
  uv run python tools/seed_demo_data.py --days 10    평일 10일
  uv run python tools/seed_demo_data.py --no-today   오늘은 비워 두기 (오늘은 시뮬레이터 · 시연으로만)

하는 일
  - 지금 smartline.db는 smartline.db.bak_날짜시각 으로 이름을 바꿔 보관하고 새 DB를 만듦
    (기록 번호가 시간 순서여야 타임라인 · 라인 흐름이 맞게 계산되기 때문)
    되돌리기: 서버를 끄고 smartline.db를 지운 뒤 백업 파일 이름을 smartline.db로
  - 날마다 교대 시간(config SHIFT_START~SHIFT_END) 동안
      검사 기록(캔 1개 = 1줄, 택트 약 5~6초) · 불량 1.5~4% (주 후반으로 갈수록 조금씩 개선)
      프레스 안전 정지(손 · 공구 침입 → 5초 비면 자동 재가동) 2~4회 · 경고구역 접근 3~8회
      고장 보고 → 정비 티켓(즉시 · 당일 · 정기) → 정비 시작 → 완료, 즉시 조치는 설비 정지 + 컨베이어 연동 정지
      작업자 입장 · 정비 판정 피드백 일부
  - 오늘은 교대 시작부터 '지금 3분 전'까지만 (그 뒤는 실제 카메라 · 시뮬레이터가 이어서 기록)
  - 오늘 정비 요청 1건은 '대기'로 남겨 둠 (시연에서 정비 시작 → 트윈 정비원 이동을 보여 줄 수 있게)
"""
import datetime
import json
import os
import random
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config  # noqa: E402
import db      # noqa: E402

DB = config.DB_PATH
SHIFT_START = getattr(config, "SHIFT_START", "08:00")
SHIFT_END = getattr(config, "SHIFT_END", "16:00")
CYCLE = max(float(getattr(config, "TARGET_CYCLE_SEC", 5.0)), float(getattr(config, "INSPECT_SEC", 4.0)) + 1.0)
TAG = {"seed": 1}
TOOLS = [("hand", "손", 0.7), ("screwdriver", "드라이버", 0.12), ("spanner", "스패너", 0.12), ("balldriver", "볼드라이버", 0.06)]

# (설비, 고장 보고 문장, 담당 분야, 조치 시점, 조치 메모)
REPORTS = [
    ("컨베이어", "컨베이어 벨트가 한쪽으로 쏠려서 캔이 자꾸 넘어지고 라인이 멈췄어요", "기계", "상", "벨트 장력 · 정렬 조정"),
    ("컨베이어", "모터 과열 알람 뜨고 재기동이 안 돼서 컨베이어 정지", "전기", "상", "인버터 과열 리셋 · 냉각팬 청소"),
    ("컨베이어", "하단 롤러에서 덜컹거리는 소리 나는데 이송은 정상", "기계", "하", "롤러 베어링 그리스 보충"),
    ("컨베이어", "아까부터 벨트가 가끔 멈칫거려서 속도가 느려졌어요", "기계", "중", "구동 체인 장력 조정"),
    ("프레스 #1", "프레스 하강할 때 유압 호스 연결부에서 기름이 뚝뚝 떨어짐 바닥 미끄러움", "유압공압", "상", "호스 피팅 교체 · 바닥 청소"),
    ("프레스 #1", "양수 버튼 한쪽만 눌러도 슬라이드가 내려와요", "전기", "상", "양수 버튼 회로 릴레이 교체"),
    ("프레스 #1", "금형 쪽에서 끼익 소리가 점점 커짐 작업은 됨", "기계", "중", "금형 가이드 윤활"),
    ("로봇 적재기", "그리퍼 에어가 새서 캔을 두세 번에 한 번 놓침", "유압공압", "중", "그리퍼 솔레노이드 밸브 교체"),
    ("로봇 적재기", "로봇 원점 복귀할 때 한 박자 늦음 적재는 정상", "전기", "하", "서보 파라미터 점검"),
    ("비전 검사기", "검사기 조명이 깜빡여서 정상 캔도 불량으로 자꾸 걸림", "센서", "중", "조명 컨트롤러 교체"),
    ("비전 검사기", "카메라 렌즈에 먼지가 껴서 화면이 뿌옇습니다 판정은 됨", "센서", "하", "렌즈 청소"),
    ("자재 투입기", "투입기 근접 센서가 반응이 없어서 캔이 안 들어가고 라인 멈춤", "센서", "상", "근접 센서 교체 · 감지 거리 조정"),
    ("자재 투입기", "투입 롤러가 헛돌아서 캔이 가끔 비뚤게 들어감", "기계", "중", "롤러 표면 교체"),
]
WORKERS = ["김정비", "박정비", "이정비"]


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime.combine(day, datetime.time(h, m)).timestamp()


def J(**kw):
    return json.dumps({**kw, **TAG}, ensure_ascii=False)


def probs(names, pick, p):
    rest = (1 - p) / (len(names) - 1)
    return {n: round(p if n == pick else rest, 3) for n in names}


class Day:
    def __init__(self, c, day, end_cap, quality, n):
        self.c, self.day, self.q, self.n = c, day, quality, n
        self.a, self.b = at(day, SHIFT_START), min(at(day, SHIFT_END), end_cap)
        self.stops = []          # (시작, 끝) 라인이 멈춘 구간
        self.ev = []             # (ts, module, event, detail)

    def eq(self, ts, name, status, reason=""):
        self.ev.append((ts, "equipment", f"{name} → {status}", J(reason=reason)))

    def line_stop(self, ts, te, cause, reason_stop, reason_go):
        self.eq(ts, cause, "안전 정지" if cause == "프레스 #1" and "정비" not in reason_stop else "고장 정지", reason_stop)
        if cause != "컨베이어":
            self.eq(ts + 0.5, "컨베이어", "연동 정지", f"{cause} 정지로 라인 정지")
        self.eq(te, cause, "가동", reason_go)
        if cause != "컨베이어":
            self.eq(te + 0.5, "컨베이어", "가동", "연동 해제")
        self.stops.append((ts, te + 0.5))

    def free(self, t, dur):
        return all(t + dur + 60 < s or t > e + 60 for s, e in self.stops) and t + dur < self.b - 120

    def slot(self, dur, lo=0.05, hi=0.95):
        for _ in range(50):
            t = self.a + (self.b - self.a) * random.uniform(lo, hi)
            if self.free(t, dur):
                return t
        return None

    def build(self):
        span = self.b - self.a
        if span < 600:
            return
        # 입장
        for k in range(random.randint(3, 5)):
            self.ev.append((self.a - random.uniform(60, 900), "gate", "작업자 입장 승인", J(items=["안전모", "조끼", "장갑"])))
        # 고장 보고 → 정비
        for _ in range(random.choice([1, 2, 2, 3]) if span > 3 * 3600 else 1):
            self.ticket()
        # 프레스 안전 정지
        for _ in range(random.randint(2, 4) if span > 3 * 3600 else 1):
            dur = random.uniform(6, 35)
            t = self.slot(dur)
            if t is None:
                continue
            cls, kr, _w = random.choices(TOOLS, weights=[x[2] for x in TOOLS])[0]
            self.ev.append((t, "safety", f"위험구역 {kr} 침입 → 안전 정지", J(cls=cls, conf=round(random.uniform(0.62, 0.95), 2))))
            self.ev.append((t + dur, "safety", "위험구역 5초 비어 있음 → 자동 재가동", J()))
            self.line_stop(t, t + dur, "프레스 #1", kr, "")
        # 경고구역 접근 (정지 없음)
        for _ in range(random.randint(3, 8) if span > 3 * 3600 else 2):
            t = self.slot(5)
            if t:
                cls, kr, _w = random.choices(TOOLS, weights=[x[2] for x in TOOLS])[0]
                self.ev.append((t, "safety", f"경고구역 {kr} 접근", J(cls=cls, conf=round(random.uniform(0.5, 0.9), 2), dur=round(random.uniform(1, 6), 1))))
        if self.n == 0 and self.b > time.time() - 600:   # 오늘: '대기' 정비 요청 1건
            self.pending()
        self.inspect()

    def pending(self):
        eqn, text, typ, urg, _a = random.choice([r for r in REPORTS if r[3] != "상"])
        t = self.b - random.uniform(300, 1500)
        result = {"type": typ, "urgency": urg, "need_review": False,
                  "type_probs": probs(["기계", "전기", "유압공압", "센서"], typ, 0.8),
                  "urgency_probs": probs(["상", "중", "하"], urg, 0.75), "review_reasons": [], **TAG}
        tid = self.c.execute("INSERT INTO tickets (ts, equipment, text, type, urgency, need_review, status, result, assignee, started, done_ts, action) "
                             "VALUES (?,?,?,?,?,0,'대기',?,'',NULL,NULL,'')", (t, eqn, text, typ, urg, json.dumps(result, ensure_ascii=False))).lastrowid
        self.ev.append((t, "maintenance", "정비 요청 접수", J(ticket=tid, equipment=eqn, type=typ, urgency=urg)))

    def ticket(self):
        eqn, text, typ, urg, action = random.choice(REPORTS)
        wait = random.uniform(120, 600)                # 접수 → 시작
        fix = random.uniform(600, 2400) if urg == "상" else random.uniform(900, 3600)
        t = self.slot(wait + fix + 120, 0.05, 0.8)
        if t is None:
            return
        start, done = t + wait, t + wait + fix
        status = "완료"
        review = random.random() < 0.15
        result = {"type": typ, "urgency": urg, "need_review": review,
                  "type_probs": probs(["기계", "전기", "유압공압", "센서"], typ, random.uniform(0.55, 0.92)),
                  "urgency_probs": probs(["상", "중", "하"], urg, random.uniform(0.55, 0.9)),
                  "review_reasons": ["확신도 낮음"] if review else [], **TAG}
        cur = self.c.execute("INSERT INTO tickets (ts, equipment, text, type, urgency, need_review, status, result, assignee, started, done_ts, action) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (t, eqn, text, typ, urg, int(review), status, json.dumps(result, ensure_ascii=False),
                              random.choice(WORKERS) if start else "", start, done, action if done else ""))
        tid = cur.lastrowid
        self.ev.append((t, "maintenance", "정비 요청 접수", J(ticket=tid, equipment=eqn, type=typ, urgency=urg)))
        if start:
            self.ev.append((start, "maintenance", "정비 시작", J(ticket=tid, equipment=eqn, who="정비원", lock=False)))
        if done:
            fb = "없음"
            if random.random() < 0.6:
                ok = random.random() < 0.85
                tt = typ if ok else random.choice([x for x in ["기계", "전기", "유압공압", "센서"] if x != typ])
                self.c.execute("INSERT OR REPLACE INTO feedback (ts, ticket_id, equipment, text, ai_type, ai_urgency, true_type, true_urgency, note) "
                               "VALUES (?,?,?,?,?,?,?,?,?)", (done, tid, eqn, text, typ, urg, tt, urg, ""))
                fb = "맞음" if ok else "수정"
            self.ev.append((done, "maintenance", "정비 완료", J(ticket=tid, equipment=eqn, feedback=fb)))
        if urg == "상" and done:
            self.line_stop(t + 1, done, eqn, f"정비 요청 #{tid}", f"정비 완료 #{tid}")

    def inspect(self):
        rows = []
        t = self.a + random.uniform(20, 90)
        stops = sorted(self.stops)
        k = 0
        while t < self.b:
            while k < len(stops) and stops[k][1] <= t:
                k += 1
            if k < len(stops) and stops[k][0] <= t:
                t = stops[k][1] + CYCLE
                continue
            if random.random() < 0.004:              # 자재 대기 같은 짧은 끊김
                t += random.uniform(20, 120)
                continue
            bad = random.random() < self.q
            dt = random.choice(["marked_can", "crushed_can"]) if bad else ""
            cx, cy = random.gauss(0.5, 0.06), random.gauss(0.55, 0.05)
            w, h = random.uniform(0.05, 0.1), random.uniform(0.06, 0.12)
            disp = ""
            if bad:
                disp = random.choices(["불량 확인", "자동 격리", "오판 · 정상품"], weights=[0.75, 0.17, 0.08])[0]
            rows.append((t, "불량" if bad else "정상", dt, "camera", round(random.uniform(0.82, 0.97) if not bad else random.uniform(0.6, 0.93), 3),
                         json.dumps([round(cx - w / 2, 3), round(cy - h / 2, 3), round(cx + w / 2, 3), round(cy + h / 2, 3)]),
                         round(random.uniform(0.9, 1.3), 2), "best.pt", disp, t + random.uniform(30, 900) if bad else None))
            t += CYCLE * random.uniform(1.0, 1.18)
        cur = self.c.executemany("INSERT INTO inspections (ts, result, defect_type, source, conf, box, judge_sec, model, disposition, disp_ts) "
                                 "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        for r in rows:
            if r[1] == "불량" and random.random() < 0.3:
                self.ev.append((r[0] + 0.2, "quality", "불량 검출", J(defect_type=r[2])))
        self.count = len(rows)


def main():
    args = sys.argv[1:]
    days = int(args[args.index("--days") + 1]) if "--days" in args else 7
    if os.path.exists(DB):
        bak = f"{DB}.bak_{time.strftime('%m%d_%H%M%S')}"
        shutil.move(DB, bak)
        for ext in ("-wal", "-shm", "-journal"):
            if os.path.exists(DB + ext):
                shutil.move(DB + ext, bak + ext)
        print(f"기존 DB 보관: {os.path.basename(bak)}")
    db.init()
    c = sqlite3.connect(DB)
    random.seed()
    now = time.time()
    today = datetime.date.fromtimestamp(now)
    picked, d = [], today
    while len(picked) < days:
        if d.weekday() < 5 and not (d == today and "--no-today" in args):
            picked.append(d)
        d -= datetime.timedelta(days=1)
    picked.reverse()
    insp_ranges, total = [], {"insp": 0, "tickets": 0, "events": 0}
    q0, q1 = 0.04, 0.017                                     # 첫날 → 마지막 날 불량률 (조금씩 개선)
    for i, day in enumerate(picked):
        q = q0 + (q1 - q0) * i / max(1, len(picked) - 1) + random.uniform(-0.004, 0.004)
        cap = now - 180 if day == today else 1e12
        D = Day(c, day, cap, q, len(picked) - 1 - i)
        before_t = c.execute("SELECT COALESCE(MAX(id),0) FROM tickets").fetchone()[0]
        lo = c.execute("SELECT COALESCE(MAX(id),0) FROM inspections").fetchone()[0] + 1
        D.build()
        hi = c.execute("SELECT COALESCE(MAX(id),0) FROM inspections").fetchone()[0]
        if hi >= lo:
            insp_ranges.append([lo, hi])
        D.ev.sort()
        c.executemany("INSERT INTO events (ts, module, event, detail) VALUES (?,?,?,?)", D.ev)
        nt = c.execute("SELECT COALESCE(MAX(id),0) FROM tickets").fetchone()[0] - before_t
        total["insp"] += max(0, hi - lo + 1); total["tickets"] += nt; total["events"] += len(D.ev)
        print(f"  {day} ({'월화수목금토일'[day.weekday()]}) 검사 {max(0, hi - lo + 1):>5}개 · 불량률 {q * 100:.1f}% · 정지 {len(D.stops)}회 · 정비 {nt}건")
    c.commit()
    print(f"\n완료: 검사 {total['insp']}개 · 정비 티켓 {total['tickets']}건 · 이벤트 {total['events']}줄")
    print("서버를 켜고 브라우저에서 Ctrl+Shift+R (맥 Cmd+Shift+R)")


if __name__ == "__main__":
    main()
