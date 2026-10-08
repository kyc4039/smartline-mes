"""라인 흐름 장부 (10/07 · FLOW_V2) — "검사 기록 1줄 = 상자 1개", 흐름은 서버가 한 번만 계산하고 화면은 그리기만

왜: 예전에는 디지털 트윈 · 관제 대시보드가 각자 4초 시계로 상자를 돌리며 DB 숫자를 '따라가서'
    정지 · 불량 · 몰아넣기 · 새로고침 때 세 화면(트윈 · 대시보드 · 생산 관리 트럭)이 서로 어긋났다.

규칙
  - 라인 시계 τ(초): 오늘 0시부터, 컨베이어가 '가동'일 때만 흐름 (시연 빨리감기 중에는 ×8)
  - 상자 = 오늘 검사 기록 1줄 (id 그대로). 기록 시각 = 비전 검사기 판정 순간 (tv)
  - 비전 검사기 (10/07 검사기 정지 방식): 상자가 검사기에 도착하면 INSPECT(4초) 멈춰 검사 → 끝나면 다음 상자가 MOVE(1초) 만에 들어옴
      한 상자의 검사 구간 [ws, we]: ws = 앞 상자가 떠난 뒤 + MOVE (라인이 IDLE_GAP 넘게 비어 있었으면 tv - INSPECT)
                                     we = max(ws + INSPECT, tv)  ← 판정이 늦으면 그만큼 더 머묾 (카메라 앞 캔 = 검사 중인 상자)
      검사 구간 안에 불량 기록이 오면 그 상자가 불량 (tj = 결과가 보이는 순간). 검사 시간 동안 불량이 없으면 시뮬레이터가 '정상' 기록
      → 기록 수 = 투입 수, 불량 1개 = 양품 1개 감소 (불량이 '추가 상자'가 아님)
      불량: 검사기(we) → D_DIV초 뒤 분기점 → D_CHUTE초 뒤 불량함
      정상: 검사기(we) → D_END초 뒤 벨트 끝 도착 → 로봇 대기열 (로봇은 한 번에 하나)
            로봇 한 동작 rc초: 내려가기(0.35) → 집기 → 놓기(0.875) → 돌아오기
            로봇 앞에 Q_FAST개 이상 밀려 있으면 rc = RC_FAST (적체 해소 ×2)
  - 정상 상자 8개를 놓으면 팔레트 1개 → 지게차(FORK_SEC, FORK_DROP초에 트럭에 내려놓음)
    트럭에 10팔레트째 내려놓는 순간 출발 → DEPART_EMPTY초 뒤 빈 트럭
  - LOT 번호: 놓인 순서로 정상 80개마다 1개 = 생산 관리 LOT 번호와 같음 (닫히는 시각만 '트럭 출발' 기준)
  - 서버를 다시 켜도 오늘 기록 · 설비 기록으로 똑같이 다시 계산 (빨리감기 기록만 메모리)
API: /api/line/flow → 지금 τ, 진행 중인 상자, 앞으로 몇 초 동안의 사건(놓기 · 지게차 · 출발 · 불량함), 지금 숫자
"""
import datetime
import json
import threading
import time
import config
import db

