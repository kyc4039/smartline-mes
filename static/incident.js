// 사건 배너 (관제 대시보드 · 디지털 트윈 공통): 한 줄 요약 + '자세히'를 누르면 '원인 → 정지 → 연쇄 → 복구' 4단계 카드
// /api/incidents 를 2초마다 받아 그린다.
// 사용: 페이지에 <div id="incidentBox"></div>, (선택) <div id="incidentList"></div>
//      INC.start() 한 번, 상태를 받을 때마다 INC.update(state)
const INC = (() => {
  let data = null, state = null, drawnKey = "";
  let open = false;                                  // '자세히' 펼침 (페이지를 옮겨도 기억)
  try { open = localStorage.getItem("inc_open") === "1"; } catch (e) {}
  const two = n => String(n).padStart(2, "0");
  const clock = ts => { const d = new Date(ts * 1000); return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${two(Math.floor(d.getMilliseconds() / 10))}`; };
  const dur = s => `${two(Math.floor(s / 60))}:${two(Math.floor(s % 60))}`;
  const gap = (a, b) => `${Math.max(0, b - a).toFixed(2)}초 후`;
  const step = (inc, k) => inc.steps.find(s => s.kind === k);
  // 설비 안전 모델 클래스 → 한글 (modules/safety.py DANGER_CLASSES와 같게)
  const KR = {hand: "손", screwdriver: "드라이버", balldriver: "볼드라이버", spanner: "스패너", object: "물체"};
  const kr = t => String(t || "").split(/,\s*/).map(w => KR[w.toLowerCase()] || w).join(", ");

  function start() {
    const f = () => fetch("/api/incidents").then(r => r.json()).then(d => { data = d; draw(); }).catch(() => {});
    f(); setInterval(f, 2000);
  }
  function update(s) { state = s; draw(); }

  const arrow = (label, color, dashed) =>
    `<div class="arrow" style="color:${color}"><svg width="52" height="16" viewBox="0 0 52 16" aria-hidden="true"><path d="M2 8h44M38 2l8 6-8 6" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="5 5"' : ""}/></svg><span>${label}</span></div>`;

  function card(inc) {
    const c = step(inc, "cause"), s = step(inc, "stop"), l = step(inc, "linked");
    const safety = inc.status === "안전 정지";
    const go = safety ? ["/safety", "설비 안전 제어로 이동"] : ["/maintenance", "정비 완료 처리하기"];
    const title = `${inc.equipment} ${inc.status}${l ? "로 라인 정지" : ""}`;
    const recover = safety
      ? `<div class="t">자동 재가동 대기</div>
         <div><div class="row small"><span>위험구역 비움</span><span class="mono" id="incZoneT"></span></div><div class="bar"><i id="incZone" style="width:0"></i></div></div>
         <div class="small">구역이 ${data.auto_sec}초 동안 비면 다시 작동 · 손·공구가 보이면 처음부터</div>`
      : `<div class="t">정비 완료 대기</div><div class="small">티켓 #${inc.ticket ?? "-"} · 담당 정비원이 완료하면 재가동</div>`;
    const flow = `${c ? `<span>${esc(c.title)}${c.detail ? " " + esc(kr(c.detail)).slice(0, 18) : ""}</span><i>→</i>` : ""}<span>■ ${esc(inc.equipment)} ${esc(inc.status)}</span>
      ${l ? `<i>→</i><span class="y">▲ 컨베이어 연동 정지</span>` : ""}<i>→</i><span class="b" id="incRec">${safety ? "재가동 조건 확인 중" : `정비 완료 대기 · 티켓 #${inc.ticket ?? "-"}`}</span>`;
    return `<div class="incb" role="alert">
      <div class="ic">!</div>
      <div><div class="s">사건 #${String(inc.no).padStart(4, "0")} · 진행 중${data.active.length > 1 ? ` · 외 ${data.active.length - 1}건` : ""}</div>
        <div class="t">${esc(title)}</div></div>
      <div class="flow">${flow}</div>
      <div class="tm"><div class="small" style="color:var(--bad-tx)">경과</div><b id="incElapsed">00:00</b></div>
      <button class="btn ghost inc-tg" type="button" onclick="INC.toggle()" aria-expanded="${open}">${open ? "접기 ▴" : "자세히 ▾"}</button>
      <a class="btn danger" href="${go[0]}">${safety ? "설비 안전 제어 →" : "설비 보전 →"}</a>
    </div>
    <div class="inc inc-more" ${open ? "" : "hidden"}>
      <div class="chain">
        <div class="node bad cause lit" style="animation-delay:0s">
          <div class="small">① 원인 · ${esc(c.source)}</div><div class="t">${esc(c.title)}</div>
          <div class="small mono">${esc(kr(c.detail))}</div><div class="tm mono">${clock(c.ts)}</div></div>
        ${arrow(safety ? "인터록" : "즉시 조치 판정", "#F0605D")}
        <div class="node bad lit" style="animation-delay:.35s">
          <div class="small">② 즉시 반응 · ${gap(c.ts, s.ts)}</div><div class="t">■ ${esc(s.title)}</div>
          <div class="small">${safety ? "램 하강 차단, 잠김 상태" : "정비 완료 전까지 정지"}</div><div class="tm mono">${clock(s.ts)}</div></div>
        ${arrow("라인 연동", l ? "#F5B544" : "#33424C")}
        ${l ? `<div class="node warn lit" style="animation-delay:.7s">
          <div class="small">③ 연쇄 영향 · ${gap(c.ts, l.ts)}</div><div class="t">▲ ${esc(l.title)}</div>
          <div class="small">벨트 위 제품 대기</div><div class="tm mono">${clock(l.ts)}</div></div>`
          : `<div class="node none lit" style="animation-delay:.7s"><div class="small">③ 연쇄 영향</div><div class="t" style="color:var(--muted)">다른 설비 영향 없음</div></div>`}
        ${arrow("재가동 규칙", "#4CC3FF", true)}
        <div class="node wait lit" style="animation-delay:1.05s"><div class="small">④ 복구 대기</div>${recover}</div>
      </div>
      <div class="inc-foot" id="incFoot"></div>
    </div>`;
  }

  function row(inc) {
    const parts = inc.steps.map(s => {
      const c = s.kind === "stop" ? "c-bad" : s.kind === "linked" ? "c-warn" : s.kind === "recover" ? "c-ok" : "";
      return `<span class="${c}">${esc(s.kind === "cause" && s.detail && s.title === "위험구역 감지" ? `${s.title} (${kr(s.detail)})` : s.title)}</span>`;
    }).join(' <span class="muted">→</span> ');
    return `<div class="incrow"><span class="mono muted">#${String(inc.no).padStart(4, "0")}</span><span class="mono muted">${clock(inc.start).slice(0, 8)}</span>
      <span>${parts}</span><span class="mono" style="text-align:right">${dur(inc.end - inc.start)}</span></div>`;
  }

  function draw() {
    const box = document.getElementById("incidentBox");
    if (box && data) {
      const inc = data.active[data.active.length - 1];
      const key = inc ? `${inc.no}-${inc.steps.length}-${data.active.length}` : "";
      if (key !== drawnKey) { box.innerHTML = inc ? card(inc) : ""; drawnKey = key; }   // 새 사건일 때만 다시 그림 (불 켜짐 효과)
      if (inc) live(inc);
    }
    const list = document.getElementById("incidentList");
    if (list && data) list.innerHTML = data.recent.map(row).join("") || '<div class="empty">오늘 끝난 사건이 없습니다</div>';
  }

  // 1초마다 바뀌는 부분만 갱신 (경과 시간, 재가동 진행 막대, 영향 요약)
  function live(inc) {
    const el = id => document.getElementById(id);
    if (el("incElapsed")) el("incElapsed").textContent = dur(Date.now() / 1000 - inc.start);
    if (!state) return;
    const s = state.modules.safety || {};
    if (el("incRec") && inc.status === "안전 정지") {
      el("incRec").textContent = s.hold === "estop" ? "관리자 수동 재가동 필요" : s.hold === "lock" ? "정비 잠금 · 정비 끝나면 해제"
        : s.zone_clear === false ? "손·공구가 보이는 동안 정지 유지" : `자동 재가동 ${(s.clear_seconds || 0).toFixed(1)} / ${data.auto_sec}초`;
    }
    if (el("incZone")) {
      const c = s.status === "안전 정지" ? (s.clear_seconds || 0) : 0;
      el("incZoneT").textContent = `${c.toFixed(1)} / ${data.auto_sec.toFixed(1)} s`; el("incZone").style.width = pct(c, data.auto_sec) + "%";
    }
    if (el("incFoot")) {
      const eq = state.equipment, stopped = eq.filter(e => e.status !== "가동"), run = eq.filter(e => e.status === "가동");
      el("incFoot").innerHTML = `<span>영향 설비 <b style="color:var(--text)">${stopped.length}대</b></span>
        <span>정상 가동 <b class="c-ok">${run.length}대</b>${run.length ? ` (${run.map(e => esc(e.name)).join(" · ")})` : ""}</span>
        <span>같은 원인 오늘 <b style="color:var(--text)">${inc.nth_today}번째</b></span>`;
    }
  }
  function toggle() {
    open = !open;
    try { localStorage.setItem("inc_open", open ? "1" : "0"); } catch (e) {}
    const m = document.querySelector("#incidentBox .inc-more"), b = document.querySelector("#incidentBox .inc-tg");
    if (m) m.hidden = !open;
    if (b) { b.textContent = open ? "접기 ▴" : "자세히 ▾"; b.setAttribute("aria-expanded", open); }
  }
  return {start, update, toggle};
})();
