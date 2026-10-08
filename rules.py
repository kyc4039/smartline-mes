"""연동 규칙: 한 모듈의 결과가 다른 모듈에 영향을 주는 규칙 (0.5초마다 확인)
1) 품질 불량률이 기준 초과 → 정비 요청 알림
2) 라인 연동 정지: 컨베이어 외 설비가 하나라도 멈추면 컨베이어도 '연동 정지',
   모두 가동으로 돌아오면 컨베이어도 자동 재가동
   (컨베이어 자체 고장으로 멈춘 경우는 자동으로 풀지 않음)
(고장 보고 '즉시 조치' → 설비 정지는 maintenance.py에서 바로 처리)
"""
import threading
import time
import db
from config import DEFECT_RATE_LIMIT, DEFECT_WINDOW
from state import state

CONVEYOR = "컨베이어"
LINE_STOP = "연동 정지"     # 다른 설비 때문에 멈춘 상태 (컨베이어 자체 고장과 구분)


class RuleEngine(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="rules")
        self.defect_alert = False

    def start(self):
        super().start()
        # 시연용 생산 시뮬레이터도 같이 시작 (app.py를 고치지 않으려고 여기서 시작, 끄기: config.py DEMO_PRODUCTION = False)
        import demo_sim
        demo_sim.start()
        # 시연 모드 (10/07) · 카메라 자동 조절 (안전 카메라 우선) — app.py를 고치지 않으려고 여기서 시작
        import demo_mode
        demo_mode.start()
        from state import workers
        from camera_worker import start_balancer
        start_balancer(workers)
        from modules import maintenance                  # 설비 보전 AI 분류기 미리 불러오기 (첫 판정 대기 없앰)
        maintenance.preload()

    def run(self):
        while True:
            try:
                self.check_quality()
                self.check_line_interlock()
            except Exception as e:
                print(f"[rules] 오류: {e}")
            time.sleep(0.5)

    def check_quality(self):
        q = state.get("quality")
        over = q.get("window", 0) >= 10 and q.get("defect_rate", 0) > DEFECT_RATE_LIMIT
        if over and not self.defect_alert:
            db.log_event("rules", "불량률 기준 초과 → 정비 요청 필요", rate=q["defect_rate"])
        self.defect_alert = over
        state.update("alerts", maintenance_needed=over,
                     message=f"최근 {DEFECT_WINDOW}개 불량률 {q.get('defect_rate', 0):.1%} 기준 초과" if over else "")

    def check_line_interlock(self):
        eq = {e["name"]: e["status"] for e in db.get_equipment()}
        conv = eq.get(CONVEYOR)
        stopped = [n for n, st in eq.items() if n != CONVEYOR and st != "가동"]
        if stopped and conv == "가동":
            db.set_equipment(CONVEYOR, LINE_STOP, reason=f"{', '.join(stopped)} 정지로 라인 정지")
        elif not stopped and conv == LINE_STOP:
            db.set_equipment(CONVEYOR, "가동", reason="연동 해제")