D_PRE, D_END, D_DIV, D_CHUTE = 8.0, 4.0, 1.5, 2.0     # 투입→검사기 · 검사기→벨트 끝 · 검사기→분기점 · 분기점→불량함
RC, RC_FAST, Q_FAST = 4.0, 2.0, 3                       # 로봇 한 동작(초) · 적체 해소 · 적체 기준 개수
GRAB, PLACE = 0.35, 0.875                               # 로봇 한 동작 안에서 집는 · 놓는 시점 (비율)
FORK_SEC, FORK_DROP, DEPART_EMPTY = 4.4, 2.1, 3.1
CONVEYOR = "컨베이어"
PALLET = int(getattr(config, "PALLET_SIZE", 8))
TRUCK = int(getattr(config, "TRUCK_PALLETS", 10))
LOT = PALLET * TRUCK
from analytics import TARGET_CYCLE_SEC, INSPECT_SEC
INSPECT = INSPECT_SEC                                   # 검사기에서 멈춰 검사하는 시간 (기본 4초)
CYCLE = TARGET_CYCLE_SEC                                # 택트 = 검사 + 이동 (기본 5초)
MOVE = max(0.5, CYCLE - INSPECT)                        # 검사 끝 → 다음 상자가 검사기에 들어오기까지
IDLE_GAP = 60.0                                         # 검사기가 이만큼 비어 있었으면 새로 시작한 것으로 봄
INSPECT_FAST, MOVE_FAST = 1.0, 0.5                     # 기록이 검사기보다 많이 밀렸을 때(몰아 넣은 기록 · 예전 방식 기록) 빠른 검사로 따라잡기
LAG_FAST, LAG_RESET = 12.0, 90.0                        # 밀린 정도(초): 이보다 크면 빠른 검사 · 이보다 크면 밀린 것을 버리고 새로 시작
VERDICT_LEAD = 2.0                                      # 시뮬레이터 판정 기록: 검사 끝나기 이만큼 전 (검사 4초 중 2초에 결과)
REVEAL_MIN = 0.6                                        # 검사 시작 후 최소 이만큼 지나야 결과 표시 (몰아 들어온 기록)
_anchor = {"ws": None, "last": None}                    # 라인이 오래 비었다가 다시 시작할 때 첫 상자의 검사 시작 τ

_lock = threading.Lock()
_ff = []            # 빨리감기 [(시작, 끝 또는 None, 배속, 목표 LOT 번호)]
_cache = {"key": None}


def _midnight(now):
    return datetime.datetime.combine(datetime.date.fromtimestamp(now), datetime.time()).timestamp()


# ---------------------------------------------------------------- 빨리감기 (시연 '트럭 출발')
def fast_forward(k=8.0, until_lot=None, max_sec=120, until_placed=None, until_count=None):
    """until_lot: 이 LOT 트럭이 출발하면 끝 · until_placed: 로봇이 놓은 양품 수가 이만큼 되면 끝 · until_count: 오늘 검사 기록 수"""
    with _lock:
        now = time.time()
        for f in _ff:                                             # 진행 중인 것은 지금 끝냄
            if f[1] is None:
                f[1] = now
        _ff.append([now, None, float(k), until_lot, now + max_sec, until_placed, until_count])
        _cache["key"] = None


def ff_stop():
    with _lock:
        now = time.time()
        for f in _ff:
            if f[1] is None:
                f[1] = now
        _cache["key"] = None


def ff_active():
    return any(f[1] is None for f in _ff)


# ---------------------------------------------------------------- 라인 시계 τ
def _conveyor_runs(m, now):
    """[(시작, 끝, 가동?)] 오늘 0시~지금 컨베이어 상태 구간"""
    with db._lock, db._conn() as c:
        prev = c.execute("SELECT event FROM events WHERE module='equipment' AND event LIKE ? AND ts < ? ORDER BY id DESC LIMIT 1",
                         (CONVEYOR + " → %", m)).fetchone()
        rows = c.execute("SELECT ts, event FROM events WHERE module='equipment' AND event LIKE ? AND ts >= ? AND ts <= ? ORDER BY ts, id",
                         (CONVEYOR + " → %", m, now)).fetchall()
        last_id = c.execute("SELECT MAX(id) FROM events WHERE module='equipment'").fetchone()[0]
    run = (prev["event"].split("→")[-1].strip() == "가동") if prev else True
    out, t0 = [], m
    for r in rows:
        st = r["event"].split("→")[-1].strip() == "가동"
        if st != run:
            out.append((t0, r["ts"], run))
            t0, run = r["ts"], st
    out.append((t0, None, run))
    return out, last_id


