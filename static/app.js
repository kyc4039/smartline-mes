// SMART LINE MES v2 공통 스크립트

// 상태 문자열 → 톤 (색·모양 결정)
const OK = ["가동", "입장 허용", "정상", "승인", "RUN"];
const BAD = ["안전 정지", "고장 정지", "불량", "정지"];
const WARN = ["연동 정지", "착용 확인 중", "확인 유지 중", "검사 중", "유지 중"];
function tone(s) { return OK.includes(s) ? "ok" : BAD.includes(s) ? "bad" : WARN.includes(s) ? "warn" : "idle"; }
function shape(s) { return {ok: "●", warn: "▲", bad: "■", idle: "○"}[tone(s)]; }
const cls = s => "c-" + tone(s);               // 이전 화면 코드 호환
const hms = d => [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, "0")).join(":");
const time = ts => hms(new Date(ts * 1000));   // 브라우저·언어 설정과 관계없이 14:36:12 형식
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const pct = (a, b) => b ? Math.max(0, Math.min(100, a / b * 100)) : 0;

// 헤더: 라인 전체 상태와 시계
function updateHeader(d) {
  const pill = document.getElementById("linePill");
  if (!pill) return;
  const stopped = d.equipment.filter(e => e.status !== "가동");
  const hard = stopped.filter(e => tone(e.status) === "bad");
  let t = "ok", text = "전 설비 정상 가동";
  if (hard.length) { t = "bad"; text = `이상 발생 · 정지 설비 ${stopped.length}대`; }
  else if (stopped.length) { t = "warn"; text = `주의 · 정지 설비 ${stopped.length}대`; }
  pill.className = "pill t-" + t;
  pill.innerHTML = `<span aria-hidden="true">${{ok: "●", warn: "▲", bad: "■"}[t]}</span>${text}`;
}
function tickClock() { const c = document.getElementById("clock"); if (c) c.textContent = hms(new Date()); }
document.addEventListener("DOMContentLoaded", tickClock);   // 페이지가 뜨자마자 시각 표시 (1초 기다리지 않음)
setInterval(tickClock, 1000);

// 1초마다 /api/state를 받아 헤더와 페이지를 갱신
function poll(render, ms = 1000) {
  const tick = () => fetch("/api/state").then(r => r.json()).then(d => { updateHeader(d); demoUpdate(d); dangerAlert(d); render(d); }).catch(() => {});
  tick(); setInterval(tick, ms);
}

// 기간 선택 버튼 (이번 교대 / 오늘 / 어제 교대) — 주소의 ?range= 값과 연결
const RANGES = [["shift", "이번 교대"], ["today", "오늘"], ["prev", "어제 교대"]];
function currentRange() { return new URLSearchParams(location.search).get("range") || "shift"; }
function rangeButtons(el, onChange) {
  const draw = () => el.innerHTML = RANGES.map(([k, n]) =>
    `<button class="btn ${k === currentRange() ? "on" : ""}" data-r="${k}">${n}</button>`).join("");
  el.onclick = e => { const b = e.target.closest("[data-r]"); if (!b) return;
    history.replaceState(null, "", "?range=" + b.dataset.r); draw(); onChange(); };
  draw();
}
// 걸린 시간 (초) → 1분 미만은 "45초", 그 이상은 분으로만 "20분", "61분"
const mins = s => { if (s == null) return "-"; s = Math.round(s);
  if (s === 0) return "0분";
  return s < 60 ? `${s}초` : `${Math.round(s / 60)}분`; };
const hm = ts => hms(new Date(ts * 1000)).slice(0, 5);
const pctTxt = v => v == null ? "-" : (v * 100).toFixed(1) + "%";


