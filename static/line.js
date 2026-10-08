// 관제 대시보드 공정 라인 애니메이션 (옆에서 본 그림)
//   디지털 트윈과 같은 박자: 제품 1개 = CYCLE(4초), 벨트 처음→끝 = TRAVEL(12초)
//   흐름: AMR 투입 → 프레스 → 비전 검사 → (불량은 밀어내 불량함) → 로봇이 팔레트에 적재 → 8개면 지게차 → 트럭 10팔레트면 출발
//   팔레트 · 트럭 숫자는 로봇이 상자를 내려놓는 순간에만 1씩 늘어남 (DB 양품 수를 목표로 따라감 → 트윈과 같은 규칙)
//   컨베이어가 멈추면(연동 정지 포함) 시계가 멈춰 전부 그 자리에 선다.
// 사용: LINE.state(/api/state 결과) 1초마다, LINE.data(/api/dashboard/summary 결과) 5초마다
const LINE = (() => {
  const CYCLE = 4, TRAVEL = 12, N = TRAVEL / CYCLE;
  const X0 = 222, X1 = 804, Y = 230;                 // 벨트 위 상자 왼쪽 x (처음 ~ 끝), 윗면 y
  const P_PRESS = (361 - X0) / (X1 - X0), P_VISION = (657 - X0) / (X1 - X0), P_DIVERT = (690 - X0) / (X1 - X0);
  const S = [872, 248], L1 = 76.6, L2 = 70.9;        // 로봇 어깨 · 팔 길이
  const PICK = [814, 196], LIFT = 160, PLACE_X = 985;
  const $ = id => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const wrap = (v, m) => ((v % m) + m) % m;
  const ease = t => t * t * (3 - 2 * t);
  const lerp = (a, b, t) => a + (b - a) * t;

  let t = 0, last = null, running = true, built = false;
  const ship = {size: 8, trucks: 10, target: null, shown: 0, onTruck: 0, live: false, lot: "-",
                fork: null, forkQ: 0, departNext: false, departing: false, defects: null, binN: 0};
  const prods = [];
  const skip = new Set();             // 불량으로 빠져서 로봇이 집을 상자가 없는 주기
  let pendingDefects = 0, armN = null, lastHold = false;

  function build() {
    const g = $("ln-prods"); if (!g) return false;
    for (let i = 0; i < N; i++) {
      const u = document.createElementNS(NS, "use");
      u.setAttribute("href", "#box"); g.appendChild(u);
      const red = document.createElementNS(NS, "rect");
      red.setAttribute("width", 22); red.setAttribute("height", 18); red.setAttribute("rx", 2); red.setAttribute("fill", "url(#gBad)");
      red.style.display = "none"; g.appendChild(red);
      prods.push({use: u, red, defect: false, gone: false});
    }
    built = true; return true;
  }

  // ---------------------------------------------------------------- 로봇 팔 (두 마디 · 팔꿈치 위)
  function ik(w) {
    let dx = w[0] - S[0], dy = w[1] - S[1], d = Math.hypot(dx, dy);
    d = Math.min(Math.max(d, Math.abs(L1 - L2) + 1), L1 + L2 - 0.5);
    const th = Math.atan2(dy, dx), a = Math.acos((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d));
    const e1 = [S[0] + L1 * Math.cos(th - a), S[1] + L1 * Math.sin(th - a)];
    const e2 = [S[0] + L1 * Math.cos(th + a), S[1] + L1 * Math.sin(th + a)];
    return e1[1] < e2[1] ? e1 : e2;
  }
  function placeAt() { const k = ship.shown % ship.size, layer = Math.floor(Math.min(k, 7) / 4); return [PLACE_X, 216 - layer * 18]; }
  // 한 주기 안의 동작 [시작, 끝, 출발점, 도착점, 들고 있나] (u = 0 에 벨트 끝의 상자를 집음)
  function armAt(u, idle) {
    const pl = placeAt(), up = p => [p[0], LIFT];
    const M = idle ? [[0, 4, up(PICK), up(PICK), false]] : [
      [0.0, 0.4, PICK, PICK, true], [0.4, 0.9, PICK, up(PICK), true], [0.9, 1.7, up(PICK), up(pl), true],
      [1.7, 2.1, up(pl), pl, true], [2.1, 2.3, pl, pl, false], [2.3, 2.8, pl, up(pl), false],
      [2.8, 3.6, up(pl), up(PICK), false], [3.6, 4.0, up(PICK), PICK, false]];
    const m = M.find(v => u >= v[0] && u < v[1]) || M[M.length - 1];
    const k = ease(Math.min(1, (u - m[0]) / (m[1] - m[0])));
    return {w: [lerp(m[2][0], m[3][0], k), lerp(m[2][1], m[3][1], k)], hold: m[4]};
  }
  function drawArm(w, hold) {
    const e = ik(w), set = (id, a) => { const el = $(id); if (el) Object.entries(a).forEach(([k, v]) => el.setAttribute(k, v)); };
    ["ln-a1", "ln-a1b"].forEach(id => set(id, {x1: S[0], y1: S[1], x2: e[0].toFixed(1), y2: e[1].toFixed(1)}));
    ["ln-a2", "ln-a2b"].forEach(id => set(id, {x1: e[0].toFixed(1), y1: e[1].toFixed(1), x2: w[0].toFixed(1), y2: w[1].toFixed(1)}));
    set("ln-j1", {cx: e[0].toFixed(1), cy: e[1].toFixed(1)}); set("ln-j2", {cx: w[0].toFixed(1), cy: w[1].toFixed(1)});
    set("ln-grip", {transform: `translate(${w[0].toFixed(1)} ${w[1].toFixed(1)})`});
    const c = $("ln-cargo"); if (c) c.style.display = hold ? "" : "none";
  }

  // ---------------------------------------------------------------- 팔레트 · 지게차 · 트럭
  function drawPallet() {
    const g = $("ln-pallet"); if (!g) return;
    const n = ship.shown % ship.size;
    let h = "";
    for (let k = 0; k < ship.size; k++) {
      const x = 938 + (k % 4) * 24, y = 254 - Math.floor(k / 4) * 18;
      h += k < n ? `<use href="#box" x="${x}" y="${y}"/>` : `<rect x="${x}" y="${y}" width="22" height="18" rx="2" fill="none" stroke="#55646E" stroke-dasharray="3 3"/>`;
    }
    g.innerHTML = h;
    $("ln-pfill").textContent = `${n} / ${ship.size}`;
    const tc = $("ln-tcargo"); if (tc) {
      let s = "";
      for (let k = 0; k < ship.trucks; k++) {
        const col = k % 5, row = Math.floor(k / 5), on = ship.departing || k < ship.onTruck;
        s += `<rect x="${1168 + col * 14}" y="${248 - row * 22}" width="12" height="18" rx="2" fill="${on ? "url(#gBox)" : "#26323A"}"/>`;
      }
      tc.innerHTML = s;
    }
    $("ln-tnum").textContent = `${ship.departing ? ship.trucks : ship.onTruck} / ${ship.trucks}`;
  }
  function forkTrip() { if (ship.fork == null) { ship.fork = t; ship.dropped = false; } else ship.forkQ++; }
  function forkAt() {
    if (ship.fork == null) return [0, false];
    const u = t - ship.fork;
    if (u >= 1.6 && !ship.dropped) {
      ship.dropped = true; ship.onTruck = Math.min(ship.trucks, ship.onTruck + 1);
      if (ship.departNext && ship.onTruck >= ship.trucks) { ship.departNext = false; depart(); }
      drawPallet();
    }
    if (u >= 3.4) { if (ship.forkQ > 0) { ship.forkQ--; ship.fork = t; ship.dropped = false; } else ship.fork = null; return [0, false]; }
    if (u < 1.4) return [ease(u / 1.4), true];
    if (u < 1.8) return [1, u < 1.6];
    return [1 - ease((u - 1.8) / 1.6), false];
  }
  function depart() {
    const tr = $("ln-truck"); if (!tr || ship.departing) return;
    ship.departing = true; drawPallet();
    tr.animate([{transform: "translate(0,0)", opacity: 1}, {transform: "translate(260px,0)", opacity: 0, offset: .45},
                {transform: "translate(-120px,0)", opacity: 0, offset: .55}, {transform: "translate(0,0)", opacity: 1}],
               {duration: 5000, easing: "ease-in-out"});
    setTimeout(() => { ship.departing = false; ship.onTruck = 0; drawPallet(); }, 2500);
  }
  function addOne() {
    ship.shown++;
    if (ship.shown % ship.size === 0) {
      forkTrip();
      if (ship.shown % (ship.size * ship.trucks) === 0) ship.departNext = true;
    }
    drawPallet();
  }
  const pending = () => ship.live && ship.target != null ? ship.target - ship.shown : Infinity;
  function snap(n) {
    ship.shown = Math.max(0, n); ship.onTruck = Math.floor(ship.shown / ship.size) % ship.trucks;
    ship.fork = null; ship.forkQ = 0; ship.departNext = false; drawPallet();
  }

  // ---------------------------------------------------------------- 서버 숫자 받기
  function data(sum) {
    const p = sum && sum.prod; if (!p) return;
    ship.size = p.pallet_size; ship.trucks = p.truck_pallets; ship.lot = p.lot;
    if (flowOn()) return;                                        // 새 흐름: 숫자는 장부(FLOW)가 정함
    const fresh = p.last_insp && p.now - p.last_insp < 120, was = ship.live;
    ship.live = !!fresh;
    if (fresh) {
      ship.target = p.good_total;
      const gap = ship.target - ship.shown;
      if (!was || gap < 0 || gap > 6) snap(ship.target - 2);       // 2개 = 검사 후 벨트 위에 있는 제품
      if (ship.defects != null && p.defects_today > ship.defects) pendingDefects += Math.min(3, p.defects_today - ship.defects);
    } else ship.target = null;
    ship.defects = p.defects_today;
    if (!ship.binShown) { ship.binN = p.defects_today; ship.binShown = true; }
    if (ship.binN > p.defects_today) ship.binN = p.defects_today;    // 날짜가 바뀜
    $("ln-bin").textContent = ship.binN;
    drawPallet();
  }

  // ---------------------------------------------------------------- 설비 상태 (1초마다)
  const LAMP = {ok: 2, warn: 1, bad: 0, idle: -1};
  function state(d) {
    const eq = Object.fromEntries((d.equipment || []).map(e => [e.name, e]));
    const conv = eq["컨베이어"] || {};
    running = !conv.status || conv.status === "가동";
    document.querySelectorAll("#lnSvg .tw").forEach(g => {
      const e = eq[g.dataset.eq] || {}, on = LAMP[tone(e.status || "가동")];
      g.querySelectorAll("circle.l").forEach((c, i) => c.setAttribute("class", "l " + (i === on ? ["r", "y", "g"][i] : "off")));
    });
    const s = (d.modules || {}).safety || {}, press = eq["프레스 #1"] || {};
    const stop = press.status && press.status !== "가동";
    $("ln-zone").setAttribute("class", stop ? "zone on" : s.warn ? "zone warn" : "zone");
    $("ln-zlbl").textContent = stop ? `■ ${press.status} · ${press.reason || ""}` : s.warn ? "▲ 경고구역 접근" : "위험구역 감시 중";
    $("ln-zlbl").setAttribute("fill", stop ? "#FFB3B0" : s.warn ? "#FFD58A" : "#93A3AD");
    $("ln-hand").style.display = s.zone_clear === false || s.warn ? "" : "none";
    $("ln-beltdash").setAttribute("stroke", running ? "#3E4C56" : "#8A6A2A");
  }

  // ---------------------------------------------------------------- 1프레임
  function frame(now) {
    requestAnimationFrame(frame);
    if (!built && !build()) return;
    if (flowOn()) { flowFrame(); last = now; return; }
    if (pool) resetPool();
    if (last != null && running) t += Math.min(0.1, (now - last) / 1000);
    last = now;
    const u = wrap(t, CYCLE);

    // 벨트 위 상자
    prods.forEach((pr, i) => {
      const p = wrap(t - i * CYCLE, TRAVEL) / TRAVEL;
      if (p < 0.05 && (pr.defect || pr.gone)) { pr.defect = false; pr.gone = false; }      // 새 상자
      if (!pr.defect && pendingDefects > 0 && p > P_VISION - 0.04 && p < P_VISION) {      // 검사기 밑에서 불량 판정
        pr.defect = true; pendingDefects--;
        skip.add(Math.floor((t + (1 - p) * TRAVEL) / CYCLE + 0.5));
        $("ln-mon").textContent = "불량"; $("ln-mon").setAttribute("fill", "#FFB3B0"); $("ln-beam").setAttribute("fill", "url(#gBeamR)");
        setTimeout(() => { $("ln-mon").textContent = "정상"; $("ln-mon").setAttribute("fill", "#7FE3C8"); $("ln-beam").setAttribute("fill", "url(#gBeam)"); }, 1800);
      }
      let x = X0 + p * (X1 - X0), y = Y;
      if (pr.defect && p >= P_DIVERT) {                                                  // 밀어내기 → 슈트 → 불량함
        const k = Math.min(1, (p - P_DIVERT) / 0.08);
        x = lerp(X0 + P_DIVERT * (X1 - X0), 752, k); y = lerp(Y, 318, k);
        if (k >= 1 && !pr.gone) { pr.gone = true; ship.binN++; $("ln-bin").textContent = ship.binN; }
      }
      const hide = p > 0.995 || pr.gone;
      pr.use.setAttribute("x", x.toFixed(1)); pr.use.setAttribute("y", y.toFixed(1));
      pr.red.setAttribute("x", x.toFixed(1)); pr.red.setAttribute("y", y.toFixed(1));
      pr.use.style.display = hide || pr.defect ? "none" : "";
      pr.red.style.display = pr.defect && !pr.gone ? "" : "none";
    });

    // 프레스 램: 상자가 밑을 지날 때 내려옴
    const dp = Math.min(...prods.map((_, i) => Math.abs(wrap(t - i * CYCLE, TRAVEL) / TRAVEL - P_PRESS)));
    const down = Math.max(0, 1 - dp * TRAVEL / 0.45);
    $("ln-ram").setAttribute("transform", `translate(0 ${(46 * ease(down)).toFixed(1)})`);

    // AMR: 주기 시작에 벨트 처음에 자재를 내려놓고, 선반에서 다시 싣고 옴
    const ak = u < 0.5 ? 0 : u < 1.5 ? ease((u - 0.5)) : u < 2.4 ? 1 : u < 3.4 ? 1 - ease(u - 2.4) : 0;
    $("ln-amr").setAttribute("transform", `translate(${(96 - 14 * ak).toFixed(1)} 0)`);
    $("ln-amr-cargo").style.display = u > 1.9 || u < 0.15 ? "" : "none";

    // 로봇: 새 주기를 시작할 때 쌓을 양품이 없으면(실제 모드) 이번 주기는 대기
    const n = Math.floor(t / CYCLE);
    if (n !== armN) { if (armN != null && pending() <= 0) skip.add(n); armN = n; skip.forEach(k => { if (k < n - 2) skip.delete(k); }); }
    const a = armAt(u, skip.has(n));
    drawArm(a.w, a.hold);
    if (lastHold && !a.hold && pending() > 0) { addOne(); if (pending() > 4) addOne(); }
    lastHold = a.hold;

    // 지게차
    const [fk, load] = forkAt();
    $("ln-fork").setAttribute("transform", `translate(${(1052 + 46 * fk).toFixed(1)} 0)`);
    $("ln-fork-load").style.display = load ? "" : "none";
  }
  // ================================================================ 새 흐름 (FLOW_V2 · static/flow.js)
  //   상자 = 검사 기록 1줄 (번호) · 검사기 앞은 흐린 예상 상자 · 로봇 · 지게차 · 트럭 · 숫자는 서버 장부 그대로 (트윈과 같은 계산)
  function flowOn() { return typeof FLOW !== "undefined" && window.FLOW_ON && FLOW.ready(); }
  let pool = null, fKey = "";
  const fFlash = new Set();
  function ensurePool() {
    if (pool) return;
    const g = $("ln-prods");
    while (prods.length < 14) {
      const u = document.createElementNS(NS, "use"); u.setAttribute("href", "#box"); g.appendChild(u);
      const red = document.createElementNS(NS, "rect");
      red.setAttribute("width", 22); red.setAttribute("height", 18); red.setAttribute("rx", 2); red.setAttribute("fill", "url(#gBad)");
      red.style.display = "none"; g.appendChild(red);
      prods.push({use: u, red, defect: false, gone: false, extra: true});
    }
    prods.forEach(pr => { if (!pr.lbl) { pr.lbl = document.createElementNS(NS, "text"); pr.lbl.setAttribute("class", "ln-pid"); g.appendChild(pr.lbl); } });
    pool = true;
  }
  function resetPool() {                                          // 예전 방식으로 돌아올 때 추가 상자 · 번호 정리
    prods.forEach(pr => { if (pr.lbl) pr.lbl.textContent = ""; pr.use.style.opacity = ""; pr.use.setAttribute("href", "#box"); if (pr.extra) { pr.use.style.display = "none"; pr.red.style.display = "none"; } });
    for (let i = prods.length - 1; i >= N; i--) { prods[i].use.remove(); prods[i].red.remove(); prods[i].lbl && prods[i].lbl.remove(); prods.pop(); }
    pool = null; fKey = "";
    $("ln-mon").textContent = "정상"; $("ln-mon").setAttribute("fill", "#7FE3C8"); $("ln-beam").setAttribute("fill", "url(#gBeam)"); $("ln-beam").style.opacity = "";
  }
  function forkShapeL(u) {                                        // 장부 지게차(4.4초 왕복)를 이 그림의 왕복(3.4초) 모양으로
    u = u * 3.4 / 4.4;
    if (u < 1.4) return [ease(u / 1.4), true];
    if (u < 1.8) return [1, u < 1.6];
    if (u < 3.4) return [1 - ease((u - 1.8) / 1.6), false];
    return [0, false];
  }
  function flowFrame() {
    t = FLOW.tau(); const u = wrap(t, CYCLE);
    ensurePool();
    const bx = FLOW.boxes({pv: P_VISION, pdiv: P_DIVERT, gap: 26 / (X1 - X0)});
    let n = 0, dp = 9, waitN = 0;
    bx.forEach(b => {
      const pr = prods[n++]; if (!pr) return;
      let x = X0 + b.p * (X1 - X0), y = Y;
      if (b.chute != null) { const k = Math.min(1, b.chute); x = lerp(X0 + P_DIVERT * (X1 - X0), 752, k); y = lerp(Y, 318, k); }
      else dp = Math.min(dp, Math.abs(b.p - P_PRESS));
      pr.use.setAttribute("x", x.toFixed(1)); pr.use.setAttribute("y", y.toFixed(1));
      pr.red.setAttribute("x", x.toFixed(1)); pr.red.setAttribute("y", y.toFixed(1));
      pr.use.style.display = b.ng ? "none" : ""; pr.red.style.display = b.ng ? "" : "none";
      const pre = !b.ng && (b.pred || b.ins), href = pre ? "#boxPre" : "#box";   // 검사 전 = 골판지색 · 양품 = 주황 · 불량 = 빨강
      if (pr.use.getAttribute("href") !== href) pr.use.setAttribute("href", href);
      pr.use.style.opacity = "";
      pr.lbl.textContent = b.pred || b.chute != null || (b.wait && waitN++ > 0) ? "" : `#${b.id}`;
      pr.lbl.setAttribute("x", (x + 11).toFixed(1)); pr.lbl.setAttribute("y", (y - 5).toFixed(1));
      pr.lbl.setAttribute("class", "ln-pid" + (b.ng ? " ng" : b.wait ? " wait" : b.st ? " st" : ""));
    });
    // 검사기 모니터: 검사 중 카운트다운 → 판정 (상자가 검사기에 5초 멈춰 있는 동안)
    const st = FLOW.station();
    const mon = !st ? ["대기", "#93A3AD", "url(#gBeam)"] : st.ng ? ["불량", "#FFB3B0", "url(#gBeamR)"] : st.ok ? ["정상", "#7FE3C8", "url(#gBeam)"]
              : [`검사 ${Math.min(st.el, st.total).toFixed(1)}s`, "#BFE8FF", "url(#gBeam)"];
    if ($("ln-mon").textContent !== mon[0]) { $("ln-mon").textContent = mon[0]; $("ln-mon").setAttribute("fill", mon[1]); $("ln-beam").setAttribute("fill", mon[2]); }
    $("ln-beam").style.opacity = st ? "" : ".25";
    for (let i = n; i < prods.length; i++) { prods[i].use.style.display = "none"; prods[i].red.style.display = "none"; if (prods[i].lbl) prods[i].lbl.textContent = ""; }
    const down = Math.max(0, 1 - dp / 0.03);
    $("ln-ram").setAttribute("transform", `translate(0 ${(46 * ease(down)).toFixed(1)})`);
    const ua = Math.max(0, t - FLOW.spawn());                    // AMR: 벨트 처음에 상자가 놓이는 순간에 맞춰
    const ak = ua < 0.5 ? 0 : ua < 1.5 ? ease((ua - 0.5)) : ua < 2.4 ? 1 : ua < 3.4 ? 1 - ease(ua - 2.4) : 0;
    $("ln-amr").setAttribute("transform", `translate(${(96 - 14 * ak).toFixed(1)} 0)`);
    $("ln-amr-cargo").style.display = ua > 1.9 || ua < 0.15 ? "" : "none";
    // 로봇: 동작 진행도 x(0~1) → 이 그림의 4초 동작표 (x=0 팔레트 위 → 0.35 집기 → 0.875 놓기 → 1 팔레트 위)
    const r = FLOW.robot();
    const a = r ? armAt(wrap(2.8 + r.x * 4, 4), false) : armAt(2.8, false);
    drawArm(a.w, !!r && a.hold);
    // 지게차 · 팔레트 · 트럭 · 불량함
    const f = FLOW.fork(), [fk, load] = f ? forkShapeL(f.u) : [0, false];
    $("ln-fork").setAttribute("transform", `translate(${(1052 + 46 * fk).toFixed(1)} 0)`);
    $("ln-fork-load").style.display = load ? "" : "none";
    const c = FLOW.counts();
    FLOW.newDeparts("line").forEach(() => depart());
    ship.size = FLOW.C.PALLET; ship.trucks = FLOW.C.TRUCK; ship.shown = c.placed;
    ship.onTruck = c.onTruck;
    ship.binN = c.bin;
    const key = [c.placed, ship.onTruck, ship.departing, c.bin].join("|");
    if (key !== fKey) { fKey = key; drawPallet(); $("ln-bin").textContent = c.bin; }
  }
  requestAnimationFrame(frame);
  // 화면에 보이는 팔레트 · 트럭 숫자 (공정 라인 아래 칸이 그림과 같은 숫자를 쓰도록)
  const counts = () => ({fill: ship.shown % ship.size, size: ship.size, onTruck: ship.departing ? ship.trucks : ship.onTruck, trucks: ship.trucks});
  return {state, data, counts};
})();