def _segments(m, now, runs):
    """τ 계산용 구간 [(t0, t1, 배속)] — 컨베이어 정지 = 0, 빨리감기 = k, 평소 = 1"""
    cuts = {m}
    for a, b, _ in runs:
        cuts.add(max(a, m))
        if b:
            cuts.add(b)
    for f in _ff:
        cuts.add(max(f[0], m))
        if f[1]:
            cuts.add(f[1])
    pts = sorted(t for t in cuts if t >= m)
    segs = []
    for i, a in enumerate(pts):
        b = pts[i + 1] if i + 1 < len(pts) else None
        mid = (a + (b if b else a + 1)) / 2
        run = next((r for x, y, r in runs if x <= mid and (y is None or mid < y)), True)
        k = next((f[2] for f in _ff if f[0] <= mid and (f[1] is None or mid < f[1])), 1.0)
        segs.append([a, b, (k if run else 0.0)])
    tau = 0.0
    for s in segs:                      # 각 구간 시작의 τ
        s.append(tau)
        if s[1]:
            tau += (s[1] - s[0]) * s[2]
    return segs


def _rate(segs, t):
    for a, b, k, t0 in reversed(segs):
        if t >= a:
            return k
    return 1.0


def _tau(segs, t):
    for a, b, k, t0 in reversed(segs):
        if t >= a:
            end = min(t, b) if b else t
            return t0 + (end - a) * k
    return 0.0


# ---------------------------------------------------------------- 상자 일정 계산
def _schedule(rows, segs, day):
    prods, events = [], []
    oks = []
    prev_end, move = None, MOVE
    for r in rows:
        tv = _tau(segs, r["ts"])
        nws = prev_end + move if prev_end is not None else None
        ws = nws if nws is not None and tv - nws <= IDLE_GAP else tv - INSPECT      # 검사기에 들어온 순간
        lag = ws - tv                                                               # 기록이 검사기보다 앞선 정도
        if lag > LAG_RESET:
            ws = tv - INSPECT_FAST
        fast = lag > LAG_FAST
        we = max(ws + (INSPECT_FAST if fast else INSPECT), tv)                      # 검사기를 떠나는 순간
        move = MOVE_FAST if fast else MOVE
        prev_end = we
        p = {"id": r["id"], "ok": r["result"] != "불량", "type": r["defect_type"] or "", "tv": round(tv, 3),
             "ws": round(ws, 3), "we": round(we, 3), "tj": round(min(max(tv, ws + REVEAL_MIN), we), 3)}
        if p["ok"]:
            p["arr"] = round(we + D_END, 3)
            oks.append(p)
        else:
            p["tdiv"] = round(we + D_DIV, 3)
            p["tbin"] = round(we + D_DIV + D_CHUTE, 3)
            events.append((p["tbin"], "bin", p["id"]))
        prods.append(p)
    robot_free, fork_free, j = -1e9, -1e9, 0
    placed = 0
    on_truck = 0
    for i, p in enumerate(oks):
        s0 = max(robot_free, p["arr"] - GRAB * RC)
        while j < len(oks) and oks[j]["arr"] <= s0 + GRAB * RC:   # 이 상자를 집으러 갈 때 이미 벨트 끝에 와 있는 상자 수
            j += 1
        queue = max(0, j - i - 1)
        rc = RC_FAST if queue >= Q_FAST else RC
        s = max(robot_free, p["arr"] - GRAB * rc)
        p.update(s=round(s, 3), rc=rc, tp=round(s + GRAB * rc, 3), tpl=round(s + PLACE * rc, 3))
        robot_free = s + rc
        seq = placed // LOT + 1
        p["lot"] = f"{day}-{seq:02d}"
        p["slot"] = placed % PALLET
        events.append((p["tpl"], "place", p["id"]))
        placed += 1
        if placed % PALLET == 0:                                  # 팔레트 완성 → 지게차
            f0 = max(p["tpl"], fork_free)
            fork_free = f0 + FORK_SEC
            events.append((round(f0, 3), "fork", seq))
            events.append((round(f0 + FORK_DROP, 3), "drop", seq))
            on_truck += 1
            if on_truck == TRUCK:                                 # 10팔레트째 → 트럭 출발
                on_truck = 0
                events.append((round(f0 + FORK_DROP + 0.01, 3), "depart", f"{day}-{seq:02d}"))
                events.append((round(f0 + FORK_DROP + DEPART_EMPTY, 3), "empty", seq))
    events.sort(key=lambda e: e[0])
    return prods, events