// ======================================================================
// 프레스 위험 경고 (모든 페이지 공통) — 화면 전체에 색을 깔고, 위쪽 가운데에 안내 카드를 띄운다
//   빨강 (안전 정지): 화면 전체가 빨갛게 물들고 테두리가 깜빡임
//     - 위험구역에 손이 보일 때 : "손을 빼고 기계에서 떨어지세요" (재가동 시간은 멈춤)
//     - 구역이 비었을 때        : "N초 후 다시 작동합니다" (카운트다운)
//     - 비상 정지 버튼          : "관리자 수동 재가동 필요" (자동 재가동 없음)
//   노랑 (경고구역 접근): 정지는 아니지만 위험구역 가까이에 손이 보임 → 화면 전체가 노랗게, 짧은 알림음
//   노랑 · 깜빡임 없음 (정비 잠금 중): 프레스 기동 금지 안내
//   경고는 화면 조작을 막지 않는다 (클릭은 그대로 됨).
// ======================================================================
const ALERT_SOUND = true;    // 경고가 처음 뜰 때 짧은 경고음 (브라우저가 막으면 조용히 넘어감)
let dangerEl = null, dangerUntil = null, dangerMode = null;

function dangerBuild() {
  dangerEl = document.createElement("div");
  dangerEl.className = "dg-alert"; dangerEl.hidden = true;
  dangerEl.setAttribute("role", "alert");
  dangerEl.innerHTML = `<div class="dg-tint"></div><div class="dg-frame"></div>
    <div class="dg-card">
      <div class="dg-ic" aria-hidden="true">⚠</div>
      <div class="dg-txt"><div class="t1" id="dangerT1"></div><div class="t2" id="dangerT2"></div></div>
      <div class="dg-cd"><div class="n" id="dangerN"></div><div class="u" id="dangerU"></div></div>
    </div>`;
  document.body.appendChild(dangerEl);
  setInterval(dangerTick, 100);     // 1초 간격 상태 사이를 0.1초 단위로 부드럽게 카운트다운
}

function dangerTick() {
  if (dangerMode !== "stop" || dangerUntil == null) return;
  const left = Math.max(0, dangerUntil - Date.now() / 1000), n = document.getElementById("dangerN");
  if (n) n.textContent = left.toFixed(1);
}

function dangerBeep(freq = 880, times = [0, 0.28]) {
  if (!ALERT_SOUND) return;
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    times.forEach(t => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = "square"; o.frequency.value = freq; g.gain.value = 0.06;
      o.connect(g); g.connect(ac.destination);
      o.start(ac.currentTime + t); o.stop(ac.currentTime + t + 0.18);
    });
  } catch (e) { /* 소리를 못 내도 경고 화면은 그대로 */ }
}

function dangerAlert(d) {
  const s = (d.modules || {}).safety || {};
  if (!dangerEl) dangerBuild();
  const mode = s.status === "안전 정지" ? (s.hold === "lock" ? "lock" : "stop") : s.warn ? "warn" : null;
  if (!mode) { dangerEl.hidden = true; dangerMode = null; dangerUntil = null; return; }
  if (mode !== dangerMode) {
    if (mode === "stop") dangerBeep();
    else if (mode === "warn") dangerBeep(660, [0]);
  }
  dangerMode = mode;
  dangerEl.hidden = false;
  const hit = mode === "stop" && s.zone_clear === false;
  dangerEl.className = "dg-alert " + (mode === "stop" ? "" : mode === "warn" ? "warn" : "warn lock") + (hit ? " hit" : "");
  const t1 = document.getElementById("dangerT1"), t2 = document.getElementById("dangerT2");
  const n = document.getElementById("dangerN"), u = document.getElementById("dangerU");
  const ic = dangerEl.querySelector(".dg-ic");
  ic.textContent = mode === "lock" ? "🔒" : "⚠";
  if (mode === "warn") {
    const c = s.det && s.det.cls ? ` (${s.det.name || s.det.cls})` : "";
    t1.textContent = "위험구역에 가까워요 — 손을 멀리 하세요";
    t2.textContent = `경고구역에서 감지${c}. 위험구역에 들어가면 프레스가 바로 멈춥니다.`;
    dangerUntil = null; n.textContent = (s.warn_sec || 0).toFixed(1); u.textContent = "초째 접근";
  } else if (mode === "lock") {
    t1.textContent = `정비 잠금 중 — 프레스 기동 금지`;
    t2.textContent = `${s.lock_by || "작업자"}님이 정비 중입니다. 잠금 해제는 설비 안전 제어 페이지에서 (관리자 PIN).`;
    dangerUntil = null; n.textContent = "LOCK"; u.textContent = "정비 중";
  } else if (s.hold === "estop") {
    t1.textContent = "비상 정지 — 프레스가 멈췄습니다";
    t2.textContent = "자동으로 다시 켜지지 않습니다. 안전을 확인한 뒤 관리자가 수동 재가동하세요.";
    dangerUntil = null; n.textContent = "E-STOP"; u.textContent = "수동 재가동 필요";
  } else if (hit) {
    const what = s.det && s.det.cls ? (s.det.name || s.det.cls) : "손";
    t1.textContent = `프레스 위험구역에 ${what}${/[가-힣]$/.test(what) && (what.charCodeAt(what.length - 1) - 44032) % 28 ? "이" : "가"} 감지되었습니다`;
    t2.textContent = "즉시 손·공구를 빼고 기계에서 떨어지세요. 보이는 동안 프레스는 멈춰 있습니다.";
    dangerUntil = null; n.textContent = "STOP"; u.textContent = "정지 유지";
  } else {
    t1.textContent = "위험 감지 — 기계에서 떨어지세요";
    t2.textContent = "위험구역이 계속 비어 있으면 프레스가 자동으로 다시 작동합니다.";
    if (s.auto_release_in != null) { dangerUntil = Date.now() / 1000 + s.auto_release_in; dangerTick(); }
    u.textContent = "초 후 재가동";
  }
}


