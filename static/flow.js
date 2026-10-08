// 라인 흐름 공용 코드 (10/07 · FLOW_V2) — 디지털 트윈 · 관제 대시보드 · 생산 관리가 같이 씀
//   서버 장부(/api/line/flow)를 1초마다 받아, 서버 라인 시계 τ에 맞춰 '지금 이 순간'의 상자 위치 · 로봇 · 지게차 · 숫자를 계산만 한다.
//   그림(입체 / 옆모습)은 각 화면이 그리고, 위치 계산은 전부 여기 → 세 화면이 같은 순간 같은 상자 · 같은 숫자
// 사용: FLOW.start() 한 번 → 매 프레임 FLOW.tau(), FLOW.boxes(geom), FLOW.robot(), FLOW.counts(), FLOW.fork(), FLOW.newDeparts(key)
const FLOW = (() => {
  let D = null, at = 0, started = false;
  const C = {INSPECT: 4, MOVE: 1, D_PRE: 8, D_END: 4, D_DIV: 1.5, D_CHUTE: 2, GRAB: 0.35, PLACE: 0.875, FORK_SEC: 4.4, FORK_DROP: 2.1, DEPART_EMPTY: 3.1, PALLET: 8, TRUCK: 10, CYCLE: 5};

  function poll() {
    fetch("/api/line/flow").then(r => r.json()).then(d => {
      // 새 값이 화면 시계보다 살짝 뒤로 가는 경우(네트워크 지연)엔 화면 시계를 유지해 뒤로 튀지 않게
      const cur = D ? tau() : null;
      D = d; D.tau0 = d.tau; at = performance.now(); Object.assign(C, d.const || {});   // tau0 = 서버가 숫자를 센 시각
      if (cur != null && d.tau < cur && cur - d.tau < 1.5) D.tau = cur;
    }).catch(() => {});
  }
  // 0.5초마다 (빨리감기 중에는 0.25초) — 검사가 끝난 상자의 판정이 늦게 보이지 않게
  function start() { if (started) return; started = true; const loop = () => { poll(); setTimeout(loop, D && D.rate > 1 ? 150 : 500); }; loop(); }
  const ready = () => !!D;
  // 지금 라인 시계: 마지막으로 받은 τ + 배속 × 지난 시간 (최대 3초까지만 앞질러 계산)
  function tau() { if (!D) return 0; return D.tau + D.rate * Math.min(3, (performance.now() - at) / 1000); }

  // 상자 목록 — g: {pv: 그림에서 검사기 위치(0~1), pdiv: 불량 분기점 위치, gap: 줄 설 때 상자 간격}
  //   검사기 정지 방식: 상자는 검사기 앞(pv - gap)에서 기다렸다가 MOVE초 만에 검사기로 → INSPECT초 검사 → 떠남
  //   돌려주는 것: {key, id, p, pred(기록 전 회색), ins(검사 중 · 결과 전), st(검사기 안), ng, chute, wait, type}
  let lastSt = null, lastSpawn = -1e9;
  function boxes(g) {
    if (!D) return [];
    const t = tau(), out = [], W = g.pv - g.gap;
    // 검사기를 아직 안 떠난 상자 (기록 있는 상자 + 회색 예상 상자) — 검사기에 들어오는 순서대로
    const items = [];
    D.products.forEach(p => items.push({p, ws: p.ws, we: p.we}));
    (D.pred || []).forEach((ws, i) => items.push({pred: true, ws, we: i === 0 && t >= ws + C.INSPECT ? t + 1e-3 : ws + C.INSPECT}));
    items.sort((a, b) => a.ws - b.ws);
    items.forEach((it, i) => {                                       // 예상 상자는 앞 상자가 떠난 뒤에 들어옴 (판정이 늦어지면 뒤로 밀림)
      if (it.pred && i > 0 && it.ws < items[i - 1].we + C.MOVE) { it.ws = items[i - 1].we + C.MOVE; it.we = it.ws + C.INSPECT; }
    });
    lastSt = null; lastSpawn = -1e9;
    let ahead = 0;
    items.forEach(it => {
      const t0 = it.ws - C.MOVE - C.D_PRE;                          // 벨트 처음에 놓이는 순간
      if (t >= t0) lastSpawn = Math.max(lastSpawn, t0);
      const p = it.p;
      if (t < it.we) {                                               // 검사기 앞 / 검사기 안
        if (t < t0) { ahead++; return; }
        if (t >= it.ws) {
          const reveal = p && t >= p.tj;
          lastSt = {el: t - it.ws, total: p ? Math.round((p.we - p.ws) * 10) / 10 : C.INSPECT, id: p ? p.id : null, pred: !p, ng: reveal && !p.ok, ok: reveal && p.ok, type: p ? p.type : ""};
          out.push(p ? {key: p.id, id: p.id, p: g.pv, st: true, ins: !reveal, ng: reveal && !p.ok, type: p.type}
                     : {key: "p" + it.ws, pred: true, p: g.pv, st: true});
        } else {
          let x = t < it.ws - C.MOVE ? W * (t - t0) / C.D_PRE : W + (g.pv - W) * Math.min(1, (t - (it.ws - C.MOVE)) / C.MOVE);
          x = Math.max(0, Math.min(x, g.pv - ahead * g.gap));
          out.push(p ? {key: p.id, id: p.id, p: x, ins: true, type: p.type} : {key: "p" + it.ws, pred: true, p: x});
        }
        ahead++;
        return;
      }
      if (!p) return;
      if (!p.ok) {                                                   // 불량: 검사기 → 분기점 → 불량함
        if (t < p.tdiv) out.push({key: p.id, id: p.id, ng: true, type: p.type, p: g.pv + (g.pdiv - g.pv) * (t - p.we) / C.D_DIV});
        else if (t < p.tbin) out.push({key: p.id, id: p.id, ng: true, type: p.type, p: g.pdiv, chute: (t - p.tdiv) / C.D_CHUTE});
      }
    });
    const oks = D.products.filter(p => p.ok);
    oks.forEach(p => {                                               // 정상: 검사기 → 벨트 끝 → 로봇 대기열
      if (t < p.we || t >= p.tp) return;
      const before = oks.filter(q => q.arr < p.arr && t < q.tp).length;
      const belt = g.pv + (1 - g.pv) * Math.min(1, (t - p.we) / C.D_END);
      const stop = 1 - before * g.gap;
      out.push({key: p.id, id: p.id, p: Math.min(belt, stop), wait: belt >= stop - 1e-6 && t >= p.arr - 0.05});
    });
    return out;
  }
  // 검사기 상태 (boxes() 다음에 부름): {el: 검사 시작 후 초, total, id, pred, ng, ok, type} 또는 null(비어 있음)
  const station = () => lastSt;
  // 마지막으로 벨트 처음에 상자가 놓인 τ (자재 투입 AMR 박자)
  const spawn = () => lastSpawn;
  // 로봇: 지금 동작 중인 상자 → {x: 동작 진행(0~1, 0.35에 집고 0.875에 놓음), id, fast}
  function robot() {
    if (!D) return null;
    const t = tau();
    const p = D.products.find(q => q.ok && t >= q.s && t < q.s + q.rc);
    return p ? {x: (t - p.s) / p.rc, id: p.id, fast: p.rc < 3} : null;
  }
  // 숫자: 서버가 계산한 값 + (서버 시각 이후 ~ 지금 사이에 일어난 사건)
  function counts() {
    if (!D) return null;
    const t = tau(), c = Object.assign({}, D.counts);
    let lastDep = null;
    D.events.forEach(e => {
      if (e.at <= D.tau0 || e.at > t) return;
      if (e.kind === "place") c.placed++;
      else if (e.kind === "bin") c.bin++;
      else if (e.kind === "drop") c.onTruck++;
      else if (e.kind === "depart") { c.trucks_out++; lastDep = e; }
      else if (e.kind === "empty") { c.onTruck = 0; c.departing = false; }
    });
    if (lastDep) { c.departing = true; c.onTruck = C.TRUCK; }
    c.fill = c.placed % C.PALLET;
    if (!c.departing) { c.lot_seq = c.trucks_out + 1; c.lot = `${D.day}-${String(c.lot_seq).padStart(2, "0")}`; }
    c.queue = D.products.filter(p => p.ok && p.arr <= t && t < p.tp).length;
    c.in_flight = Math.max(0, c.good_db - c.placed);
    return c;
  }
  // 지게차: 지금 왕복 중이면 {u: 출발 후 지난 초}
  function fork() {
    if (!D) return null;
    const t = tau(), e = D.events.filter(x => x.kind === "fork" && x.at <= t && t < x.at + C.FORK_SEC).pop();
    return e ? {u: t - e.at} : null;
  }
  // 아직 화면에서 출발 장면을 안 보여 준 트럭 출발 (화면마다 key로 따로 기억)
  const shownDeparts = {};
  function newDeparts(key) {
    if (!D) return [];
    const t = tau(), seen = shownDeparts[key] || (shownDeparts[key] = new Set());
    const out = D.events.filter(e => e.kind === "depart" && e.at <= t && t - e.at < 6 && !seen.has(e.ref));
    out.forEach(e => seen.add(e.ref));
    return out.map(e => e.ref);
  }
  // 이벤트 표시용 상태 한 줄
  function status() {
    if (!D) return null;
    const s = D.status, c = counts();
    if (s.stopped) return {kind: "stop", short: "■ 라인 정지", text: `■ 라인 정지 · ${s.reason || s.conveyor} · ${Math.max(0, Math.round(D.now - (s.since || D.now) + (performance.now() - at) / 1000))}초`};
    if (s.ff) return {kind: "ff", short: `⏩ 빨리감기 ×${s.ff}`, text: `⏩ 빨리감기 ×${s.ff} · 트럭 채우는 중 ${c.onTruck}/${C.TRUCK}`};
    if (c.queue >= 2 || s.fast) return {kind: "queue", short: `▲ 로봇 대기 ${c.queue}`, text: `▲ 로봇 대기 ${c.queue}${s.fast ? " · 적체 해소 ×2" : ""}`};
    return {kind: "ok", short: "", text: `● LOT ${c.lot} · ${c.onTruck}/${C.TRUCK} · 팔레트 ${c.fill}/${C.PALLET}`};
  }
  return {start, ready, tau, boxes, station, spawn, robot, counts, fork, newDeparts, status, C, data: () => D};
})();