def _counts(events, tau, day):
    c = {"placed": 0, "bin": 0, "onTruck": 0, "trucks_out": 0, "departing": False, "fork_busy": False}
    last_depart = None
    for at, kind, ref in events:
        if at > tau:
            break
        if kind == "place":
            c["placed"] += 1
        elif kind == "bin":
            c["bin"] += 1
        elif kind == "drop":
            c["onTruck"] += 1
        elif kind == "depart":
            c["trucks_out"] += 1
            last_depart = (at, ref)
        elif kind == "empty":
            c["onTruck"] = 0
    if last_depart and tau < last_depart[0] + DEPART_EMPTY:
        c["departing"] = True
        c["onTruck"] = TRUCK
    c["fill"] = c["placed"] % PALLET
    seq = c["trucks_out"] + 1 - (1 if c["departing"] else 0)
    c["lot_seq"] = seq
    c["lot"] = f"{day}-{seq:02d}"
    return c


def _build(now):
    m = _midnight(now)
    day = datetime.date.fromtimestamp(now).strftime("%Y%m%d")
    runs, ev_id = _conveyor_runs(m, now)
    with db._lock, db._conn() as c:
        last = c.execute("SELECT MAX(id) FROM inspections").fetchone()[0]
    ffkey = tuple((round(f[0], 2), f[1] and round(f[1], 2), f[2]) for f in _ff)
    key = (day, last, ev_id, ffkey)
    if _cache.get("key") == key:
        return _cache
    with db._lock, db._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, ts, result, defect_type FROM inspections WHERE ts >= ? ORDER BY ts, id", (m,))]
    segs = _segments(m, now, runs)
    prods, events = _schedule(rows, segs, day)
    last_we = prods[-1]["we"] if prods else None      # (마지막 상자가 빠른 검사였어도 다음 상자는 보통 이동 시간 기준)
    _cache.update(key=key, m=m, day=day, runs=runs, segs=segs, prods=prods, events=events, last_we=last_we, last_id=last)
    return _cache


def _next_ws(b, tau):
    """다음 (아직 기록 없는) 상자가 검사기에 들어오는 τ — 없으면 None (라인이 오래 비어 있음)"""
    nws = b["last_we"] + MOVE if b.get("last_we") is not None else None
    if nws is not None and tau - nws <= IDLE_GAP:
        return nws
    if _anchor["ws"] is not None and _anchor["last"] == b.get("last_id"):
        return _anchor["ws"]
    return None


def next_due(now=None):
    """시뮬레이터용: (지금 τ, 지금 검사 중인 상자의 검사가 끝나는 τ, 배속, 그 순간의 실제 시각)
    라인이 오래 비었으면 지금 투입한 상자가 검사기에 들어오는 시각부터 새로 시작"""
    now = now or time.time()
    with _lock:
        b = _build(now)
        tau, rate = _tau(b["segs"], now), _rate(b["segs"], now)
        ws = _next_ws(b, tau)
        if ws is None:
            _anchor.update(ws=tau + D_PRE + MOVE, last=b.get("last_id"))
            ws = _anchor["ws"]
    due = ws + INSPECT
    # 판정은 검사가 끝나기 VERDICT_LEAD초 전에 기록 → 화면이 기록을 받은 뒤에 상자가 검사기를 떠남 (기록이 늦어 상자가 튀지 않게)
    #   기록 시각(tv)이 검사 구간 안이라 장부의 we = ws + INSPECT 그대로 (박자 변화 없음) · 결과는 tv에 보임
    write_at = due - VERDICT_LEAD
    real = now if rate > 0 and tau >= write_at else None
    return tau, due, rate, real