// ======================================================================
// 시연 모드 (모든 페이지 공통, 10/07)
//   - 시연 중: 화면 맨 위 노란 줄무늬 + 상단 상태 표시가 "▶ 시연 모드 · 3/8"
//   - Shift + D: 작은 리모컨 (다음 단계 · 자주 쓰는 이벤트 9개 · 모두 원래대로)
//   - '단계마다 화면 자동 이동'을 켜면 시나리오 단계가 바뀔 때 추천 화면으로 이동
// ======================================================================
const DEMO_QUICK = [["warn_tool", "▲", "경고 접근", "y"], ["hit_hand", "■", "손 침입", "r"], ["estop", "■", "비상 정지", "r"],
  ["defect_marked", "■", "흠집 불량", "r"], ["defect_crushed", "■", "찌그러짐", "r"], ["conveyor_fault", "■", "설비 고장", "r"],
  ["pallet", "▣", "팔레트 +1", "b"], ["truck", "🚚", "트럭 출발", "b"], ["maint_done", "●", "정비 완료", "g"]];
let demoEl = null, demoS = {}, demoLastIdx = null;
const DEMO_PAGE = {"/gate?preview=1": "안전 게이트", "/": "관제 대시보드", "/twin": "디지털 트윈", "/quality": "품질 관리", "/maintenance": "설비 보전", "/oee": "OEE",
  "/safety": "설비 안전 제어", "/production": "생산 관리"};
const demoGet = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
const demoSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

