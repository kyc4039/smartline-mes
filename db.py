"""SQLite DB: 이벤트 로그, 설비 상태, 정비 티켓
- 매 프레임이 아니라 '상태가 바뀔 때만' 기록한다.
"""
import json
import sqlite3
import threading
import time
from config import DB_PATH, EQUIPMENT

_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, module TEXT, event TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS equipment (
            name TEXT PRIMARY KEY, status TEXT, reason TEXT, updated REAL);
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, equipment TEXT, text TEXT,
            type TEXT, urgency TEXT, need_review INTEGER, status TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, result TEXT, defect_type TEXT);
        CREATE TABLE IF NOT EXISTS notes (key TEXT PRIMARY KEY, text TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, ticket_id INTEGER UNIQUE, equipment TEXT, text TEXT,
            ai_type TEXT, ai_urgency TEXT, true_type TEXT, true_urgency TEXT, note TEXT);
        """)
        for name in EQUIPMENT:
            c.execute("INSERT OR IGNORE INTO equipment VALUES (?, '가동', '', ?)", (name, time.time()))
        # 검사 기록 출처: camera(품질 카메라 실제 판정) / sim(시연용 생산 시뮬레이터) — 예전 DB에는 칸을 추가
        cols = [r["name"] for r in c.execute("PRAGMA table_info(inspections)")]
        if "source" not in cols:
            c.execute("ALTER TABLE inspections ADD COLUMN source TEXT DEFAULT 'camera'")
        # AI 판정 상세 · 불량품 처리 칸 (예전 DB에는 추가만 하고, 예전 기록은 빈칸)
        #   conf: 신뢰도 / box: 검출 위치 [x1,y1,x2,y2] (화면 비율 0~1) / judge_sec: 판정에 걸린 시간 / model: 모델 파일
        #   disposition: 불량품 처리 (격리 / 불량 확인 / 오판 / 정비 요청 #번호) / disp_ts: 처리 시각
        for col, typ in [("conf", "REAL"), ("box", "TEXT"), ("judge_sec", "REAL"), ("model", "TEXT"),
                         ("disposition", "TEXT DEFAULT ''"), ("disp_ts", "REAL")]:
            if col not in cols:
                c.execute(f"ALTER TABLE inspections ADD COLUMN {col} {typ}")
        # 정비 티켓 진행 (10/07): 상태 '대기' → '조치 중'(담당자 · 시작 시각) → '완료'(완료 시각)
        tcols = [r["name"] for r in c.execute("PRAGMA table_info(tickets)")]
        for col, typ in [("assignee", "TEXT DEFAULT ''"), ("started", "REAL"), ("done_ts", "REAL"), ("action", "TEXT DEFAULT ''")]:
            if col not in tcols:
                c.execute(f"ALTER TABLE tickets ADD COLUMN {col} {typ}")


def log_event(module, event, **detail):
    with _lock, _conn() as c:
        c.execute("INSERT INTO events (ts, module, event, detail) VALUES (?, ?, ?, ?)",
                  (time.time(), module, event, json.dumps(detail, ensure_ascii=False)))


def set_equipment(name, status, reason=""):
    with _lock, _conn() as c:
        row = c.execute("SELECT status FROM equipment WHERE name = ?", (name,)).fetchone()
        if row and row["status"] == status:
            return False                      # 바뀐 게 없으면 기록하지 않음
        if row:      # UPDATE로 바꿔야 설비 순서(rowid)가 유지됨 (REPLACE는 행을 지웠다 다시 넣어 순서가 섞임)
            c.execute("UPDATE equipment SET status = ?, reason = ?, updated = ? WHERE name = ?",
                      (status, reason, time.time(), name))
        else:
            c.execute("INSERT INTO equipment VALUES (?, ?, ?, ?)", (name, status, reason, time.time()))
        c.execute("INSERT INTO events (ts, module, event, detail) VALUES (?, ?, ?, ?)",
                  (time.time(), "equipment", f"{name} → {status}", json.dumps({"reason": reason}, ensure_ascii=False)))
        return True


def get_equipment():
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM equipment ORDER BY rowid")]


def recent_events(n=20):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,))]


def create_ticket(equipment, text, result):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO tickets (ts, equipment, text, type, urgency, need_review, status, result) "
            "VALUES (?, ?, ?, ?, ?, ?, '대기', ?)",
            (time.time(), equipment, text, result["type"], result["urgency"], int(result["need_review"]),
             json.dumps(result, ensure_ascii=False)))
        return cur.lastrowid


def list_tickets(n=30):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (n,))]


def get_ticket(tid):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
        return dict(r) if r else None


def complete_ticket(tid, action=""):
    """정비 완료 (action: 한 조치 메모 → 다음 비슷한 고장 때 '비슷한 지난 정비'로 보여 줌)"""
    with _lock, _conn() as c:
        c.execute("UPDATE tickets SET status = '완료', done_ts = ?, action = ? WHERE id = ?", (time.time(), action, tid))


def start_ticket(tid, who):
    """정비 시작: 대기 → 조치 중 (담당자 · 시작 시각)"""
    with _lock, _conn() as c:
        c.execute("UPDATE tickets SET status = '조치 중', assignee = ?, started = ? WHERE id = ? AND status != '완료'",
                  (who, time.time(), tid))


def open_urgent_tickets(equipment):
    """해당 설비에 아직 완료되지 않은 즉시 조치 티켓 수"""
    with _lock, _conn() as c:
        return c.execute("SELECT COUNT(*) FROM tickets WHERE equipment = ? AND urgency = '상' AND status != '완료'",
                         (equipment,)).fetchone()[0]


# ---------- 디지털 트윈: 설비별 상세 ----------
def equipment_detail(name, since_ts, n_events=6):
    """설비 하나의 오늘 정지 횟수, 관련 최근 이벤트, 미완료 정비 요청"""
    like = f"%{name}%"
    with _lock, _conn() as c:
        stops = c.execute(
            "SELECT COUNT(*) FROM events WHERE module = 'equipment' AND ts >= ? "
            "AND event LIKE ? AND event NOT LIKE '% → 가동'", (since_ts, f"{name} → %")).fetchone()[0]
        events = [dict(r) for r in c.execute(
            "SELECT * FROM events WHERE event LIKE ? OR detail LIKE ? ORDER BY id DESC LIMIT ?",
            (like, like, n_events))]
        tickets = [dict(r) for r in c.execute(
            "SELECT id, ts, text, type, urgency, status FROM tickets WHERE equipment = ? AND status != '완료' "
            "ORDER BY id DESC", (name,))]
    return {"stops_today": stops, "events": events, "tickets": tickets}


def open_tickets():
    """아직 완료되지 않은 정비 요청 전체 (트윈 '정비 요청' 레이어용)"""
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT id, ts, equipment, urgency, status FROM tickets WHERE status != '완료'")]


def events_since(since_ts):
    """since_ts 이후 이벤트를 시간 순서대로 (사건 묶기용)"""
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM events WHERE ts >= ? ORDER BY id", (since_ts,))]


# ---------- 정비원 피드백 (AI 판정이 맞았는지) ----------
def save_feedback(ticket, true_type, true_urgency, note=""):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO feedback (ts, ticket_id, equipment, text, ai_type, ai_urgency, "
                  "true_type, true_urgency, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (time.time(), ticket["id"], ticket["equipment"], ticket["text"], ticket["type"], ticket["urgency"],
                   true_type, true_urgency, note))


def all_feedback():
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM feedback ORDER BY id")]


# ---------- 설비 분석 (타임라인·OEE·교대 보고서) ----------
def equipment_events_until(until_ts):
    """설비 상태 변경 기록 전체 (구간 계산용, 시간 순서)"""
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM events WHERE module = 'equipment' AND ts <= ? ORDER BY id", (until_ts,))]


def add_inspection(result, defect_type="", source="camera", conf=None, box=None, judge_sec=None, model=None, ts=None):
    """검사 결과 1건 저장 → 번호(id) 돌려줌 (불량 사진 파일 이름에 사용)
    source: camera(품질 카메라) / sim(시연용 생산 시뮬레이터, demo_sim.py)
    conf · box · judge_sec · model: AI 판정 상세 (품질 검사 페이지에 표시)
    ts: 판정 시각 (없으면 지금) — 시뮬레이터가 검사기 5초 검사가 끝난 정확한 순간으로 기록할 때 사용"""
    with _lock, _conn() as c:
        # 불량은 판정과 동시에 분기 컨베이어로 불량함에 빠지므로 처리 상태 = '자동 격리' (사람은 확인만)
        cur = c.execute("INSERT INTO inspections (ts, result, defect_type, source, conf, box, judge_sec, model, disposition, disp_ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (ts or time.time(), result, defect_type, source, conf,
                         json.dumps([round(v, 3) for v in box]) if box else None, judge_sec, model,
                         "자동 격리" if result == "불량" else "", time.time() if result == "불량" else None))
        return cur.lastrowid


def get_inspection(iid):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM inspections WHERE id = ?", (iid,)).fetchone()
        return dict(r) if r else None


def latest_inspection(defect_only=False):
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM inspections" + (" WHERE result = '불량'" if defect_only else "") +
                      " ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None


def set_disposition(iid, disposition):
    """불량품 처리 기록 (격리 / 불량 확인 / 오판 / 정비 요청 #번호)"""
    with _lock, _conn() as c:
        c.execute("UPDATE inspections SET disposition = ?, disp_ts = ? WHERE id = ?", (disposition, time.time(), iid))


def last_inspection_ts(source):
    """출처별 마지막 검사 시각 (없으면 None)"""
    with _lock, _conn() as c:
        return c.execute("SELECT MAX(ts) FROM inspections WHERE COALESCE(source, 'camera') = ?", (source,)).fetchone()[0]


def count_inspections(source):
    with _lock, _conn() as c:
        return c.execute("SELECT COUNT(*) FROM inspections WHERE COALESCE(source, 'camera') = ?", (source,)).fetchone()[0]


def delete_sim_inspections():
    """시연용 시뮬레이터가 넣은 검사 기록만 지움 → 지운 개수"""
    with _lock, _conn() as c:
        return c.execute("DELETE FROM inspections WHERE source = 'sim'").rowcount


def defects_between(a, b, limit=200):
    """기간 안의 불량 검사 기록 (최신 순)"""
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM inspections WHERE result = '불량' AND ts >= ? AND ts < ? ORDER BY id DESC LIMIT ?", (a, b, limit))]


def inspections_between(a, b):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM inspections WHERE ts >= ? AND ts < ? ORDER BY id", (a, b))]


def tickets_between(a, b):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tickets WHERE ts >= ? AND ts < ? ORDER BY id", (a, b))]


def events_between(a, b, module=None):
    q, args = "SELECT * FROM events WHERE ts >= ? AND ts < ?", [a, b]
    if module:
        q += " AND module = ?"; args.append(module)
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id", args)]


def get_note(key):
    with _lock, _conn() as c:
        r = c.execute("SELECT text FROM notes WHERE key = ?", (key,)).fetchone()
        return r["text"] if r else ""


def set_note(key, text):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO notes VALUES (?, ?, ?)", (key, text, time.time()))