def flow(now=None):
    now = now or time.time()
    with _lock:
        for f in _ff:                                              # 빨리감기 시간 초과
            if f[1] is None and now > f[4]:
                f[1] = now
        b = _build(now)
        segs = b["segs"]
        tau = _tau(segs, now)
        rate = _rate(segs, now)
        # 빨리감기 목표 LOT이 출발했으면 끝
        ff = next((f for f in _ff if f[1] is None), None)
        if ff:
            done = False
            if ff[3]:
                done = any(e[1] == "depart" and e[2] == f"{b['day']}-{int(ff[3]):02d}" and e[0] <= tau for e in b["events"])
            if len(ff) > 5 and ff[5] is not None:
                done = done or sum(1 for e in b["events"] if e[1] == "place" and e[0] <= tau) >= ff[5]
            if len(ff) > 6 and ff[6] is not None:
                done = done or len(b["prods"]) >= ff[6]
            if done:
                ff[1] = now
                _cache["key"] = None
                b = _build(now)
                segs = b["segs"]
                tau = _tau(segs, now)
                rate = _rate(segs, now)
                ff = None
    prods = b["prods"]
    live = [p for p in prods if p["tv"] <= tau + 3 and (p.get("tpl", p.get("tbin", 0)) >= tau - 1.5)]
    ev = [{"at": e[0], "kind": e[1], "ref": e[2]} for e in b["events"] if tau - 8 <= e[0] <= tau + 15]
    counts = _counts(b["events"], tau, b["day"])
    queue = sum(1 for p in live if p["ok"] and p["arr"] <= tau < p["tp"])
    belt = sum(1 for p in live if p["tv"] <= tau and (p["ok"] and tau < p["arr"] or not p["ok"] and tau < p["tdiv"]))
    good_db = sum(1 for p in prods if p["ok"])
    # 아직 검사 기록이 없는 다음 상자 4개 (골판지색 · 번호 없음): 검사기 안(검사 중) 또는 검사기로 오는 중
    ws0 = _next_ws(b, tau)
    pred = []
    if ws0 is not None:
        we0 = ws0 + INSPECT if tau <= ws0 + INSPECT else tau                         # 판정이 늦으면 계속 검사기 안
        pred = [round(ws0, 3)]
        nxt = we0 + MOVE
        while len(pred) < 4:                      # 투입~검사기까지 가는 동안 벨트 위에 있을 상자까지 (벨트 처음부터 보이게)
            pred.append(round(nxt, 3)); nxt += INSPECT + MOVE
    run_now = next(((x, y, rr) for x, y, rr in b["runs"] if x <= now and (y is None or now < y)), b["runs"][-1])
    conv = next((e for e in db.get_equipment() if e["name"] == CONVEYOR), {})
    return {
        "now": now, "tau": round(tau, 3), "rate": rate, "day": b["day"],
        "const": {"INSPECT": INSPECT, "MOVE": MOVE, "D_PRE": D_PRE, "D_END": D_END, "D_DIV": D_DIV, "D_CHUTE": D_CHUTE, "GRAB": GRAB, "PLACE": PLACE,
                  "FORK_SEC": FORK_SEC, "FORK_DROP": FORK_DROP, "DEPART_EMPTY": DEPART_EMPTY, "PALLET": PALLET, "TRUCK": TRUCK, "CYCLE": CYCLE},
        "products": live, "events": ev, "pred": pred,
        "counts": {**counts, "queue": queue, "belt": belt, "good_db": good_db, "in_flight": good_db - counts["placed"]},
        "status": {"stopped": not run_now[2], "since": run_now[0] if not run_now[2] else None,
                   "reason": conv.get("reason", "") if not run_now[2] else "", "conveyor": conv.get("status", "가동"),
                   "ff": rate if ff_active() else None, "fast": any(p["ok"] and p.get("rc") == RC_FAST and p["s"] <= tau < p["s"] + p["rc"] for p in live)},
    }