function demoPost(url, body) {
  return fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})})
    .then(r => r.json().then(j => { if (!r.ok) demoMsg(j.msg || "실패"); return j; })).catch(() => demoMsg("서버 연결 실패"));
}
function demoMsg(t) {
  const m = demoEl && demoEl.querySelector(".dr-msg");
  if (m) { m.textContent = t; m.hidden = false; clearTimeout(demoMsg.t); demoMsg.t = setTimeout(() => m.hidden = true, 3000); }
}
function demoUpdate(d) {
  const m = (d.modules || {}).demo || {};
  demoS = m;
  document.body.classList.toggle("demo-on", !!m.on);
  if (m.on) {
    const pill = document.getElementById("linePill");
    if (pill) {
      const stopped = d.equipment.filter(e => e.status !== "가동").length;
      pill.className = "pill demo";
      pill.innerHTML = `<span aria-hidden="true">▶</span>시연 모드${m.idx >= 0 ? ` · ${m.idx + 1}/${m.n}` : ""}${stopped ? ` · 정지 ${stopped}대` : ""}`;
    }
    if (demoLastIdx !== null && m.idx !== demoLastIdx && m.idx >= 0 && demoGet("demo_nav", "0") === "1"
        && m.page && location.pathname !== m.page) { location.href = m.page; return; }
    demoLastIdx = m.idx;
  } else demoLastIdx = null;
  if (demoGet("demo_remote", "0") === "1") { if (!demoEl) demoBuild(); demoEl.hidden = false; demoDraw(); }
}
function demoBuild() {
  demoEl = document.createElement("div");
  demoEl.className = "demo-remote"; demoEl.setAttribute("aria-label", "시연 리모컨");
  document.body.appendChild(demoEl);
  demoEl.addEventListener("click", e => {
    const b = e.target.closest("[data-ev],[data-sc],[data-act]"); if (!b) return;
    if (b.dataset.ev) demoPost("/api/demo/trigger", {id: b.dataset.ev});
    else if (b.dataset.sc) demoPost("/api/demo/scenario", {cmd: b.dataset.sc});
    else if (b.dataset.act === "reset") demoPost("/api/demo/reset");
    else if (b.dataset.act === "close") { demoSet("demo_remote", "0"); demoEl.hidden = true; }
  });
  demoEl.addEventListener("change", e => { if (e.target.name === "nav") demoSet("demo_nav", e.target.checked ? "1" : "0"); });
}
function demoDraw() {
  const m = demoS, nav = demoGet("demo_nav", "0") === "1";
  if (!m.on) {
    demoEl.innerHTML = `<div class="dr-h"><b>▶ 시연 리모컨</b><button class="dr-x" data-act="close" aria-label="닫기">✕</button></div>
      <div class="small muted">시연 모드가 꺼져 있어요.</div><a class="btn" href="/demo">시연 제어판에서 켜기 →</a>`;
    return;
  }
  const cur = m.idx >= 0 ? `<div class="dr-cur"><span>지금 ${m.idx + 1}/${m.n}</span> ${esc(m.title)}</div>` : "";
  const nextN = m.idx + 2 <= m.n ? (m.idx < 0 ? 1 : m.idx + 2) : null;
  demoEl.innerHTML = `<div class="dr-h"><b>▶ 시연 리모컨</b><span class="small muted">Shift+D</span><button class="dr-x" data-act="close" aria-label="닫기">✕</button></div>
    <div class="dr-next">${cur}
      ${nextN ? `<div class="s">다음 단계 ${nextN}/${m.n} · ${esc(DEMO_PAGE[m.next_page] || m.next_page || "")} 화면</div><b>${esc(m.next || "")}</b>` : `<b>시나리오 끝 · 처음부터 다시 가능</b>`}
      <div class="dr-ctl">${m.running ? '<button class="btn" data-sc="pause" title="일시정지">⏸</button>' : '<button class="btn" data-sc="play" title="자동 재생">▶</button>'}
        <button class="btn primary" data-sc="${nextN ? "next" : "start"}">⏭ ${nextN ? "다음 단계 실행" : "처음부터"}</button></div></div>
    <div class="small muted">바로 실행</div>
    <div class="dr-bt">${DEMO_QUICK.map(([id, ic, nm, lv]) => `<button class="${lv}" data-ev="${id}"><i>${ic}</i>${nm}</button>`).join("")}</div>
    <label class="dr-nav"><input type="checkbox" name="nav" ${nav ? "checked" : ""}> 단계마다 추천 화면으로 자동 이동</label>
    <div class="dr-ctl"><a class="btn" href="/demo">시연 제어판 →</a><button class="btn warn" data-act="reset">■ 모두 원래대로</button></div>
    <div class="dr-msg small c-bad" hidden></div>`;
}
document.addEventListener("keydown", e => {
  if (!(e.shiftKey && (e.key === "D" || e.key === "d"))) return;
  if (/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "")) return;
  const open = demoGet("demo_remote", "0") !== "1";
  demoSet("demo_remote", open ? "1" : "0");
  if (!demoEl) demoBuild();
  demoEl.hidden = !open; if (open) demoDraw();
});
