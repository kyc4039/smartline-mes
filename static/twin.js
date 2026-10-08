// SMART LINE 디지털 트윈 — 등각(아이소메트릭) 공정 라인
//
// 좌표계: 바닥 위의 (x, y)와 높이 z를 '칸' 단위로 쓰고, P()가 화면 좌표로 바꾼다.
//   x: 라인 진행 방향(왼쪽 위 → 오른쪽 아래), y: 라인 앞뒤(클수록 화면 앞쪽), z: 높이
// 설비 위치·크기를 바꾸고 싶으면 아래 build()의 box(...) 숫자만 고치면 된다.
//
// 이 파일이 제공하는 기능 (twin.html에서 사용)
//   TW.build()             장면 SVG 만들기
//   TW.apply(eq, mod, sel) 실시간 상태 반영 (멈춤, 표시등, 이름표, 선택 강조)
//   TW.zone(safety, st)    ② 프레스 앞 위험구역 바닥 표시
//   TW.spawnDefect(type)   ② 불량품이 배출 레일로 빠지는 움직임
//   TW.paint(vals)         ① 레이어: 설비를 지표 색으로 다시 칠하기 / TW.unpaint()
//   TW.chip(name, text, t) 이름표 글자 바꾸기 (레이어·가정 모드에서 사용)
//   TW.focus(name), TW.ghosts(k)  ④ 가정 시뮬레이션: 병목 강조, 늘어나는 제품 표시
const TW = (() => {
  const U = 46, X0 = 250, Y0 = 230;                 // 한 칸 크기(px), 원점 위치
  const P = (x, y, z = 0) => [+(X0 + (x - y) * U * 0.866).toFixed(1), +(Y0 + (x + y) * U * 0.5 - z * U).toFixed(1)];
  const D = (dx, dy, dz = 0) => [(dx - dy) * U * 0.866, (dx + dy) * U * 0.5 - dz * U];   // 칸 이동량 → 화면 이동량
  const pts = a => a.map(p => p.join(",")).join(" ");

  // 색 묶음: [윗면, 앞면(+y), 옆면(+x)] — 빛이 위에서 와서 윗면이 가장 밝음
  const C = {
    metal: ["#3A4A54", "#2A363E", "#222C33"], steel: ["#4A5B66", "#3A464E", "#323C43"],
    light: ["#B9C6CD", "#7F919C", "#6A7A84"], belt: ["#33424C", "#26323A", "#1E282E"],
    crown: ["#566873", "#3E4D56", "#34424A"], box: ["#F5B544", "#C98A33", "#A87224"],
    bad: ["#F0605D", "#B8413F", "#97302F"], bin: ["#8E2F2D", "#66201F", "#521918"],
    ghost: ["#4CC3FF", "#2E8FC2", "#22729C"],
    pred: ["#A39377", "#857760", "#70644F"],          // 검사 전 상자 · 자재 = 흐린 골판지색 (10/07)
    // 설비 도장색 (10/07): 차콜 뼈대 · 안전 노랑 덮개 · 고무 벨트 · 노랑 선반 보
    eqb: ["#4A5258", "#3A4146", "#30363A"], eqw: ["#F5C542", "#D9A92A", "#C29522"],
    rub: ["#2B3238", "#21272C", "#1B2024"], beam: ["#F5C542", "#D9A92A", "#C29522"],
  };

  const mat = (x0, x1, y0, y1, z0, z1) => box(x0, x1, y0, y1, z0, z1, C.pred);   // 자재(검사 전) 상자
  // 직육면체 하나 (보이는 세 면만 그림). data-f: 0=윗면 1=앞면 2=옆면 (레이어 색칠에 사용)
  function box(x0, x1, y0, y1, z0, z1, c) {
    const top = [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)];
    const front = [P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1)];
    const side = [P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1)];
    return `<polygon data-f="1" points="${pts(front)}" fill="${c[1]}"/><polygon data-f="2" points="${pts(side)}" fill="${c[2]}"/>` +
           `<polygon data-f="0" points="${pts(top)}" fill="${c[0]}"/>`;
  }

  // 신호등 탑 (빨강 · 노랑 · 초록 3단): apply()가 설비 상태에 맞는 칸만 켬
  function tower(x, y, z, name) {
    const w = 0.07, h = 0.13;
    return `<g class="stk" data-stk="${name}">` + box(x - 0.015, x + 0.015, y - 0.015, y + 0.015, z, z + 0.35, C.steel) +
      `<g class="stk-g">${box(x - w, x + w, y - w, y + w, z + 0.35, z + 0.35 + h, ["#1E3A33", "#173029", "#132822"])}</g>` +
      `<g class="stk-y">${box(x - w, x + w, y - w, y + w, z + 0.35 + h, z + 0.35 + 2 * h, ["#3B3220", "#2E2718", "#262014"])}</g>` +
      `<g class="stk-r">${box(x - w, x + w, y - w, y + w, z + 0.35 + 2 * h, z + 0.35 + 3 * h, ["#3A2224", "#2E1A1C", "#261517"])}</g>` +
      box(x - w - 0.01, x + w + 0.01, y - w - 0.01, y + w + 0.01, z + 0.35 + 3 * h, z + 0.4 + 3 * h, C.belt) + `</g>`;
  }
  // 바닥 그림자 (설비 아래 살짝 어둡게)
  const shadow = (x0, x1, y0, y1, d = 0.12) => `<polygon points="${pts([P(x0 - d, y0 - d), P(x1 + d, y0 - d), P(x1 + d, y1 + d), P(x0 - d, y1 + d)])}" fill="#000" opacity=".28"/>`;
  // 노랑·검정 경고 띠 (앞면 y = 일정, x0~x1, 높이 z0~z1)
  function hazard(x0, x1, y, z0, z1) {
    let s = `<polygon points="${pts([P(x0, y, z0), P(x1, y, z0), P(x1, y, z1), P(x0, y, z1)])}" fill="#F5C542"/>`;
    const n = Math.max(2, Math.round((x1 - x0) / 0.18));
    for (let i = 0; i < n; i += 2) { const a = x0 + (x1 - x0) * i / n, b = x0 + (x1 - x0) * (i + 1) / n;
      s += `<polygon points="${pts([P(a, y, z0), P(b, y, z0), P(b + 0.06, y, z1), P(a + 0.06, y, z1)])}" fill="#1A1A1A"/>`; }
    return s;
  }

  // 설비 이름 → 내부 키, 상태 표시등·이름표 위치(칸 좌표)
  const EQ = {
    "자재 투입기": {key: "feeder", anchor: [-1.6, 1.5, 1.7], num: "②"},    // 자재 투입 AMR (왼쪽 AMR 통로 위)
    "프레스 #1":   {key: "press",  anchor: [3.8, 1.5, 3.4], num: "③"},
    "컨베이어":    {key: "conv",   anchor: [10.8, 2.7, 0.0]},
    "비전 검사기": {key: "vision", anchor: [7.0, 1.4, 2.9], num: "④"},     // 프레스(3.8)·로봇(10.2) 사이 한가운데
    "로봇 적재기": {key: "robot",  anchor: [10.2, -0.25, 2.9], num: "⑤"},
  };
  const KEY2NAME = Object.fromEntries(Object.entries(EQ).map(([n, v]) => [v.key, n]));

  // 컨베이어 위 제품 이동 거리 (CSS 애니메이션에 넣음)
  const TRAVEL = 10.4, MOVE = [TRAVEL * U * 0.866, TRAVEL * U * 0.5];

  // ② 위험구역: 프레스 앞 바닥 (카메라 3의 SAFETY_ROI를 모형 바닥에 옮긴 것)
  const ZONE = [P(2.4, 2.1), P(5.2, 2.1), P(5.2, 3.7), P(2.4, 3.7)];
  // ② 배출 레일과 불량함 (비전 검사기 뒤에서 앞쪽으로 빠짐)
  const RAIL_X = 9.6, BIN = [8.5, 10.7, 2.85, 4.95];   // 회수함 x0 x1 y0 y1 (가운데 = 분기 컨베이어 끝)
  // 자재 투입 AMR: 컨베이어 왼쪽 끝의 AMR 통로에서 '자재 선반 ↔ 컨베이어 입구'를 왕복하며 자재를 실어 나름
  //   10/07: 창고(격자 위쪽 모서리) 앞 W → 통로를 따라 아래로 K → 컨베이어 입구 I (4개씩 운반 · 한 바퀴 = 4박자)
  const AMR_W = [-4.5, -3.0], AMR_K = [-4.5, 1.5], AMR_I = [-1.6, 1.5];
  const MECH_NAME = "정비 구역", MECH_HOME = [7.1, -3.75];
  // 정비원이 일하러 가는 자리 (설비 앞 바닥)
  const MECH_SPOT = {"프레스 #1": [2.5, 2.95], "컨베이어": [6.2, 2.7], "비전 검사기": [7.9, -0.75], "로봇 적재기": [9.0, -1.4], "자재 투입기": [-2.4, 2.6]};
  // 로봇 적재기: 기둥 위치(ROBOT), 어깨 높이, 팔 길이(L1 위팔, L2 아래팔), 집게 길이, 한 번 쌓는 시간(초)
  //   PICK: 컨베이어 끝 제품 윗면, PLACE: 팔레트 위 쌓는 곳 (집게 끝 위치, 칸 좌표 x y z)
  const ROBOT = [10.2, -0.25], SHOULDER_Z = 1.05, L1 = 1.35, L2 = 1.3, GRIP = 0.3;
  // ★ 라인 박자: 모든 움직임이 이 시계 하나로 맞물려 돈다 (컨베이어가 멈추면 시계도 멈춤)
  //   CYCLE: 제품 1개 주기(초) — AMR 1회 왕복 = 프레스 1회 = 로봇 1회 / TRAVEL_SEC: 제품이 벨트 처음→끝까지 가는 시간
  const CYCLE = 4, TRAVEL_SEC = 12, N_PROD = TRAVEL_SEC / CYCLE;
  // ⑥ 출하: 팔레트가 다 차면 지게차가 트럭에 싣고 돌아옴 / 출하장 위치
  const FORK = [13.5, 14.5, -0.85], FORK_BACK = 1.4;
  const SHIP_DX = 1.4;                                   // 출하장 전체를 오른쪽으로 옮긴 거리 (지게차가 로봇 팔레트와 겹치지 않게)
  // ① 안전 게이트 위치 (기둥 두 개 사이를 작업자가 지나감)
  const GATE = [-5.75, -5.05, 2.75, 4.05];          // 자재 선반 앞(맨 왼쪽) — 공정 순서 ①이 화면에서도 가장 왼쪽
  const GATE_NAME = "안전 게이트", SHIP_NAME = "출하장";
  const PRESS_X = 3.8;                                   // 프레스 중심 (제품이 이 밑을 지날 때 램이 내려옴)
  const PICK = [11.0, 1.5, 0.95], PLACE = [11.7, -0.5, 1.75];

  const part = (name, inner, extra = "") => `<g class="eq" data-eq="${name}" ${extra}>${inner}</g>`;

  // 이름표 위치 (설비를 가리지 않는 빈 곳) · 작은 이름표 안 왼쪽에 상태등
  const LBL = {"자재 투입기": [-2.2, 2.75, 0], "프레스 #1": [3.8, 1.5, 3.75], "컨베이어": [6.2, 2.75, 0],
               "비전 검사기": [6.4, 0.5, 2.75], "로봇 적재기": [10.7, -1.0, 2.75]};
  const chipText = name => (EQ[name].num ? EQ[name].num + " " : "") + name;
  const chipW = name => 26 + chipText(name).length * 10.2;
  function lamp(name) {
    const [ax, ay] = P(...LBL[name]), x = ax - chipW(name) / 2 + 10, y = ay;
    const k = EQ[name].key;
    return `<g class="lampx" id="lamp-${k}"><circle cx="${x}" cy="${y}" r="7" class="halo"/>` +
           `<circle cx="${x}" cy="${y}" r="3.6" class="dot"/></g>`;
  }
  function chip(name) {
    const [x, y] = P(...LBL[name]), k = EQ[name].key, w = chipW(name);
    return `<g class="chip" id="chip-${k}" data-eq="${name}" transform="translate(${x} ${y})">` +
           `<rect x="${-w / 2}" y="-11" width="${w}" height="22" rx="6"/>` +
           `<text x="7" y="4" text-anchor="middle" style="font-size:11px">${chipText(name)}</text></g>`;
  }


  // 컨베이어 위 제품 (ghost=true면 가정 시뮬레이션용 파란 반투명 제품, 처음엔 숨김)
  function product(i, ghost = false) {
    return `<g class="tw-prod${ghost ? " ghost" : ""}" data-i="${i}" ${ghost ? `data-g="${i}"` : ""}>` +
           `${box(0.3, 0.9, 1.2, 1.8, 0.45, 0.95, ghost ? C.ghost : C.box)}</g>`;
  }

  // ---------------------------------------------------------------- 프레스 앞 작업자
  const SKIN = ["#E0B48F", "#C99A76", "#B58663"], VEST = ["#F28C28", "#D9761A", "#C26A16"], PANTS = ["#3B4A63", "#2E3A4F", "#263042"];
  const HELMET = ["#F5D04C", "#D9B530", "#C9A520"], GLOVE = ["#4CC3FF", "#2E8FC2", "#22729C"], WHITE = ["#E7EDF0", "#E7EDF0", "#E7EDF0"];
  function worker(wx, wy, reach, noHelmet) {          // reach=true: 프레스 쪽으로 손을 뻗은 모습 + 손 감지 상자
    const sh = P(wx, wy);
    let s = `<ellipse cx="${sh[0]}" cy="${sh[1]}" rx="20" ry="9" fill="#000" opacity=".35"/>`;
    s += box(wx - 0.22, wx - 0.04, wy - 0.12, wy + 0.08, 0, 0.75, PANTS) + box(wx + 0.04, wx + 0.22, wy - 0.12, wy + 0.08, 0, 0.75, PANTS);
    s += box(wx - 0.26, wx + 0.26, wy - 0.16, wy + 0.12, 0.75, 1.45, VEST) + box(wx - 0.24, wx + 0.24, wy + 0.12, wy + 0.13, 0.95, 1.02, WHITE);
    if (reach) {
      s += box(wx - 0.4, wx - 0.26, wy - 0.1, wy + 0.04, 0.85, 1.4, VEST);
      s += box(wx + 0.26, wx + 0.4, wy - 0.95, wy - 0.05, 1.2, 1.34, VEST) + box(wx + 0.25, wx + 0.42, wy - 1.15, wy - 0.95, 1.18, 1.36, GLOVE);
    } else {
      s += box(wx - 0.4, wx - 0.26, wy - 0.08, wy + 0.06, 0.85, 1.4, VEST) + box(wx + 0.26, wx + 0.4, wy - 0.08, wy + 0.06, 0.85, 1.4, VEST);
      s += box(wx - 0.41, wx - 0.25, wy - 0.09, wy + 0.07, 0.72, 0.86, GLOVE) + box(wx + 0.25, wx + 0.41, wy - 0.09, wy + 0.07, 0.72, 0.86, GLOVE);
    }
    s += box(wx - 0.15, wx + 0.15, wy - 0.15, wy + 0.1, 1.45, 1.75, SKIN) + (noHelmet ? box(wx - 0.16, wx + 0.16, wy - 0.16, wy + 0.11, 1.75, 1.8, ["#3B2A20","#2E2118","#261B14"]) : box(wx - 0.2, wx + 0.2, wy - 0.2, wy + 0.15, 1.72, 1.86, HELMET));
    if (reach) {
      const hp = P(wx + 0.33, wy - 1.05, 1.27);
      s += `<rect class="blink" x="${hp[0] - 15}" y="${hp[1] - 15}" width="30" height="30" rx="3" fill="none" stroke="#F0605D" stroke-width="2.5"/>` +
           `<g transform="translate(${hp[0] + 18} ${hp[1] - 30})"><rect width="64" height="20" rx="4" fill="#F0605D"/>` +
           `<text x="32" y="14" text-anchor="middle" font-size="12" font-weight="700" fill="#2A1213" font-family="IBM Plex Sans KR, sans-serif">손 감지</text></g>`;
    }
    return s;
  }

  // 새 작업자: 바라보는 방향(face: "+x" "+y" "-x" "-y") · 걷기(walk -1~1) · 보호구 착용 여부
  const BOOT = ["#3A3F47", "#2A2F36", "#22262C"], SHIRT = ["#3B4A63", "#2E3A4F", "#263042"], REFL = ["#E7EDF0", "#C9D3D8", "#B9C6CD"],
        HAIR = ["#3B2A20", "#2E2118", "#261B14"], EYE = ["#1B1B1B", "#1B1B1B", "#1B1B1B"], BELT = ["#26323A", "#1B242A", "#151C21"];
  function person(wx, wy, o = {}) {
    const face = o.face || "+y", walk = o.walk || 0, ppe = Object.assign({helmet: true, vest: true, gloves: true}, o.ppe || {});
    const ax = face[1] === "x", sg = face[0] === "-" ? -1 : 1;
    // 몸 기준(앞 f, 옆 l) → 세계 좌표 상자
    const zz = o.z || 0, k = o.scale || 1;
    const B = (f0, f1, l0, l1, z0, z1, c) => {
      f0 *= k; f1 *= k; l0 *= k; l1 *= k; z0 = z0 * k + zz; z1 = z1 * k + zz;
      const a = [f0 * sg, f1 * sg].sort((p, q) => p - q);
      return ax ? box(wx + a[0], wx + a[1], wy + l0, wy + l1, z0, z1, c) : box(wx + l0, wx + l1, wy + a[0], wy + a[1], z0, z1, c);
    };
    const sh = P(wx, wy);
    let s = zz ? "" : `<ellipse cx="${sh[0]}" cy="${sh[1]}" rx="17" ry="8" fill="#000" opacity=".35"/>`;
    const sw = 0.09 * walk;
    const leg = (l0, l1, d) => B(-0.08 + d, 0.08 + d, l0, l1, 0.1, 0.78, SHIRT) + B(-0.09 + d, 0.14 + d, l0 - 0.01, l1 + 0.01, 0, 0.11, BOOT);
    const arm = (l0, l1, d) => B(-0.06 + d, 0.07 + d, l0, l1, 0.92, 1.42, SHIRT) + B(-0.06 + d, 0.07 + d, l0, l1, 0.78, 0.93, ppe.gloves ? GLOVE : SKIN);
    const vest = ppe.vest ? VEST : SHIRT;
    if (!o.seated) s += leg(-0.19, -0.03, sw);
    s += arm(-0.37, -0.25, -sw);                                               // 먼 쪽 다리 · 팔
    if (!o.seated) s += leg(0.03, 0.19, -sw);
    s += B(-0.13, 0.12, -0.25, 0.25, 0.78, 0.85, BELT) + B(-0.14, 0.12, -0.25, 0.25, 0.85, 1.46, vest);   // 허리띠 · 몸통(조끼)
    if (ppe.vest) s += B(0.12, 0.13, -0.25, 0.25, 1.0, 1.05, REFL) + B(0.12, 0.13, -0.25, 0.25, 1.2, 1.25, REFL) +
                       B(-0.15, -0.14, -0.25, 0.25, 1.0, 1.05, REFL);              // 반사띠 (앞 · 뒤)
    s += arm(0.25, 0.37, sw);                                                  // 가까운 쪽 팔
    s += B(-0.05, 0.05, -0.06, 0.06, 1.46, 1.5, SKIN) + B(-0.12, 0.12, -0.13, 0.13, 1.5, 1.79, SKIN);   // 목 · 머리
    if (sg > 0) s += B(0.12, 0.125, -0.08, -0.04, 1.63, 1.67, EYE) + B(0.12, 0.125, 0.04, 0.08, 1.63, 1.67, EYE);   // 눈 (앞을 볼 때만 보임)
    s += ppe.helmet ? B(-0.15, 0.14, -0.16, 0.16, 1.76, 1.9, HELMET) + B(0.14, 0.24, -0.15, 0.15, 1.76, 1.79, HELMET) + B(-0.02, 0.02, -0.16, 0.16, 1.9, 1.93, HELMET)
                    : B(-0.13, 0.11, -0.14, 0.14, 1.77, 1.83, HAIR);
    return s;
  }

  // 위험구역 안으로 뻗은 팔 + 손 감지 표시 (새 작업자 그림에 덧붙임)
  function reach(wx, wy) {
    const hp = P(wx + 0.1, wy - 1.05, 1.27);
    return box(wx + 0.03, wx + 0.17, wy - 0.95, wy - 0.12, 1.2, 1.34, SHIRT) + box(wx + 0.01, wx + 0.19, wy - 1.15, wy - 0.95, 1.18, 1.36, GLOVE) +
      `<rect class="blink" x="${hp[0] - 15}" y="${hp[1] - 15}" width="30" height="30" rx="3" fill="none" stroke="#F0605D" stroke-width="2.5"/>` +
      `<g transform="translate(${hp[0] + 18} ${hp[1] - 30})"><rect width="64" height="20" rx="4" fill="#F0605D"/>` +
      `<text x="32" y="14" text-anchor="middle" font-size="12" font-weight="700" fill="#2A1213" font-family="IBM Plex Sans KR, sans-serif">손 감지</text></g>`;
  }

  // ---------------------------------------------------------------- 작업자 대시보드 (HMI)
  const HMI_NAME = "작업자 대시보드", HMI = [2.75, 3.95];   // 프레스 앞 작업자(3.8, 3.95) 바로 왼쪽, 화면이 작업자 쪽(+x)을 봄
  const HMI_W = 240, HMI_H = 190;
  // 화면 옆면(x = HMI[0]+0.07 평면, 작업자 쪽)에 240×190 그림을 비스듬히 붙이는 변환 (글자 방향 = -y)
  const HMI_M = (() => { const o = P(HMI[0] + 0.07, HMI[1] + 0.5, 1.95);
    return `matrix(${(0.866 * U / HMI_W).toFixed(4)} ${(-0.5 * U / HMI_W).toFixed(4)} 0 ${(U * 0.8 / HMI_H).toFixed(4)} ${o[0].toFixed(1)} ${o[1].toFixed(1)})`; })();
  const hmi = {mode: "ok", left: null, prod: null, rate: null};
  // 화면 내용 (트윈 위 작은 화면과 오른쪽 칸 큰 화면이 같은 그림을 씀)
  function hmiScreen() {
    const W = HMI_W, H = HMI_H, bad = hmi.mode !== "ok";
    const col = bad ? "#F0605D" : "#3CC6A8";
    let s = `<rect width="${W}" height="${H}" rx="6" fill="#0E1317"/>` +
      `<rect x="8" y="8" width="${W - 16}" height="44" rx="5" fill="${bad ? "#2A1213" : "#12302A"}" stroke="${col}"/>` +
      `<text x="18" y="26" font-size="11" fill="${col}">프레스 #1</text>` +
      `<text x="18" y="45" font-size="17" font-weight="700" fill="${bad ? "#FFB3B0" : "#7FE3C8"}">${bad ? "■ 안전 정지" : "● 정상 가동"}</text>`;
    if (hmi.mode === "hit") {
      s += `<text x="${W - 18}" y="45" font-size="20" font-weight="700" text-anchor="end" fill="#FFE1DF">STOP</text>` +
        `<rect x="8" y="60" width="${W - 16}" height="54" rx="5" fill="#F0605D"/>` +
        `<text x="${W / 2}" y="82" font-size="15" font-weight="700" text-anchor="middle" fill="#2A1213">⚠ 위험구역 손 감지</text>` +
        `<text x="${W / 2}" y="103" font-size="13" font-weight="600" text-anchor="middle" fill="#2A1213">기계에서 떨어지세요</text>`;
    } else if (hmi.mode === "hold") {
      s += `<text x="${W - 18}" y="45" font-size="20" font-weight="700" text-anchor="end" fill="#FFE1DF">${hmi.left != null ? hmi.left.toFixed(1) + "s" : ""}</text>` +
        `<rect x="8" y="60" width="${W - 16}" height="54" rx="5" fill="#2B2210" stroke="#F5B544"/>` +
        `<text x="${W / 2}" y="82" font-size="14" font-weight="700" text-anchor="middle" fill="#FFD58A">${hmi.left != null ? `${hmi.left.toFixed(1)}초 뒤 자동 재가동` : "재가동 대기"}</text>` +
        `<text x="${W / 2}" y="103" font-size="12" text-anchor="middle" fill="#FFD58A">계속 떨어져 있으세요</text>`;
    } else {
      s += `<text x="16" y="78" font-size="11" fill="#93A3AD">오늘 생산</text>` +
        `<text x="16" y="102" font-size="20" font-weight="600" fill="#E7EDF0">${hmi.prod == null ? "-" : hmi.prod.toLocaleString()}</text>` +
        `<text x="128" y="78" font-size="11" fill="#93A3AD">불량률</text>` +
        `<text x="128" y="102" font-size="20" font-weight="600" fill="#E7EDF0">${hmi.rate == null ? "-" : (hmi.rate * 100).toFixed(1) + "%"}</text>`;
    }
    s += `<text x="16" y="138" font-size="11" fill="#93A3AD">보호구 (입장 시 확인)</text>` +
      `<text x="16" y="158" font-size="13" font-weight="600" fill="#7FE3C8">✓ 안전모  ✓ 조끼  ✓ 장갑</text>` +
      `<rect x="16" y="168" width="${W - 32}" height="8" rx="4" fill="#26323A"/>` +
      `<rect x="16" y="168" width="${(W - 32) * (hmi.mode === "ok" ? 1 : hmi.mode === "hold" && hmi.left != null ? Math.max(0.05, 1 - hmi.left / 5) : 0.05)}" height="8" rx="4" fill="${hmi.mode === "ok" ? "#3CC6A8" : "#F5B544"}"/>`;
    return s;
  }
  function drawHmi() {
    const g = document.getElementById("hmi-screen"); if (g) g.innerHTML = hmiScreen();
    // 오른쪽 칸: 다른 메뉴와 같은 글씨 크기의 일반 화면으로 (그림을 키우지 않음)
    const big = document.getElementById("hmiBig");
    if (big) {
      const t = hmi.mode === "ok" ? "ok" : "bad";
      const sub = hmi.mode === "hit" ? "위험구역 손 감지 · 기계에서 떨어지세요"
                : hmi.mode === "hold" ? (hmi.left != null ? `구역 비움 · ${hmi.left.toFixed(1)}초 뒤 자동 재가동 · 계속 떨어져 있으세요` : "재가동 대기")
                : "정상 가동 중";
      big.innerHTML = `<div class="state t-${t}"><div class="small">프레스 #1</div>
          <div class="big" style="font-size:22px">${hmi.mode === "ok" ? "● 정상 가동" : "■ 안전 정지"}${hmi.mode === "hit" ? " · STOP" : ""}</div>
          <div class="small">${sub}</div></div>
        <div class="stat3" style="grid-template-columns:repeat(2,minmax(0,1fr))">
          <div><div class="small muted">오늘 생산</div><div class="v">${hmi.prod == null ? "-" : hmi.prod.toLocaleString()}</div></div>
          <div><div class="small muted">불량률 (오늘)</div><div class="v">${hmi.rate == null ? "-" : (hmi.rate * 100).toFixed(1) + "%"}</div></div></div>
        <div class="card" style="padding:12px 14px"><div class="small muted">보호구 (입장 시 확인)</div>
          <div class="c-ok" style="font-weight:600;margin-top:4px">✓ 안전모 · ✓ 조끼 · ✓ 장갑</div></div>`;
    }
  }
  // 오늘 생산 수량·불량률 (twin.html이 /api/dashboard 값으로 알려 줌)
  function hmiStats(prod, rate) { hmi.prod = prod; hmi.rate = rate; drawHmi(); }

  // ---------------------------------------------------------------- ① 안전 게이트
  // 벽 출입구 안쪽의 스피드 게이트: 정지선 → 카메라 아치(보호구 검사) → 날개 → 생산 구역
  //   작업자 · 날개 · 상태등 · 화면은 gateState()가 게이트 카메라 판정에 맞춰 바꿈
  const GATE_STAND = [-6.4, 3.4];                 // 정지선 앞 (검사 받는 자리)
  function gate() {
    let s = `<g class="eq gate" data-eq="${GATE_NAME}">`;
    { const a = P(-6.05, 2.75), b = P(-6.05, 4.05); s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#F5C542" stroke-width="3"/>`; }   // 정지선
    s += box(-5.75, -5.05, 2.65, 2.85, 0, 1.0, C.light) + box(-5.7, -5.1, 2.65, 2.85, 1.0, 1.04, ["#2A363E", "#222C33", "#1B242A"]);   // 뒤쪽 몸통
    s += box(-5.95, -5.83, 2.6, 2.72, 0, 2.3, C.eqb) + box(-5.95, -5.83, 3.98, 4.1, 0, 2.3, C.eqb) + box(-5.95, -5.83, 2.6, 4.1, 2.3, 2.42, C.eqb);   // 카메라 아치
    { const c = P(-5.83, 3.35, 2.36); s += `<circle cx="${c[0]}" cy="${c[1]}" r="4" fill="#0E1317" stroke="#4CC3FF" stroke-width="2"/>`;
      s += `<polygon id="gt-cone" points="${pts([P(-5.9, 3.2, 2.3), P(-5.9, 3.5, 2.3), P(-6.8, 3.95, 0), P(-6.8, 2.75, 0)])}" fill="#F5B544" opacity="0"/>`; }
    s += `<polygon id="gt-flapc" points="${pts([P(-5.4, 2.85, 0.95), P(-5.4, 3.95, 0.95), P(-5.4, 3.95, 0.45), P(-5.4, 2.85, 0.45)])}" fill="#56646C" opacity=".45" stroke="#56646C"/>`;
    s += `<g id="gt-flapo" style="display:none">${box(-5.5, -5.3, 2.85, 2.92, 0.45, 0.95, ["#3CC6A8", "#3CC6A8", "#3CC6A8"])}${box(-5.5, -5.3, 3.88, 3.95, 0.45, 0.95, ["#3CC6A8", "#3CC6A8", "#3CC6A8"])}</g>`;
    s += `<g id="gt-person"></g>`;                                                                    // 작업자 (판정에 따라 그림)
    s += box(-5.75, -5.05, 3.95, 4.15, 0, 1.0, C.light) + box(-5.7, -5.1, 3.95, 4.15, 1.0, 1.04, ["#2A363E", "#222C33", "#1B242A"]);   // 앞쪽 몸통
    // 상태 화면 (게이트 뒤쪽 · 작업자를 가리지 않게)
    s += box(-5.75, -5.55, 2.2, 2.35, 0, 1.25, C.eqb) + box(-5.95, -5.3, 2.18, 2.38, 1.25, 1.95, ["#3A4A54", "#222C33", "#1B242A"]);
    { const o = P(-5.92, 2.39, 1.91);
      s += `<g transform="matrix(${(0.866 * U / 100).toFixed(4)} ${(0.5 * U / 100).toFixed(4)} 0 1 ${o[0]} ${o[1]})">` +
        `<rect id="gt-kr" width="60" height="28" rx="3" fill="#1B242A" stroke="#56646C" stroke-width="1.5"/>` +
        [0, 1, 2].map(i => `<text id="gt-k${i}" x="30" y="${9 + i * 8.5}" font-size="${i ? 6.2 : 7.6}" font-weight="700" text-anchor="middle" fill="#93A3AD">${i ? "" : "정지선에 서 주세요"}</text>`).join("") + `</g>`; }
    { const c = P(-5.89, 3.35, 2.6); s += `<circle id="gt-light" cx="${c[0]}" cy="${c[1]}" r="6" fill="#56646C"/>`; }
    return s + `</g>`;
  }
  // 게이트 장면: modules.gate (items 보호구별 확인 · missing · all_on · hold_seconds · status)
  //   아무것도 안 보임 → 비어 있음 / 하나라도 보임 → 정지선에서 검사(노랑) / 2.5초 넘게 빠진 보호구 → 입장 불가(빨강, 돌아 나감)
  //   입장 허용 → 초록 · 날개 열림 · 작업자가 게이트를 지나 안으로 걸어감
  const gs = {phase: "idle", since: 0, key: ""};
  function gtPerson(face, walk, ppe, from, to, ms, fade) {
    const g = document.getElementById("gt-person"); if (!g) return;
    g.innerHTML = person(GATE_STAND[0], GATE_STAND[1], {face, walk, ppe});
    const a = D(from, 0), b = D(to, 0);
    g.style.transition = "none"; g.style.opacity = "1"; g.style.transform = `translate(${a[0]}px, ${a[1]}px)`;
    void g.getBoundingClientRect();
    g.style.transition = `transform ${ms}ms linear, opacity ${fade ? 400 : 0}ms linear ${fade ? ms - 400 : 0}ms`;
    g.style.transform = `translate(${b[0]}px, ${b[1]}px)`; if (fade) g.style.opacity = "0";
  }
  function gateState(status, g) {
    if (!document.getElementById("gt-light")) return;
    g = g || {}; const items = g.items || {}, labels = g.labels || {helmet: "안전모", vest: "조끼", gloves: "장갑"};
    const n = Object.values(items).filter(Boolean).length, now = performance.now();
    const prev = gs.phase;
    let want = status === "입장 허용" ? "pass" : n > 0 ? "check" : "idle";
    if (want === "check") { if (prev === "idle" || prev === "pass") gs.since = now; if ((g.missing || []).length && now - gs.since > 2500) want = "deny"; }
    if (want === "pass" && prev === "pass") want = "pass";
    gs.phase = want;
    const ppe = {helmet: !!items.helmet, vest: !!items.vest, gloves: !!items.gloves};
    const pk = JSON.stringify(ppe);
    if (want !== prev || (want !== "pass" && want !== "idle" && pk !== gs.key)) {
      gs.key = pk;
      if (want === "pass") gtPerson("+x", 1, {helmet: true, vest: true, gloves: true}, 0, 2.4, 2600, true);
      else if (want === "check" || want === "deny") gtPerson("+x", 0, ppe, prev === "idle" ? -0.8 : 0, 0, prev === "idle" ? 700 : 1, false);
      else if (prev === "check" || prev === "deny") gtPerson("-x", 1, ppe, 0, -1.4, 1600, true);
    }
    const col = {idle: ["#1B242A", "#56646C", "#93A3AD"], check: ["#2B2210", "#F5B544", "#FFD58A"], pass: ["#12302A", "#3CC6A8", "#7FE3C8"], deny: ["#2A1213", "#F0605D", "#FFB3B0"]}[want];
    const $ = id => document.getElementById(id);
    $("gt-light").setAttribute("fill", col[1]);
    $("gt-cone").setAttribute("fill", col[1]); $("gt-cone").setAttribute("opacity", want === "idle" ? "0" : ".14");
    $("gt-flapc").style.display = want === "pass" ? "none" : ""; $("gt-flapc").setAttribute("fill", want === "idle" ? "#56646C" : col[1]); $("gt-flapc").setAttribute("stroke", want === "idle" ? "#56646C" : col[1]);
    $("gt-flapo").style.display = want === "pass" ? "" : "none";
    $("gt-kr").setAttribute("fill", col[0]); $("gt-kr").setAttribute("stroke", col[1]);
    const chk = Object.entries(labels).map(([k, l]) => (items[k] ? "✓" : "…") + l).join(" ");
    const lines = want === "idle" ? [["정지선에 서 주세요", col[2]], ["", col[2]], ["", col[2]]]
      : want === "check" ? [["보호구 검사 중", col[2]], [chk, "#E7EDF0"], [g.all_on ? `유지 ${(g.hold_seconds || 0).toFixed(1)} / ${g.hold_target || 1}초` : "카메라를 보고 서 주세요", "#C9D3D8"]]
      : want === "deny" ? [["입장 불가", col[2]], ["✕ " + (g.missing || []).join(" · ") + " 없음", "#FFB3B0"], ["착용 후 다시", "#C9D3D8"]]
      : [["입장 허용", col[2]], ["✓안전모 ✓조끼 ✓장갑", "#7FE3C8"], ["안전한 작업 되세요", "#C9D3D8"]];
    lines.forEach(([t, c], i) => { const e = $("gt-k" + i); if (e.textContent !== t) e.textContent = t; e.setAttribute("fill", c); });
  }

  // ---------------------------------------------------------------- 정비원: '조치 중' 정비 요청이 있으면 그 설비 앞으로 걸어가고, 끝나면 정비 구역으로
  //   10/08: 직선 이동 → 바닥 통로(MECH_NODES · MECH_EDGES)만 따라 최단 경로로 걷는다.
  //          뒤 통로(y < MECH_BACK_Y)에서는 설비 뒤 자리(#tw-mech-back), 그 밖에서는 설비 앞 자리(#tw-mech-front)에 그려서
  //          설비 위에 떠 보이지 않게 한다. 걷는 동안 바닥에 경로 · 도착 자리, 머리 위에 이름표를 보여 준다.
  const MECH_FACE = {"프레스 #1": "+x", "컨베이어": "-y", "비전 검사기": "-x", "로봇 적재기": "+x", "자재 투입기": "+x"};
  const MECH_NODES = {
    home: MECH_HOME, a: [7.1, -2.75], vr: [7.9, -2.75], vb: [7.9, -1.4], l1: [-3.4, -2.75], l2: [-3.4, 3.3],
    ff: [-2.4, 3.3], fp: [2.5, 3.3], fc: [6.2, 3.3],
    "프레스 #1": MECH_SPOT["프레스 #1"], "컨베이어": MECH_SPOT["컨베이어"], "비전 검사기": MECH_SPOT["비전 검사기"],
    "로봇 적재기": MECH_SPOT["로봇 적재기"], "자재 투입기": MECH_SPOT["자재 투입기"],
  };
  const MECH_EDGES = [["home", "a"], ["a", "vr"], ["vr", "vb"], ["vb", "비전 검사기"], ["vb", "로봇 적재기"], ["a", "l1"], ["l1", "l2"],
    ["l2", "ff"], ["ff", "자재 투입기"], ["ff", "fp"], ["fp", "프레스 #1"], ["fp", "fc"], ["fc", "컨베이어"]];
  // 바닥 통로 띠 [x0, x1, y0, y1] (build()가 바닥에 옅게 그림)
  const MECH_AISLES = [[-3.75, 8.25, -3.1, -2.4], [-3.75, -3.05, -3.1, 3.65], [-3.75, 6.55, 2.95, 3.65], [7.55, 8.25, -2.4, -1.05], [8.25, 9.3, -1.75, -1.05]];
  const MECH_SPEED = 1.7, MECH_BACK_Y = 1.0;       // 걷는 속도(칸/초) · 이 y보다 뒤에 있으면 설비 뒤에 그림
  const mech = {at: "home", node: "home", pos: MECH_HOME.slice(), path: [], seg: 0, t0: 0, target: "home", next: null, ticket: null, raf: 0, face: "-y", step: 0};
  function mechPath(from, to) {                     // 간선 길이 기준 최단 경로 (노드 이름 배열)
    const adj = {}; MECH_EDGES.forEach(([a, b]) => { (adj[a] = adj[a] || []).push(b); (adj[b] = adj[b] || []).push(a); });
    const len = (a, b) => Math.hypot(MECH_NODES[a][0] - MECH_NODES[b][0], MECH_NODES[a][1] - MECH_NODES[b][1]);
    const dist = {[from]: 0}, prev = {}, todo = new Set(Object.keys(MECH_NODES));
    while (todo.size) {
      let u = null; todo.forEach(k => { if (dist[k] != null && (u == null || dist[k] < dist[u])) u = k; });
      if (u == null || u === to) break; todo.delete(u);
      (adj[u] || []).forEach(v => { const d = dist[u] + len(u, v); if (dist[v] == null || d < dist[v]) { dist[v] = d; prev[v] = u; } });
    }
    const out = [to]; while (out[0] !== from && prev[out[0]]) out.unshift(prev[out[0]]);
    return out[0] === from ? out : [from, to];
  }
  function mechDraw(walking) {
    const g = document.getElementById("tw-mech"); if (!g) return;
    const back = mech.pos[1] < MECH_BACK_Y, slot = document.getElementById(back ? "tw-mech-back" : "tw-mech-front");
    if (slot && g.nextSibling !== slot) slot.parentNode.insertBefore(g, slot);        // 설비 앞/뒤 자리로 옮기기
    const d = D(mech.pos[0] - MECH_HOME[0], mech.pos[1] - MECH_HOME[1]);
    g.style.transition = "none"; g.style.transform = `translate(${d[0]}px, ${d[1]}px)`;
    const walk = walking ? (Math.floor(performance.now() / 260) % 2 ? 1 : -1) : 0, key = mech.face + walk;
    if (g.dataset.k !== key) { g.dataset.k = key; g.innerHTML = person(MECH_HOME[0], MECH_HOME[1], {face: mech.face, walk}); }
    const tag = document.getElementById("tw-mech-tag");
    if (tag) {
      if (tag.nextElementSibling) tag.parentNode.appendChild(tag);      // 다른 표시(검사 카운트다운 등)보다 항상 위
      const p = P(mech.pos[0], mech.pos[1], mech.path.length === 0 && mech.target === "비전 검사기" ? 3.4 : 2.6), t = mech.target, here = mech.path.length === 0;
      const txt = here ? (t === "home" ? "" : `🔧 정비 중 · ${t}${mech.ticket ? ` · 요청 #${mech.ticket}` : ""}`)
                       : (t === "home" ? "정비 구역으로 복귀 중" : `→ ${t} 이동 중`);
      tag.style.display = txt ? "" : "none";
      if (txt) { const tx = tag.querySelector("text"), r = tag.querySelector("rect");
        if (tx.textContent !== txt) { tx.textContent = txt; const w = tx.getComputedTextLength ? tx.getComputedTextLength() + 24 : txt.length * 12 + 22; r.setAttribute("width", w); r.setAttribute("x", -w / 2); }
        tag.setAttribute("transform", `translate(${p[0]} ${p[1]})`); tag.classList.toggle("arrived", here); }
    }
  }
  function mechRoute(nodes) {                       // 바닥 경로 · 도착 자리 표시
    const r = document.getElementById("tw-mech-route"); if (!r) return;
    if (!nodes || nodes.length < 2) { r.innerHTML = ""; return; }
    const end = MECH_NODES[nodes[nodes.length - 1]], e = P(end[0], end[1]);
    r.innerHTML = `<polyline points="${pts(nodes.map(k => P(MECH_NODES[k][0], MECH_NODES[k][1])))}" />` +
      `<ellipse cx="${e[0]}" cy="${e[1]}" rx="22" ry="11"/>`;
  }
  function mechTick() {
    mech.raf = 0;
    if (!mech.path.length) return;
    const a = MECH_NODES[mech.path[mech.seg]], b = MECH_NODES[mech.path[mech.seg + 1]];
    const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 0.001, t = Math.min(1, (performance.now() - mech.t0) / 1000 * MECH_SPEED / L);
    const dx = b[0] - a[0], dy = b[1] - a[1];
    mech.face = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "+x" : "-x") : (dy > 0 ? "+y" : "-y");
    mech.pos = [a[0] + dx * t, a[1] + dy * t];
    if (t >= 1) {                                   // 다음 꼭짓점 도착
      mech.node = mech.path[mech.seg + 1]; mech.seg++; mech.t0 = performance.now();
      if (mech.next) { const n = mech.next; mech.next = null; mechGo(n); return; }     // 가는 중에 목적지가 바뀜 → 이 꼭짓점에서 다시 계산
      if (mech.seg >= mech.path.length - 1) {     // 목적지 도착
        mech.path = []; mech.at = mech.target;
        mech.face = mech.target === "home" ? "-y" : MECH_FACE[mech.target] || "-y";
        if (mech.target === "home") mechRoute(null); else document.getElementById("tw-mech-route")?.classList.add("done");
        mechDraw(false); return;
      }
    }
    mechDraw(true); mech.raf = requestAnimationFrame(mechTick);
  }
  function mechGo(tgt) {
    mech.target = tgt; mech.at = "moving";
    mech.path = mechPath(mech.node, tgt); mech.seg = 0; mech.t0 = performance.now();
    if (mech.path.length < 2) { mech.path = []; mech.at = tgt; mechDraw(false); return; }
    mechRoute(mech.path); document.getElementById("tw-mech-route")?.classList.remove("done");
    if (!mech.raf) mech.raf = requestAnimationFrame(mechTick);
  }
  function mechMove(tickets) {
    const doing = (tickets || []).find(t => t.status === "조치 중" && MECH_SPOT[t.equipment]);
    const tgt = doing ? doing.equipment : "home";
    mech.ticket = doing ? doing.id : null;
    if (!document.getElementById("tw-mech")) return;
    if (tgt === mech.target) { if (!mech.path.length) mechDraw(false); return; }
    if (mech.path.length) { mech.next = tgt; mech.target = tgt; return; }    // 걷는 중: 다음 꼭짓점에서 방향을 바꿈
    mechGo(tgt);
  }
  const mechAt = () => mech.at;

  // ---------------------------------------------------------------- ⑥ 출하장 (트럭 + 지게차)
  const C2 = {light: ["#D7DEE2", "#AEB9C0", "#97A3AA"], yellow: ["#F5C542", "#D9A92A", "#C29522"], blue: ["#3E7BD6", "#2E5FA8", "#264F8C"],
              dark: ["#26323A", "#1B242A", "#151C21"], wood: ["#9A7B55", "#7D6343", "#6A5439"], glass: ["#9FD3F5", "#7FB8DE", "#6AA3C9"]};
  // 바퀴: 옆면(x = 일정한 면)에 붙은 납작한 원 → 비스듬히 보이므로 타원(다각형)으로 그림
  const wheel = (x, y, z, r) => {
    const ring = (rr) => pts(Array.from({length: 20}, (_, i) => { const a = i / 20 * 2 * Math.PI; return P(x, y + rr * Math.cos(a), z + rr * Math.sin(a)); }));
    return `<polygon points="${ring(r)}" fill="#151C21" stroke="#3A4852" stroke-width="1.5"/>` +
           `<polygon points="${ring(r * 0.45)}" fill="#7C8A93" stroke="#56646C" stroke-width="1"/>`;
  };
  function shipping() {
    const sd = D(SHIP_DX, 0);
    let s = `<g class="eq ship" data-eq="${SHIP_NAME}" transform="translate(${sd[0].toFixed(1)} ${sd[1].toFixed(1)})">`;
    // 트럭: 운전석 + 짐칸 (뒷문이 앞쪽을 보고 열려 있고 안에 상자)
    const TW = [-4.45, -2.65, -2.05];                       // 바퀴 위치(앞바퀴 1, 뒷바퀴 2)
    s += `<g id="tw-truck">`;                                // 정각(LOT 끝)에 이 묶음이 앞으로 나가며 출발 → 빈 트럭이 후진해 들어옴
    s += TW.map(y => wheel(13.3, y, 0.3, 0.3)).join("");    // 반대편 바퀴: 차체에 가려 아래만 살짝 보임
    s += box(13.2, 14.8, -4.8, -4.2, 0.35, 1.75, C2.blue) + box(13.4, 14.6, -4.8, -4.5, 1.2, 1.7, C2.glass);
    s += box(13.2, 14.8, -4.2, -1.7, 0.35, 2.05, C2.light);
    const door = pts([P(13.3, -1.7, 0.42), P(14.7, -1.7, 0.42), P(14.7, -1.7, 1.95), P(13.3, -1.7, 1.95)]);
    s += `<clipPath id="truck-door"><polygon points="${door}"/></clipPath><polygon points="${door}" fill="#1B242A"/>`;
    s += `<g clip-path="url(#truck-door)">` +                  // 짐칸 안 상자는 뒷문 구멍 안쪽만 보이게 (LOT 적재량에 따라 0~3개)
      `<g id="tb0">${box(13.45, 13.95, -2.3, -1.8, 0.42, 0.9, C.box)}</g><g id="tb1">${box(14.05, 14.55, -2.3, -1.8, 0.42, 0.9, C.box)}</g>` +
      `<g id="tb2">${box(13.7, 14.2, -2.3, -1.8, 0.9, 1.38, C.box)}</g></g>`;
    s += box(14.78, 14.8, -4.8, -1.7, 0.33, 0.37, C2.dark);   // 차체 아래 테두리
    s += TW.map(y => wheel(14.82, y, 0.3, 0.3)).join("") + `</g>`;   // 보이는 쪽 바퀴 (옆면에 붙임)
    // 지게차 (트럭 쪽을 보고 서 있는 위치로 그림 → lineLoop()가 앞뒤로 움직임)
    const [f0, f1, fy] = FORK;
    s += `<g id="tw-fork"><g id="tw-fork-load">` + box(f0 + 0.05, f1 - 0.05, fy - 0.75, fy - 0.1, 0.3, 0.42, C2.wood) +
      box(f0 + 0.1, f0 + 0.45, fy - 0.7, fy - 0.42, 0.42, 0.8, C.box) + box(f0 + 0.55, f0 + 0.9, fy - 0.7, fy - 0.42, 0.42, 0.8, C.box) +
      box(f0 + 0.1, f0 + 0.45, fy - 0.4, fy - 0.12, 0.42, 0.8, C.box) + box(f0 + 0.55, f0 + 0.9, fy - 0.4, fy - 0.12, 0.42, 0.8, C.box) + `</g>` +
      box(f0 - 0.02, f1 + 0.02, fy - 0.08, fy, 0.1, 1.75, C.steel) +
      box(f0, f1, fy, fy + 1.0, 0.15, 0.75, C2.yellow) + box(f0, f1, fy + 0.75, fy + 1.05, 0.15, 0.95, C2.dark) +
      box(f0 + 0.02, f0 + 0.08, fy + 0.05, fy + 0.11, 0.75, 1.6, C2.dark) + box(f1 - 0.08, f1 - 0.02, fy + 0.05, fy + 0.11, 0.75, 1.6, C2.dark) +
      box(f0 + 0.02, f0 + 0.08, fy + 0.7, fy + 0.76, 0.75, 1.6, C2.dark) + box(f1 - 0.08, f1 - 0.02, fy + 0.7, fy + 0.76, 0.75, 1.6, C2.dark) +
      person(f0 + 0.5, fy + 0.42, {face: "-y", z: 0.2, scale: 0.7, seated: true}) +
      box(f0, f1, fy + 0.05, fy + 0.76, 1.6, 1.66, C2.dark) + wheel(f1 + 0.02, fy + 0.2, 0.17, 0.17) + wheel(f1 + 0.02, fy + 0.85, 0.17, 0.17) + `</g>`;
    return s + `</g>`;
  }
  // ---------------------------------------------------------------- ⑥ 팔레트 적재 → 지게차 → 트럭 출발
  // 양품 8개 = 1팔레트 → 지게차가 트럭에 실음 → 10팔레트(80개)가 실리면 트럭 출발 = LOT 1개 출하
  // ★ 화면의 숫자는 '로봇이 상자를 내려놓는 순간'에만 1씩 늘어난다 (팔레트 · 지게차 · 트럭 · 안내판이 로봇과 같은 박자)
  //   실제 모드: DB 양품 수(ship.target, 5초마다 TW.lot)를 목표로, 로봇이 내려놓을 때마다 따라감
  //             → 검사는 끝났지만 아직 벨트 위에 있는 제품(보통 1~2개)만큼 화면이 DB보다 살짝 늦는 게 정상
  //             → 쌓을 제품이 없으면 로봇은 팔레트 위에서 기다림 (빈손으로 내려놓는 동작 없음)
  //   시뮬레이션 모드: 최근 2분 동안 검사 기록이 없으면(카메라 꺼짐) 로봇이 놓는 대로 셈
  const ship = {size: 8, trucks: 10, live: null, mode: "sim", target: null, shown: 0, onTruck: 0, simSeq: 1,
                fork: null, forkQ: 0, departNext: null, departing: false, msg: null};
  const FORK_SEC = 4.4;                     // 지게차 왕복 (가는 1.8초 · 내려놓기 0.6초 · 돌아오기 1.8초)
  const lotGood = () => ship.size * ship.trucks;
  const mmin = s => s < 60 ? Math.round(s) + "초" : Math.round(s / 60) + "분";

  // 팔레트 위 상자 n개 (아래층부터, 뒤쪽부터 그려야 겹침이 맞음)
  let stackN = -1;
  function setStack(n) {
    const g = document.getElementById("tw-pallet"); if (!g || n === stackN) return;
    stackN = n; let h = "";
    for (let k = 0; k < Math.min(n, 8); k++) {
      const z = Math.floor(k / 4), x = Math.floor(k % 4 / 2), y = k % 2, x0 = 11.25 + x * 0.58, y0 = -1.15 + y * 0.66;
      h += box(x0, x0 + 0.54, y0, y0 + 0.6, 0.25 + z * 0.48, 0.71 + z * 0.48, C.box);
    }
    g.innerHTML = h;
  }
  // 지게차 한 번 왕복 (라인 시계 기준이라 라인이 멈추면 같이 멈춤). 팔레트를 트럭에 내려놓는 순간 onTruck +1
  function forkTrip() { if (ship.fork == null) { ship.fork = lineT; ship.dropped = false; } else ship.forkQ++; }
  function forkAt(t) {            // → [트럭 쪽으로 간 비율 0~1, 팔레트를 들고 있나]
    if (ship.fork == null) return [0, false];
    const u = t - ship.fork;
    if (u >= 2.1 && !ship.dropped) {                 // 트럭에 내려놓음
      ship.dropped = true; ship.onTruck = Math.min(ship.trucks, ship.onTruck + 1);
      if (ship.departNext && ship.onTruck >= ship.trucks) { const i = ship.departNext; ship.departNext = null; depart(i); }
      else drawLot();
    }
    if (u >= FORK_SEC) {
      if (ship.forkQ > 0) { ship.forkQ--; ship.fork = t; ship.dropped = false; } else ship.fork = null;
      return [0, false];
    }
    if (u < 1.8) return [ease(u / 1.8), true];
    if (u < 2.4) return [1, u < 2.1];
    return [1 - ease(Math.min(1, (u - 2.4) / 1.8)), false];
  }

  // 화면 숫자를 n으로 바로 맞춤 (처음 열 때 · 모드가 바뀔 때 · 날짜가 바뀌거나 많이 밀렸을 때)
  function snap(n) {
    ship.shown = n; ship.onTruck = Math.floor(n / ship.size) % ship.trucks;
    ship.fork = null; ship.forkQ = 0; ship.departNext = null;
    drawLot();
  }
  // 로봇이 상자 1개를 내려놓음 → 8개면 지게차 출발 → 10팔레트째를 실으면 트럭 출발
  function addOne() {
    ship.shown++;
    if (ship.shown % ship.size === 0) {
      forkTrip();
      if (ship.shown % lotGood() === 0) {
        const L = ship.mode === "live" && ship.live;
        ship.departNext = L ? (L.last_shipped || L.current) : {id: `시뮬레이션 ${ship.simSeq++}`};
        ship.departNext = {id: ship.departNext.id, pallets: ship.trucks, good: lotGood()};
      }
    }
    drawLot();
  }
  // 실제 모드에서 아직 팔레트에 못 올라간(벨트 위) 양품 수
  const pending = () => ship.mode === "live" && ship.target != null ? ship.target - ship.shown : Infinity;

  // /api/production 결과 받기 (twin.html이 5초마다 호출)
  function lot_(d) {
    if (!d || !d.current) return;
    if (flowOn()) { ship.live = d; return; }                   // 새 흐름: 팔레트 · 트럭 숫자는 장부(FLOW)가 정함
    ship.size = d.pallet_size; ship.trucks = d.truck_pallets;
    const c = d.current, fresh = c.last_insp && d.now - c.last_insp < 120;
    const was = ship.mode, prev = was === "live" && ship.live ? ship.live.current : null;
    ship.live = d;
    if (!fresh) { ship.mode = "sim"; ship.target = null; drawLot(); return; }
    ship.mode = "live";
    ship.target = d.today.shipped_good + c.good;               // 오늘 누적 양품 (트럭에 실린 것 + 지금 LOT)
    // 처음 · 시뮬레이션에서 넘어옴 · 날짜 바뀜(숫자 감소) · 많이 밀림(탭이 백그라운드였음) → 바로 맞춤
    const gap = ship.target - ship.shown;
    if (was !== "live" || gap < 0 || gap > 6) snap(Math.max(0, ship.target - 2));   // 2개 = 검사 후 벨트 위에 있는 제품
    // 시뮬레이터가 만든 불량은 품질 카메라 상태에 안 잡히므로, 불량 수가 늘면 여기서 빨간 제품을 분기시킴
    if (prev && d.sim && prev.id === c.id && c.defects > prev.defects)
      for (let i = 0; i < Math.min(3, c.defects - prev.defects); i++) setTimeout(() => spawnDefect("시뮬레이션"), i * 700);
    drawLot();
  }
  // 로봇이 집게를 놓는 순간 (lineLoop가 호출)
  //   실제 생산이 로봇 박자(4초)보다 빨라 밀리면(벨트 위 5개 이상) 한 번에 2개씩 쌓아 따라잡음
  function robotPlaced() { if (pending() > 0) addOne(); if (pending() > 4) addOne(); }

  function drawLot() {
    const g = document.getElementById("tw-lot"); if (!g) return;
    g.style.display = "";
    const live = ship.mode === "live" && ship.live, d = ship.live;
    const fill = ship.shown % ship.size;
    setStack(fill);
    const t = k => g.querySelector(".lb-" + k);
    if (ship.msg) {                                                              // 출발 직후: 출하 완료 안내
      g.classList.add("done");
      t("t1").textContent = `LOT ${ship.msg.id} 출하 완료`;
      t("t2").textContent = `팔레트 ${ship.msg.pallets}개 · 양품 ${ship.msg.good.toLocaleString()}개`;
      t("t3").textContent = ""; t("bar").setAttribute("width", 218);
    } else if (flowOn() && ship.flow) {
      g.classList.remove("done");
      const c = ship.flow, st = FLOW.status(), left = lotGood() - c.placed % lotGood();
      t("t1").textContent = `LOT ${c.lot} · 적재 중`;
      t("t2").textContent = `팔레트 ${ship.onTruck} / ${ship.trucks}`;
      t("t3").textContent = st && st.kind !== "ok" ? st.short : `출발까지 양품 ${left}개`;
      t("bar").setAttribute("width", (218 * Math.min(1, (ship.onTruck + fill / ship.size) / ship.trucks)).toFixed(1));
    } else {
      g.classList.remove("done");
      // 화면에서 적재 중인 LOT: DB가 이미 다음 LOT으로 넘어갔어도 트럭이 아직 안 떠났으면 직전 LOT 번호
      const lotIdx = Math.floor(ship.shown / lotGood());
      const id = live ? (lotIdx < d.today.trucks && d.last_shipped ? d.last_shipped.id : d.current.id) : null;
      const leftGood = lotGood() - ship.shown % lotGood();
      // 예상 출발: 실제 모드는 서버 계산(최근 10분 속도), 직전 LOT 마무리 중이거나 시뮬레이션이면 남은 개수 × 사이클
      const eta = live && lotIdx >= d.today.trucks ? d.current.eta_sec : leftGood * CYCLE;
      t("t1").textContent = live ? `LOT ${id} · 적재 중` : "시뮬레이션 · 품질 카메라 대기";
      t("t2").textContent = `팔레트 ${ship.onTruck} / ${ship.trucks}`;
      // 실제 모드인데 새 검사 기록이 없어 로봇이 기다리는 중이면 그 이유를 표시 (멈춘 것처럼 보이지 않게)
      const idle = live && pending() <= 0 && d.current.last_insp ? d.now - d.current.last_insp : 0;
      t("t3").textContent = idle > 8 ? `검사 기록 대기 · ${mmin(idle)} 전` : `출발 ≈ ${mmin(eta)}`;
      t("bar").setAttribute("width", (218 * Math.min(1, (ship.onTruck + fill / ship.size) / ship.trucks)).toFixed(1));
    }
    // 짐칸 상자 0~3개: 트럭에 실린 팔레트 비율만큼 (출발 중에는 꽉 찬 상태)
    const f = ship.departing ? 1 : ship.onTruck / ship.trucks;
    ["tb0", "tb1", "tb2"].forEach((id, i) => { const b = document.getElementById(id);
      if (b) b.style.visibility = (ship.departing || ship.onTruck > 0) && f > i / 3 ? "" : "hidden"; });
  }
  // 트럭 출발: 앞으로 나가며 사라짐 → 빈 트럭이 후진해서 들어옴 (6초), 안내판은 10초 동안 '출하 완료'
  function depart(info) {
    const tr = document.getElementById("tw-truck"); if (!tr || ship.departing) return;
    ship.departing = true;
    ship.msg = {id: info.id, pallets: info.pallets ?? ship.trucks, good: info.good ?? 0};
    const out = D(0, -4.5), k = (d, op, off) => ({transform: `translate(${d[0].toFixed(1)}px, ${d[1].toFixed(1)}px)`, opacity: op, offset: off});
    const a = tr.animate([k([0, 0], 1, 0), k(out, 0, 0.45), k(out, 0, 0.55), k([0, 0], 1, 1)], {duration: 6000, easing: "ease-in-out"});
    setTimeout(() => { ship.departing = false; ship.onTruck = 0; drawLot(); }, 3100);   // 화면 밖에 있을 때 짐칸 비우기
    a.onfinish = () => setTimeout(() => { ship.msg = null; drawLot(); }, 4000);
    drawLot();
  }

  function build() {
    let s = "", trees = "";
    // 바닥과 격자
    s += `<polygon points="${pts([P(-6, -5.2), P(18, -5.2), P(18, 6.6), P(-6, 6.6)])}" fill="#151E23"/>`;
    s += `<g stroke="#1E2A31" stroke-width="1">`;
    for (let i = -6; i <= 18; i++) { const a = P(i, -5.2), b = P(i, 6.6); s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>`; }
    for (let j = -5; j <= 6; j++) { const a = P(-6, j), b = P(18, j); s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>`; }
    s += `</g>`;
    // 공장 벽 (뒤쪽 두 면) · 창문 · 비상구 · 로고 · 출입구(게이트 자리)
    { const WALL = ["#2A363E", "#1E282E", "#222C33"], H = 2.9;
      s += `<polygon points="${pts([P(-7.0, 2.65), P(-6, 2.65), P(-6, 4.15), P(-7.0, 4.15)])}" fill="#1B242A"/>`;     // 출입구 밖 바닥
      s += box(-6.25, -6, -5.45, 2.6, 0, H, WALL) + box(-6.25, -6, 2.6, 4.2, 2.35, H, WALL);        // 왼쪽 벽 + 출입구 위
      // 건물 밖 (출하장): 아스팔트 · 주차선 · 울타리 · 나무 · 가로등
      const XE = 13.9;                                                                              // 건물 끝 (출하 문)
      s += `<polygon points="${pts([P(XE, -5.2), P(18, -5.2), P(18, 6.6), P(XE, 6.6)])}" fill="#191D21"/>`;
      s += `<g stroke="#20262B" stroke-width="1">` + [-4, -2, 0, 2, 4, 6].map(j => { const a = P(XE, j), b = P(18, j); return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"/>`; }).join("") + `</g>`;
      [2.6, 4.2, 5.8].forEach(y => { const a = P(15.2, y), b = P(17.6, y); s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#C9D3D8" stroke-width="2" opacity=".5"/>`; });   // 주차선
      { const t = P(16.4, 3.4); s += `<text x="${t[0]}" y="${t[1]}" font-size="12" fill="#93A3AD" text-anchor="middle" transform="rotate(30 ${t[0]} ${t[1]})">건물 밖 · 출하 도로</text>`; }
      s += box(-6, XE, -5.45, -5.2, 0, H, WALL);                                                      // 뒤 벽 (건물 안)
      // (트럭 앞은 울타리 없이 도로로 열려 있음)
      s += `<polygon points="${pts([P(XE, -6.6), P(18, -6.6), P(18, -5.2), P(XE, -5.2)])}" fill="#191D21"/>`;
      [15.0, 16.6].forEach(x => { const a = P(x, -6.5), b = P(x, -5.3); s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#F5C542" stroke-width="2" stroke-dasharray="10 8" opacity=".5"/>`; });
      const tree = (x, y) => box(x - 0.06, x + 0.06, y - 0.06, y + 0.06, 0, 0.6, ["#6A5439", "#5A4630", "#4A3A28"]) +
        box(x - 0.4, x + 0.4, y - 0.4, y + 0.4, 0.6, 1.2, ["#3E8E5E", "#2E6E48", "#26593B"]) + box(x - 0.28, x + 0.28, y - 0.28, y + 0.28, 1.2, 1.65, ["#4CA870", "#3A8257", "#2F6B47"]);
      trees = tree(17.6, 5.4) + tree(16.0, 6.4);                                   // 맨 앞 레이어에 그림 (벽에 안 가려지게)
      s += box(17.6, 17.66, 1.9, 1.96, 0, 2.6, C.steel) + box(17.2, 17.66, 1.88, 1.98, 2.55, 2.62, C.steel);   // 가로등
      { const l = P(17.25, 1.93, 2.53); s += `<circle cx="${l[0]}" cy="${l[1]}" r="4" fill="#FFE9A8"/>`; }
      // 건물 오른쪽 벽: 낮게 잘라 보여줌(안이 보이게) + 출하 문(셔터 올라감)
      const DY0 = -2.1, DY1 = 0.7;
      s += box(XE - 0.25, XE, -5.2, DY0, 0, 0.55, WALL) + box(XE - 0.25, XE, DY1, 6.6, 0, 0.55, WALL);
      s += box(XE - 0.25, XE, -5.2, -4.95, 0, H, WALL);                                              // 뒤 모서리 기둥
      s += box(XE - 0.25, XE, DY0 - 0.15, DY0, 0, H, WALL) + box(XE - 0.25, XE, DY1, DY1 + 0.15, 0, H, WALL) + box(XE - 0.25, XE, DY0, DY1, H - 0.45, H, WALL);
      s += box(XE - 0.2, XE + 0.05, DY0, DY1, H - 0.75, H - 0.45, ["#8C99A1", "#6A7A84", "#5A6B76"]);  // 말려 올라간 셔터
      s += hazard(XE + 0.0, XE + 0.0, DY1, 0, 0);
      { const o = P(XE, DY0 + 0.1, H - 0.08); s += `<text transform="matrix(0 0 0 1 0 0)"></text>`; }
      s += `<polygon points="${pts([P(XE - 0.6, DY0, 0.01), P(XE + 0.5, DY0, 0.01), P(XE + 0.5, DY1, 0.01), P(XE - 0.6, DY1, 0.01)])}" fill="#F5C542" opacity=".18"/>`;   // 도크 바닥
      const win = (x0, x1) => `<polygon points="${pts([P(x0, -5.2, 1.75), P(x1, -5.2, 1.75), P(x1, -5.2, 2.55), P(x0, -5.2, 2.55)])}" fill="#16303D" stroke="#2E5566" stroke-width="1.5"/>` +
        `<line x1="${P((x0 + x1) / 2, -5.2, 1.75)[0]}" y1="${P((x0 + x1) / 2, -5.2, 1.75)[1]}" x2="${P((x0 + x1) / 2, -5.2, 2.55)[0]}" y2="${P((x0 + x1) / 2, -5.2, 2.55)[1]}" stroke="#2E5566" stroke-width="1.5"/>`;
      [[-2.6, -1.0], [3.4, 5.0], [6.0, 7.6], [13.0, 14.6]].forEach(([a, b]) => s += win(a, b));
      const winL = (y0, y1) => `<polygon points="${pts([P(-6, y0, 1.75), P(-6, y1, 1.75), P(-6, y1, 2.55), P(-6, y0, 2.55)])}" fill="#16303D" stroke="#2E5566" stroke-width="1.5"/>`;
      s += winL(-1.6, -0.2) + winL(0.4, 1.8);
      // 비상구 (뒤 벽 문 + 초록 표시)
      s += `<polygon points="${pts([P(1.2, -5.2, 0), P(2.3, -5.2, 0), P(2.3, -5.2, 2.0), P(1.2, -5.2, 2.0)])}" fill="#3A464E" stroke="#56646C"/>`;
      s += `<polygon points="${pts([P(1.35, -5.2, 2.12), P(2.15, -5.2, 2.12), P(2.15, -5.2, 2.45), P(1.35, -5.2, 2.45)])}" fill="#1F8A5A"/>`;
      { const o = P(1.38, -5.2, 2.42); s += `<text transform="matrix(0.866 0.5 0 1 ${o[0]} ${o[1]})" x="0" y="11" font-size="10" font-weight="800" fill="#E7FFF3">🏃 비상구</text>`; }
      { const o = P(8.6, -5.2, 2.55); s += `<text transform="matrix(0.866 0.5 0 1 ${o[0]} ${o[1]})" x="0" y="22" font-size="24" font-weight="800" fill="#3A4A54" letter-spacing="3">SMART LINE</text>`; }
      // 바닥 안내: 출입구 앞 '보호구 착용 구역'
      { const o = P(-5.9, 4.5); s += `<text x="${o[0]}" y="${o[1] + 12}" font-size="10" fill="#F5C542" opacity=".8" transform="rotate(30 ${o[0]} ${o[1]})">⚠ 보호구 착용 구역</text>`; }
    }
    // 작업자 동선 (게이트 → 프레스 앞, 초록 점선) · 출하 동선 (팔레트 → 트럭, 파란 점선)
    s += `<polyline points="${pts([P(GATE[1] + 0.1, 3.45), P(0.4, 3.45), P(0.4, 4.4), P(3.0, 4.4)])}" fill="none" stroke="#7FE3C8" stroke-width="3" stroke-dasharray="4 8" stroke-linecap="round" opacity=".7"/>`;
    s += `<polyline points="${pts([P(12.45, -0.5), P(14.7, -0.5), P(14.7, 0.2)])}" fill="none" stroke="#4CC3FF" stroke-width="3" stroke-dasharray="10 8" opacity=".7"/>`;
    // 출하장 바닥 (노란 점선 구역) · 게이트 통과 매트 (초록)
    s += `<polygon points="${pts([P(14.3, -5.0), P(17.6, -5.0), P(17.6, 1.6), P(14.3, 1.6)])}" fill="#1A2228" stroke="#F5C542" stroke-width="2" stroke-dasharray="10 6"/>`;
    s += `<polygon points="${pts([P(GATE[0] + 0.05, GATE[2] - 0.1), P(GATE[1] - 0.05, GATE[2] - 0.1), P(GATE[1] - 0.05, GATE[3] + 0.5), P(GATE[0] + 0.05, GATE[3] + 0.5)])}" fill="#12302A" stroke="#3CC6A8" stroke-width="1.5"/>`;

    // 안전 통로 (노란 선) · 설비 그림자
    { const a = P(0.4, 5.55), b = P(7.6, 5.55), c = P(0.4, 5.8), d = P(7.6, 5.8);
      s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#F5C542" stroke-width="2.5" opacity=".55"/>` +
           `<line x1="${c[0]}" y1="${c[1]}" x2="${d[0]}" y2="${d[1]}" stroke="#F5C542" stroke-width="2.5" opacity=".55"/>`;
      const t = P(5.6, 5.67); s += `<text x="${t[0]}" y="${t[1] + 4}" fill="#8A7A4A" font-size="11" text-anchor="middle" font-family="IBM Plex Sans KR, sans-serif" transform="rotate(30 ${t[0]} ${t[1]})">작업자 통로</text>`; }
    s += shadow(0, 12, 1, 2) + shadow(3, 4.6, 0.4, 2.6) + shadow(6.95, 7.45, -0.3, 0.95) + shadow(ROBOT[0] - 0.45, ROBOT[0] + 0.45, ROBOT[1] - 0.45, ROBOT[1] + 0.45) +
         shadow(11.2, 12.4, -1.2, 0.2);

    // AMR 통로 (컨베이어 왼쪽 끝) + 노란 유도선
    s += `<polygon points="${pts([P(-3.9, 0.8), P(0, 0.8), P(0, 2.2), P(-3.9, 2.2)])}" fill="#172127"/>`;
    { const a = P(-3.1, 1.5), b = P(-0.1, 1.5);
      s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#F5B544" stroke-width="2" stroke-dasharray="10 8" opacity=".55"/>`; }

    // ② 위험구역 (바닥에 붙어 있으므로 가장 먼저)
    s += `<g id="tw-zone" class="zone"><polygon class="zf" points="${pts(ZONE)}"/>` +
         `<polygon class="zl" points="${pts(ZONE)}"/></g>`;
    // ④ 병목 설비 바닥 표시 (가정 시뮬레이션에서만 보임)
    s += `<polygon id="tw-focus" class="focusfloor" points=""/>`;
    // 정비원 통로 (바닥 옅은 띠) · 걷는 경로와 도착 자리 (10/08)
    s += `<g class="mech-aisle">` + MECH_AISLES.map(([x0, x1, y0, y1]) => `<polygon points="${pts([P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)])}"/>`).join("") + `</g>`;
    s += `<g id="tw-mech-route" class="mech-route"></g>`;

    // ---- 뒤쪽 (컨베이어보다 먼저 그려야 가려지는 것들) ----
    // 자재 창고: 격자 위쪽 모서리 (알루미늄 판 묶음)
    { const X0r = -5.6, X1r = -3.5, Y0r = -4.9, Y1r = -3.75, post = (x, y) => box(x, x + 0.07, y, y + 0.07, 0, 2.1, C.eqb);
      s += shadow(X0r, X1r, Y0r, Y1r);
      s += post(X0r, Y0r) + post(X1r - 0.07, Y0r) + post(X0r + 1.03, Y0r);
      [0.25, 0.95, 1.65].forEach(z => { s += box(X0r, X1r, Y0r, Y1r, z, z + 0.06, C.beam);
        [0, 1, 2, 3].forEach(i => { if (z > 1.5 && i === 3) return; s += mat(X0r + 0.08 + i * 0.5, X0r + 0.5 + i * 0.5, Y0r + 0.15, Y1r - 0.12, z + 0.06, z + 0.5); }); });
      s += post(X0r, Y1r - 0.07) + post(X1r - 0.07, Y1r - 0.07) + post(X0r + 1.03, Y1r - 0.07);
      // AMR 통로 (창고 앞 → 아래로 → 컨베이어 입구)
      s += `<polygon points="${pts([P(-5.2, -3.6), P(-3.8, -3.6), P(-3.8, 2.2), P(-5.2, 2.2)])}" fill="#172127"/>`;
      s += `<polygon points="${pts([P(-5.2, 0.8), P(-1.1, 0.8), P(-1.1, 2.2), P(-5.2, 2.2)])}" fill="#172127"/>`;
      s += `<polyline points="${pts([P(-4.5, -3.4), P(-4.5, 1.5), P(-1.3, 1.5)])}" fill="none" stroke="#F5B544" stroke-width="2.5" stroke-dasharray="10 8" opacity=".8"/>`;
      // 자재 투입기 = AMR(4개씩 운반) + 투입 대기 칸(4칸 → 5초마다 1개씩 컨베이어로) · 차콜 + 노랑 포인트
      const YEL = ["#F5C542", "#D9A92A", "#C29522"];
      let amr = "";
      { const [cx, cy] = AMR_W, x0 = cx - 0.5, x1 = cx + 0.5, y0 = cy - 0.45, y1 = cy + 0.45, lid = P(cx, y1 + 0.02, 0.5);
        amr = `<g id="tw-amr">` + box(x0 + 0.08, x0 + 0.22, y1 - 0.12, y1, 0, 0.1, C.rub) + box(x1 - 0.22, x1 - 0.08, y1 - 0.12, y1, 0, 0.1, C.rub) +
          box(x0, x1, y0, y1, 0.06, 0.42, C.eqb) + box(x0, x1, y1 - 0.02, y1, 0.28, 0.34, YEL) + hazard(x0 + 0.05, x1 - 0.05, y1, 0.1, 0.18) +
          `<circle class="tw-lidar" cx="${lid[0]}" cy="${lid[1]}" r="3" fill="#4CC3FF"/>` +
          `<g id="tw-amr-cargo">` + mat(x0 + 0.08, x0 + 0.48, y0 + 0.05, y0 + 0.43, 0.42, 0.8) + mat(x0 + 0.52, x0 + 0.92, y0 + 0.05, y0 + 0.43, 0.42, 0.8) +
          mat(x0 + 0.08, x0 + 0.48, y0 + 0.47, y0 + 0.85, 0.42, 0.8) + mat(x0 + 0.52, x0 + 0.92, y0 + 0.47, y0 + 0.85, 0.42, 0.8) + `</g></g>`; }
      const rack = box(-1.05, -0.1, 1.05, 1.95, 0, 0.32, C.eqb) + box(-1.0, -0.15, 1.05, 1.12, 0.32, 0.5, C.eqb) + box(-1.05, -0.1, 1.93, 1.95, 0.22, 0.28, YEL) +
        [[-0.95, -0.6, 1.15, 1.5], [-0.55, -0.2, 1.15, 1.5], [-0.95, -0.6, 1.55, 1.9], [-0.55, -0.2, 1.55, 1.9]]
          .map(([a, b, c, d], i) => `<g id="tw-buf${i}">${mat(a, b, c, d, 0.32, 0.72)}</g>`).join("");
      s += part("자재 투입기", amr + rack);
    }
    // 정비 구역 (뒤쪽 빈 바닥): 작업대 · 공구함 · 예비 부품 선반 · 정비원
    { const X0 = 4.6, X1 = 9.4, Y0 = -5.0, Y1 = -3.0;
      s += `<g class="eq place mech" data-eq="${MECH_NAME}">`;
      s += `<polygon points="${pts([P(X0, Y0), P(X1, Y0), P(X1, Y1), P(X0, Y1)])}" fill="#14232C" stroke="#4CC3FF" stroke-width="1.5" stroke-dasharray="8 6" opacity=".9"/>`;
      { const t = P(X0 + 0.3, Y1 - 0.2); s += `<text x="${t[0]}" y="${t[1]}" font-size="11" fill="#4CC3FF" opacity=".8" transform="rotate(-30 ${t[0]} ${t[1]})">🔧 정비 구역</text>`; }
      const RED = ["#C0453F", "#9A3430", "#7E2A27"], WOOD = ["#9A7B55", "#7D6343", "#6A5439"];
      s += box(5.0, 5.9, -4.95, -4.45, 0, 1.7, RED) + box(5.05, 5.85, -4.45, -4.44, 0.2, 1.6, ["#B03F3A", "#B03F3A", "#B03F3A"]);   // 공구함
      [0.45, 0.85, 1.25].forEach(z => { const a = P(5.1, -4.44, z), b = P(5.8, -4.44, z); s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#5E1C1A" stroke-width="1.5"/>`; });
      s += box(6.3, 7.9, -4.9, -4.2, 0.8, 0.88, WOOD) + box(6.35, 6.45, -4.85, -4.25, 0, 0.8, C.steel) + box(7.75, 7.85, -4.85, -4.25, 0, 0.8, C.steel);   // 작업대
      s += box(6.6, 6.9, -4.7, -4.45, 0.88, 1.05, C.steel) + box(7.1, 7.6, -4.75, -4.5, 0.88, 0.95, ["#F5C542", "#D9A92A", "#C29522"]);       // 공구
      { const post = (x, y) => box(x, x + 0.05, y, y + 0.05, 0, 1.8, C.steel); s += post(8.3, -4.95) + post(9.15, -4.95);
        [0.3, 0.9, 1.5].forEach(z => { s += box(8.3, 9.2, -4.95, -4.5, z, z + 0.05, ["#5A6B76", "#3A464E", "#323C43"]);
          s += box(8.4, 8.7, -4.85, -4.6, z + 0.05, z + 0.3, ["#7F919C", "#5A6B76", "#4A5B66"]) + box(8.8, 9.1, -4.85, -4.6, z + 0.05, z + 0.22, ["#4CC3FF", "#2E8FC2", "#22729C"]); });
        s += post(8.3, -4.55) + post(9.15, -4.55); }
      s += `</g>`;
    }
    s += `<g id="tw-mech-back"></g>`;      // 정비원이 뒤 통로에 있을 때 이 자리 앞에 그림 (앞쪽 설비에 가려짐)
    // 로봇 적재기 받침대 (팔은 앞쪽에서 그림)
    s += part("로봇 적재기", box(ROBOT[0] - 0.55, ROBOT[0] + 0.55, ROBOT[1] - 0.55, ROBOT[1] + 0.55, 0, 0.08, C.belt) +
      box(ROBOT[0] - 0.45, ROBOT[0] + 0.45, ROBOT[1] - 0.45, ROBOT[1] + 0.45, 0.08, 0.3, C.eqb) +
      hazard(ROBOT[0] - 0.4, ROBOT[0] + 0.4, ROBOT[1] + 0.45, 0.12, 0.2) +
      box(ROBOT[0] - 0.26, ROBOT[0] + 0.26, ROBOT[1] - 0.26, ROBOT[1] + 0.26, 0.3, 0.45, C.eqb) +
      box(ROBOT[0] - 0.2, ROBOT[0] + 0.2, ROBOT[1] - 0.2, ROBOT[1] + 0.2, 0.45, SHOULDER_Z - 0.08, C.eqw) +
      tower(ROBOT[0] + 0.38, ROBOT[1] - 0.38, 0.3, "로봇 적재기"));
    s += shipping();
    // 로봇 옆 팔레트: 양품이 한 층 4개씩 2층(8개)까지 쌓임 → setStack()이 채움
    { const W2 = ["#B08A5C", "#8C6B45", "#77593A"];
      [-1.2, -0.55, 0.05].forEach(y => { s += box(11.2, 12.4, y, y + 0.15, 0, 0.12, W2); });          // 받침목
      [11.2, 11.55, 11.9, 12.25].forEach(x => { s += box(x, x + 0.15, -1.2, 0.2, 0.12, 0.25, W2); });  // 윗판
      s += `<g id="tw-pallet"></g>`; }
    const VP = C.eqw;                                                   // 비전 검사기 지지대 (노랑)
    s += part("비전 검사기", box(6.55, 6.7, -0.3, -0.1, 0, 2.4, VP) + box(7.3, 7.45, -0.3, -0.1, 0, 2.4, VP) +
      box(6.5, 7.5, -0.3, -0.1, 2.4, 2.55, C.eqb) + box(6.95, 7.05, -0.1, 0.95, 2.4, 2.5, VP) +
      box(7.48, 7.75, -0.28, -0.12, 1.2, 1.55, ["#0E1317", "#1B242A", "#151C21"]) +                    // 판정 모니터
      tower(6.62, -0.2, 2.55, "비전 검사기"));
    s += part("프레스 #1", box(2.9, 4.7, 0.3, 0.9, 0, 0.12, C.rub) + box(3, 3.3, 0.4, 0.8, 0, 2.6, C.eqb) + box(4.3, 4.6, 0.4, 0.8, 0, 2.6, C.eqb));

    // ---- 컨베이어와 제품 ----
    const b0 = P(0.2, 1.5, 0.46), b1 = P(11.8, 1.5, 0.46);
    let prods = "";
    for (let i = 0; i < N_PROD; i++) prods += product(i);
    for (let i = 0; i < N_PROD; i++) prods += product(i, true);   // 실제 제품 사이사이에 끼는 가정 제품 (가정 시뮬레이션)
    let legs = "";
    [0.4, 2.4, 5.4, 8.4, 11.4].forEach(x => { legs += box(x, x + 0.1, 1.02, 1.12, 0, 0.3, C.eqb) + box(x, x + 0.1, 1.88, 1.98, 0, 0.3, C.eqb); });
    let rollers = ""; for (let x = 0.3; x < 12; x += 0.6) { const c = P(x, 2.05, 0.39); rollers += `<ellipse cx="${c[0]}" cy="${c[1]}" rx="2.6" ry="3.2" fill="#9AAAB4" opacity=".8"/>`; }
    s += part("컨베이어", legs + box(-0.45, 0, 1.9, 2.3, 0.05, 0.45, C.eqb) +       // 구동 모터
      box(0, 12, 0.95, 1.02, 0.28, 0.52, C.eqb) + box(0, 12, 1, 2, 0.28, 0.45, C.rub) +
      `<line class="anim tw-belt" x1="${b0[0]}" y1="${b0[1]}" x2="${b1[0]}" y2="${b1[1]}" stroke="#4A5B66" stroke-width="2" stroke-dasharray="12 10"/>` +
      prods + box(0, 12, 1.98, 2.05, 0.28, 0.5, C.eqb) + rollers + box(0, 12, 1.98, 2.02, 0.5, 0.54, ["#C3CDD3", "#9AAAB4", "#83939D"]));

    // ② 불량 분기 컨베이어 + 불량품 회수함 (컨베이어 앞쪽)
    //   본 컨베이어와 같은 모양의 작은 컨베이어가 앞쪽으로 뻗어 나와, 끝이 회수함 한가운데 위에서 끝남
    //   그리는 순서: 회수함 뒷벽·왼쪽벽·바닥·불량품 → 분기 컨베이어 → 떨어지는 불량품 → 앞벽·오른쪽벽
    { const [bx0, bx1, by0, by1] = BIN, BH = 0.45, WT = 0.08, cy = (by0 + by1) / 2;
      const RED = ["#D9534F", "#B03A36", "#93302C"], IN = ["#5A1E1C", "#4A1918", "#3E1513"];
      let back = `<polygon points="${pts([P(bx0, by0, 0.02), P(bx1, by0, 0.02), P(bx1, by1, 0.02), P(bx0, by1, 0.02)])}" fill="${IN[2]}"/>` +
        box(bx0, bx1, by0, by0 + WT, 0, BH, [RED[0], IN[1], RED[2]]) +             // 뒷벽 (앞쪽이 안쪽 면)
        box(bx0, bx0 + WT, by0, by1, 0, BH, [RED[0], RED[1], IN[0]]) +             // 왼쪽벽 (옆쪽이 안쪽 면)
        [[0.35, 0.5, "crushed"], [0.8, 0.45, "marked"], [1.3, 0.55, "crushed"], [1.75, 0.5, "crushed"], [0.55, 1.05, "marked"], [1.05, 1.0, "crushed"],
         [1.55, 1.1, "marked"], [0.4, 1.55, "crushed"], [0.95, 1.6, "crushed"], [1.5, 1.6, "marked"], [1.85, 1.45, "crushed"]]
          .sort((a, b) => (a[0] + a[1]) - (b[0] + b[1])).map(([dx, dy, k], i) => box(bx0 + dx - 0.2, bx0 + dx + 0.2, by0 + dy - 0.2, by0 + dy + 0.2, 0.02 + (i % 3 === 2 ? 0.3 : 0), 0.34 + (i % 3 === 2 ? 0.3 : 0), C.bad)).join("");  // 쌓인 불량 상자
      s += `<g class="reject eq" data-eq="불량함">${back}</g>`;
      // 분기 컨베이어 (본 컨베이어와 같은 높이·색, 움직이는 벨트 줄무늬, 다리 2개)
      const y0 = 2.0, y1 = by0 + (by1 - by0) / 3, d0 = P(RAIL_X, y0 + 0.08, 0.46), d1 = P(RAIL_X, y1 - 0.05, 0.46);
      s += `<g class="reject eq" data-eq="불량함">` +
        box(RAIL_X - 0.27, RAIL_X - 0.2, 2.45, 2.52, 0, 0.3, C.steel) + box(RAIL_X + 0.2, RAIL_X + 0.27, 2.45, 2.52, 0, 0.3, C.steel) +
        box(RAIL_X - 0.3, RAIL_X + 0.3, y0, y1, 0.3, 0.45, C.belt) +
        `<line class="anim tw-belt" x1="${d0[0]}" y1="${d0[1]}" x2="${d1[0]}" y2="${d1[1]}" stroke="#4A5B66" stroke-width="2" stroke-dasharray="12 10"/></g>`;
      s += `<g id="tw-fx"></g>`;     // 떨어지는 불량품 (분기 컨베이어 위 → 회수함 속, 앞벽 뒤로)
      // 앞벽 · 오른쪽벽 + 앞면 표시 (노랑·검정 경고 띠, NG 표시판) + 바퀴
      const W = 240, H = 60, o = P(bx0, by1, BH);
      const m = `matrix(${(0.866 * U * (bx1 - bx0) / W).toFixed(4)} ${(0.5 * U * (bx1 - bx0) / W).toFixed(4)} 0 ${(U * BH / H).toFixed(4)} ${o[0]} ${o[1]})`;
      let stripes = ""; for (let i = -2; i < 26; i++) stripes += `<polygon points="${i * 12},0 ${i * 12 + 6},0 ${i * 12 + 6 - 14},14 ${i * 12 - 14},14" fill="#1A1A1A"/>`;
      const deco = `<g transform="${m}"><clipPath id="bin-band"><rect width="${W}" height="14"/></clipPath>` +
        `<rect width="${W}" height="14" fill="#F5C542"/><g clip-path="url(#bin-band)">${stripes}</g>` +
        `<rect x="${W / 2 - 46}" y="22" width="92" height="32" rx="5" fill="#F4F6F7"/>` +
        `<text x="${W / 2}" y="45" text-anchor="middle" font-size="19" font-weight="800" fill="#C0392B" font-family="IBM Plex Sans KR, sans-serif">NG 불량</text></g>`;
      const wheels = [[bx0 + 0.12, by1 - 0.05], [bx1 - 0.12, by1 - 0.05], [bx1 - 0.05, by0 + 0.15]].map(([x, y]) => {
        const c = P(x, y, 0); return `<circle cx="${c[0]}" cy="${c[1] + 2}" r="4.5" fill="#1E282E" stroke="#4A5B66" stroke-width="1.5"/>`; }).join("");
      s += `<g class="reject eq" data-eq="불량함">${wheels}` +
        box(bx1 - WT, bx1, by0, by1, 0, BH, RED) + box(bx0, bx1, by1 - WT, by1, 0, BH, RED) + deco + `</g>`; }
    const bl = P(BIN[0], BIN[3], 0);     // 불량함 왼쪽 아래에 이름표
    s += `<g id="tw-bin" class="binlabel eq" data-eq="불량함" transform="translate(${bl[0] - 140} ${bl[1] + 6})">` +
         `<rect width="128" height="26" rx="6"/><text x="64" y="18" text-anchor="middle">불량함 0개</text></g>`;

    // ---- 앞쪽 (컨베이어 위로 보이는 것들) ----
    s += part("프레스 #1",
      `<g id="tw-ram">${box(3.7, 3.9, 1.4, 1.6, 1.35, 2.6, ["#7F8A91", "#5E686F", "#4E575D"])}${box(3.35, 4.25, 0.85, 2.15, 0.92, 1.35, C.eqw)}</g>` +
      box(2.9, 4.7, 2.1, 2.7, 0, 0.12, C.rub) + hazard(2.9, 4.7, 2.7, 0.0, 0.12) +
      box(3, 3.3, 2.2, 2.6, 0, 2.6, C.eqb) + box(4.3, 4.6, 2.2, 2.6, 0, 2.6, C.eqb) +
      box(3.3, 3.36, 2.5, 2.58, 0.5, 2.2, ["#F0605D", "#B8413F", "#97302F"]) + box(4.24, 4.3, 2.5, 2.58, 0.5, 2.2, ["#F0605D", "#B8413F", "#97302F"]) +   // 광커튼 기둥
      `<g class="lcurtain">${[0.7, 1.0, 1.3, 1.6, 1.9].map(z => { const a = P(3.36, 2.54, z), b = P(4.24, 2.54, z); return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#F0605D" stroke-width="1.2" opacity=".55"/>`; }).join("")}</g>` +
      box(3, 4.6, 0.4, 2.6, 2.6, 3.0, C.eqb) + box(3.0, 4.6, 2.58, 2.6, 2.7, 2.9, ["#F5C542", "#F5C542", "#F5C542"]) + box(3.55, 4.05, 1.25, 1.75, 3.0, 3.45, C.eqw) + box(3.65, 3.95, 1.35, 1.65, 3.45, 3.55, ["#C3CDD3", "#9AAAB4", "#83939D"]) +   // 유압 실린더
      box(4.6, 4.75, 2.3, 2.6, 1.0, 1.6, ["#2B363E", "#222C33", "#1B242A"]) +                                                                         // 조작 패널
      (() => { const c = P(4.75, 2.45, 1.42); return `<circle cx="${c[0]}" cy="${c[1]}" r="4" fill="#F0605D" stroke="#F5C542" stroke-width="1.5"/>`; })() +
      tower(4.45, 0.55, 3.0, "프레스 #1"));
    // 작업자 대시보드 (프레스 왼쪽 앞 키오스크). 화면 내용은 drawHmi()가 그림, 누르면 오른쪽에 크게 열림
    s += `<g class="eq hmi" data-eq="${HMI_NAME}">` +
      box(HMI[0] - 0.25, HMI[0] + 0.25, HMI[1] - 0.35, HMI[1] + 0.35, 0, 0.08, C.belt) +
      box(HMI[0] - 0.08, HMI[0] + 0.08, HMI[1] - 0.06, HMI[1] + 0.06, 0.08, 1.15, C.steel) +
      box(HMI[0] - 0.04, HMI[0] + 0.06, HMI[1] - 0.55, HMI[1] + 0.55, 1.1, 2.0, ["#3A4A54", "#222C33", "#1B242A"]) +
      `<g id="hmi-screen" transform="${HMI_M}" font-family="IBM Plex Sans KR, sans-serif"></g></g>`;
    // ① 안전 게이트: 기둥 두 개 + 위 빔 + 카메라 + 보호구 확인 화면 + 지나가는 작업자
    s += gate();
    // 프레스 앞 작업자: 평소엔 위험구역 밖(wk-out), 손이 감지되면 구역 안에서 손을 뻗은 모습(wk-in)
    s += `<g id="tw-worker"><g id="wk-out">${person(3.8, 3.95, {face: "-y"})}</g><g id="wk-in" style="display:none">${person(3.8, 3.15, {face: "-y"}) + reach(3.8, 3.15)}</g></g>`;
    // 검사 빛: 네모난 검사기 머리 아래 네 꼭짓점에서 내려와 벨트 위에 직사각형으로 비추는 빛 기둥
    //   위(검사기 바닥, z 1.9) 네모 → 아래(벨트 윗면, z 0.46) 조금 더 넓은 네모. 뒷면·옆면은 옅게, 앞면은 진하게
    const T = [[6.55, 0.9], [7.45, 0.9], [7.45, 1.9], [6.55, 1.9]].map(([x, y]) => P(x, y, 1.9));
    const B = [[6.45, 1.0], [7.55, 1.0], [7.55, 2.0], [6.45, 2.0]].map(([x, y]) => P(x, y, 0.46));
    const face = (i, j, op) => `<polygon points="${pts([T[i], T[j], B[j], B[i]])}" fill-opacity="${op}"/>`;
    s += part("비전 검사기",
      `<g id="tw-beam" class="anim tw-scan" fill="#4CC3FF">` +
        face(0, 1, 0.35) + face(3, 0, 0.35) +                                 // 뒷면 · 왼쪽 면 (옅게)
        `<polygon points="${pts(B)}" fill-opacity="1"/>` +                      // 벨트 위 직사각형 빛
        face(2, 3, 0.6) + face(1, 2, 0.6) +                                   // 앞면 · 오른쪽 면
      `</g>` + box(6.55, 7.45, 0.9, 1.9, 1.9, 2.3, C.eqw) + box(6.55, 7.45, 0.9, 1.9, 2.3, 2.34, C.eqb) +
      `<polygon points="${pts([P(6.62, 1.9, 1.95), P(7.38, 1.9, 1.95), P(7.38, 1.9, 2.0), P(6.62, 1.9, 2.0)])}" fill="#4CC3FF" opacity=".9"/>` +   // 앞면 LED 조명 줄
      (() => { const c = P(7.0, 1.9, 2.16); return `<circle cx="${c[0]}" cy="${c[1]}" r="5" fill="#0E1317" stroke="#4CC3FF" stroke-width="2"/><circle cx="${c[0]}" cy="${c[1]}" r="2" fill="#4CC3FF"/>`; })());
    // 로봇 팔: 위치는 lineLoop()가 매 순간 계산해서 옮김 (위팔 · 아래팔 · 집게 · 들고 있는 제품)
    s += part("로봇 적재기", `<g id="tw-robot">` +
      `<line data-arm="1" id="rb-a1" stroke="${C.eqw[0]}" stroke-width="13" stroke-linecap="round"/>` +
      `<line data-arm="1" id="rb-a2" stroke="${C.eqw[0]}" stroke-width="10" stroke-linecap="round"/>` +
      `<g id="rb-cargo" style="display:none">${box(-0.3, 0.3, -0.3, 0.3, -0.5, 0, C.box)}</g>` +
      `<line id="rb-g" stroke="#566873" stroke-width="6" stroke-linecap="round"/>` +
      `<circle id="rb-j0" r="9" fill="${C.eqb[1]}"/><circle id="rb-j1" r="7" fill="${C.eqb[1]}"/><circle id="rb-j2" r="5" fill="#E7EDF0"/></g>`);

    s += trees;                                                     // 나무 (벽 앞)
    s += `<g id="tw-mech" class="eq place mech" data-eq="${MECH_NAME}">${person(MECH_HOME[0], MECH_HOME[1], {face: "-y"})}</g>`;   // 정비원
    s += `<g id="tw-mech-front"></g>`;     // 정비원이 앞쪽에 있을 때 이 자리 앞에 그림
    // 품질 담당자: 불량함 옆에서 불량 캔 확인
    s += person(11.15, 3.9, {face: "-x"});
    // ① 게이트 · ⑥ 출하장 이름표 (누르면 오른쪽에 정보)
    { const g = P((GATE[0] + GATE[1]) / 2, GATE[3] + 0.5, 0), k = P(17.0, 0.8, 0);
      s += `<g class="chip t-ok place-chip" data-eq="${GATE_NAME}" transform="translate(${g[0] + 30} ${g[1] + 40})"><rect x="-80" y="-11" width="160" height="22" rx="6"/>` +
           `<text x="0" y="4" text-anchor="middle" style="font-size:11px">① 안전 게이트 · 보호구 검사</text></g>`;
      s += `<g class="chip t-data place-chip" data-eq="${SHIP_NAME}" transform="translate(${k[0]} ${k[1] + 30})"><rect x="-74" y="-11" width="148" height="22" rx="6"/>` +
           `<text x="0" y="4" text-anchor="middle" style="font-size:11px">⑥ 출하장 · 지게차 → 트럭</text></g>`; }
    // ⑥ LOT 안내판 (트럭 위): 지금 LOT · 실린 팔레트 / 10 · 예상 출발 (TW.lot() · 로봇 적재가 채움)
    { const b = P(14.6 + SHIP_DX, -3.4, 4.3);
      s += `<g id="tw-lot" class="lotboard place-chip" data-eq="${SHIP_NAME}" transform="translate(${b[0]} ${b[1]})" style="display:none">` +
        `<rect class="lb-bg" x="-125" y="-40" width="250" height="80" rx="9"/>` +
        `<text class="lb-t1" x="-109" y="-16">LOT</text><text class="lb-t2" x="-109" y="7">-</text><text class="lb-t3" x="109" y="7" text-anchor="end"></text>` +
        `<rect class="lb-bar0" x="-109" y="18" width="218" height="8" rx="4"/><rect class="lb-bar" x="-109" y="18" width="0" height="8" rx="4"/></g>`; }
    // 작업자 대시보드 이름표
    { const k = P(HMI[0] - 0.25, HMI[1] + 0.35, 0);     // 불량함 이름표처럼 받침대 왼쪽 아래
      s += `<g class="chip t-data hmi-chip" data-eq="${HMI_NAME}" transform="translate(${k[0] - 80} ${k[1] + 20})"><rect x="-66" y="-15" width="132" height="30" rx="7"/>` +
           `<text x="0" y="5" text-anchor="middle">작업자 대시보드</text></g>`; }

    // ---- 표시등과 이름표 (맨 위) ----
    Object.keys(EQ).forEach(n => { s += chip(n); });
    Object.keys(EQ).forEach(n => { s += lamp(n); });

    // ② 위험구역 안내 글자, 불량 꼬리표
    const zl = P(2.4, 3.7);
    s += `<g id="tw-zlabel" class="zlabel" transform="translate(${zl[0] - 70} ${zl[1] + 78})"><rect width="230" height="30" rx="7"/>` +
         `<text x="14" y="20">위험구역</text></g>`;
    const tg = P(RAIL_X, 1.5, 1.3);
    s += `<g id="tw-dtag" class="dtag" transform="translate(${tg[0] + 18} ${tg[1] - 40})"><rect width="176" height="46" rx="8"/>` +
         `<text x="12" y="19" class="t1">▲ 불량 검출</text><text x="12" y="36" class="t2">→ 배출 레일</text></g>`;

    const style = "";   // 제품·AMR·프레스·로봇은 lineLoop()가 움직임
    s += `<g id="tw-mech-tag" class="mech-tag" style="display:none"><rect x="-80" y="-14" width="160" height="26" rx="8"/><text x="0" y="5" text-anchor="middle"></text></g>`;   // 정비원 머리 위 상태표
    return `<svg viewBox="-280 -150 1520 970" preserveAspectRatio="xMidYMid meet" role="img" aria-label="입체 공정 라인">${style}${s}</svg>`;
  }

  // ---------------------------------------------------------------- 실시간 상태
  function apply(equipment, modules, selected) {
    equipment.forEach(e => {
      const meta = EQ[e.name]; if (!meta) return;
      const t = tone(e.status), stop = e.status !== "가동";
      document.querySelectorAll(`[data-eq="${e.name}"].eq`).forEach(g => {
        g.classList.toggle("stop", stop);
        g.classList.toggle("glow-bad", t === "bad");
        g.classList.toggle("glow-warn", t === "warn");
        g.classList.toggle("sel", selected === e.name);
      });
      document.querySelectorAll(`.stk[data-stk="${e.name}"]`).forEach(g => g.setAttribute("class", `stk t-${t}`));
      const lampEl = document.getElementById("lamp-" + meta.key);
      lampEl.setAttribute("class", `lampx t-${t}${stop ? " blink" : ""}`);
      setChip(e.name, stop ? `${shape(e.status)} ${e.name} · ${e.status}` : e.name, t, selected === e.name);
    });
    const beam = document.getElementById("tw-beam");
    if (beam) beam.setAttribute("fill", ((modules.quality || {}).status === "불량") ? "#F0605D" : "#4CC3FF");
  }

  function setChip(name, label, t, on = false) {
    const meta = EQ[name]; if (!meta) return;
    const c = document.getElementById("chip-" + meta.key);
    c.setAttribute("class", `chip t-${t}${on ? " on" : ""}`);
    label = (meta.num ? meta.num + " " : "") + label;   // 공정 순서 번호 (① 게이트 → ⑥ 출하)
    c.querySelector("text").textContent = label;
    const w = 26 + label.length * 10.2;                 // 작은 이름표 (글자 11px) · 왼쪽에 상태 점
    const r = c.querySelector("rect"); r.setAttribute("x", -w / 2); r.setAttribute("width", w);
    const [ax] = P(...LBL[name]), lx = (ax - w / 2 + 10).toFixed(1);
    document.querySelectorAll(`#lamp-${meta.key} circle`).forEach(q => q.setAttribute("cx", lx));
  }

  // ---------------------------------------------------------------- ② 위험구역
  // safety: /api/state의 modules.safety, pressStatus: 프레스 상태 문자열
  //   손이 지금 보임 → 빨갛게 깜빡 / 안전 정지 중이지만 구역은 비었음 → 빨갛게 고정 / 평소 → 점선 테두리만
  function zone(safety, pressStatus) {
    const z = document.getElementById("tw-zone"), lb = document.getElementById("tw-zlabel");
    if (!z) return;
    safety = safety || {};
    const stopped = pressStatus === "안전 정지";
    const hit = stopped && safety.zone_clear === false;
    z.setAttribute("class", "zone" + (hit ? " hit" : stopped ? " hold" : ""));
    let text = "";
    if (hit) text = `⛔ 위험구역 · ${safety.reason || "위험 대상"} 감지`;
    else if (stopped && safety.auto_release_in != null) text = `위험구역 비움 · ${safety.auto_release_in.toFixed(1)}초 뒤 자동 재가동`;
    else if (stopped) text = "위험구역 · 재가동 승인 대기";
    lb.setAttribute("class", "zlabel" + (text ? " show" + (hit ? " hit" : "") : ""));
    lb.querySelector("text").textContent = text;
    lb.querySelector("rect").setAttribute("width", Math.max(150, text.length * 12.5 + 28));
    // 작업자: 손이 감지되는 동안만 구역 안에서 손을 뻗은 모습
    const wi = document.getElementById("wk-in"), wo = document.getElementById("wk-out");
    if (wi) { wi.style.display = hit ? "" : "none"; wo.style.display = hit ? "none" : ""; }
    // 작업자 대시보드 화면
    hmi.mode = hit ? "hit" : stopped ? "hold" : "ok";
    hmi.left = stopped && !hit && safety.auto_release_in != null ? safety.auto_release_in : null;
    drawHmi();
  }

  // ---------------------------------------------------------------- ② 불량품 움직임
  // 비전 검사기 아래 → 벨트를 따라 레일 입구 → 레일을 타고 앞으로 → 불량함 속으로
  let binCount = 0, tagTimer = null;
  function setBin(n) {
    binCount = n;
    const t = document.querySelector("#tw-bin text"); if (t) t.textContent = `불량함 ${n}개`;
  }
  // 판정 순간 비전 검사기 바로 밑(또는 막 지난) 실제 제품을 찾아 빨갛게 표시 → 그 제품이 분기점(RAIL_X)에 오면
  // 본 벨트에서 사라지고 분기 컨베이어를 타고 회수함으로 들어감 (lineLoop가 위치를 보고 divert 호출)
  const P_VISION = (7.0 - 0.6) / TRAVEL, P_RAIL = (RAIL_X - 0.6) / TRAVEL;
  const BRANCH_DY = BIN[2] + (BIN[3] - BIN[2]) / 3 - 0.3 - 1.5;   // 분기 컨베이어가 불량함 1/3 지점까지    // 제품 앞끝이 분기 컨베이어 끝(회수함 한가운데)에 닿을 때까지
  const paintProd = (g, c) => g.querySelectorAll("polygon[data-f]").forEach(q => q.setAttribute("fill", c[+q.dataset.f]));
  function spawnDefect(type = "") {
    if (flowOn()) return;                                      // 새 흐름: 불량은 장부의 그 상자가 직접 빠짐
    // 아직 분기점을 지나지 않은 제품 중 비전 검사기에 가장 가까운 것 = 판정받은 제품
    let best = null, bd = 9;
    document.querySelectorAll(".tw-prod:not(.ghost)").forEach(g => {
      if (g.dataset.defect || g.style.visibility === "hidden") return;
      const p = +g.dataset.p || 0, d = Math.abs(p - P_VISION);
      if (p < P_RAIL - 0.02 && d < bd) { bd = d; best = g; }
    });
    if (best) {
      const p = +best.dataset.p || 0;
      best.dataset.defect = "1";
      // 이 제품이 원래 벨트 끝(로봇이 집는 곳)에 닿았을 주기 → 그 주기에는 로봇이 집으러 가지 않음
      skipPick.add(Math.round((lineT + (1 - p) * TRAVEL_SEC) / CYCLE));
      if (p >= P_VISION - 0.02) paintProd(best, C.bad);      // 검사기 밑이거나 막 지남 → 바로 빨갛게
      else best.dataset.wait = "1";                           // 검사기 앞 → 검사기 밑에 오는 순간 빨갛게
    } else divert(7.35);                                       // (드묾) 벨트에 맞는 제품이 없으면 검사기 밑에서 바로 출발
    flashTag(type);
  }
  function flashTag(type) {
    const tag = document.getElementById("tw-dtag"); if (!tag) return;
    tag.querySelector(".t1").textContent = "▲ 불량 검출" + (type ? ` · ${type}` : "");
    tag.classList.add("show");
    clearTimeout(tagTimer); tagTimer = setTimeout(() => tag.classList.remove("show"), 3500);
  }
  // 빨간 제품이 (x0 위치에서) 본 벨트 → 분기 컨베이어 → 회수함 속으로
  function divert(x0) {
    const fx = document.getElementById("tw-fx"); if (!fx) return;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.innerHTML = box(x0 - 0.3, x0 + 0.3, 1.2, 1.8, 0.45, 0.95, C.bad);
    fx.appendChild(g);
    const k = (a, off, op = 1) => ({transform: `translate(${a[0].toFixed(1)}px, ${a[1].toFixed(1)}px)`, offset: off, opacity: op});
    const dx = RAIL_X - x0, lead = dx > 0.01 ? 0.35 : 0;     // 분기점까지 남은 거리
    const anim = g.animate([
      k(D(0, 0, 0), 0), k(D(dx, 0, 0), lead),
      k(D(dx, BRANCH_DY, 0), lead + (1 - lead) * 0.65),
      k(D(dx, BRANCH_DY + 0.15, -0.2), lead + (1 - lead) * 0.82), k(D(dx, BRANCH_DY + 0.2, -0.5), 1, 0),
    ], {duration: lead ? 3200 : 2200, easing: "linear"});
    anim.onfinish = () => {
      g.remove(); if (!flowOn()) setBin(binCount + 1);       // 새 흐름에서는 불량함 숫자를 장부가 정함
      const b = document.getElementById("tw-bin");
      b.classList.remove("flash"); void b.getBBox(); b.classList.add("flash");
    };
  }

  // ---------------------------------------------------------------- ① 레이어 색칠
  // 값(0~1) → 색: 낮음(어두운 청록) → 초록 → 노랑 → 빨강
  const STOPS = [[0, [0x2C, 0x4A, 0x58]], [0.45, [0x3C, 0xC6, 0xA8]], [0.7, [0xF5, 0xB5, 0x44]], [1, [0xF0, 0x60, 0x5D]]];
  function heatRGB(v) {
    v = Math.max(0, Math.min(1, v));
    for (let i = 1; i < STOPS.length; i++) {
      const [b, cb] = STOPS[i], [a, ca] = STOPS[i - 1];
      if (v <= b) { const t = (v - a) / (b - a); return ca.map((c, j) => Math.round(c + (cb[j] - c) * t)); }
    }
    return STOPS[STOPS.length - 1][1];
  }
  const hex = rgb => "#" + rgb.map(c => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0")).join("");
  const FACE = [1, 0.72, 0.58];       // 윗면·앞면·옆면 밝기
  const heat = v => hex(heatRGB(v));
  const legendCSS = () => `linear-gradient(90deg, ${[0, .2, .45, .6, .7, .85, 1].map(heat).join(", ")})`;

  // 설비의 색을 칠할 면들 (컨베이어 위 제품은 제외)
  const faces = name => [...document.querySelectorAll(`[data-eq="${name}"].eq polygon[data-f], [data-eq="${name}"].eq [data-arm]`)]
    .filter(p => !p.closest(".tw-prod") && !p.closest("#rb-cargo") && !p.closest("#tw-amr-cargo"));

  // vals: {설비이름: {heat: 0~1 또는 null(데이터 없음), text: 이름표 글자, tone: ok/warn/bad/idle}}
  function paint(vals) {
    Object.keys(EQ).forEach(name => {
      const v = vals[name] || {heat: null};
      const rgb = v.heat == null ? [0x3A, 0x44, 0x4A] : heatRGB(v.heat);
      faces(name).forEach(p => {
        const attr = p.dataset.arm ? "stroke" : "fill";
        if (!p.dataset.o) p.dataset.o = p.getAttribute(attr);
        const f = p.dataset.arm ? 0.85 : FACE[+p.dataset.f];
        p.setAttribute(attr, hex(rgb.map(c => c * f)));
      });
      if (v.text) setChip(name, v.text, v.tone || "idle");
    });
  }
  function unpaint() {
    Object.keys(EQ).forEach(name => faces(name).forEach(p => {
      if (p.dataset.o) { p.setAttribute(p.dataset.arm ? "stroke" : "fill", p.dataset.o); delete p.dataset.o; }
    }));
  }

  // ---------------------------------------------------------------- ④ 가정 시뮬레이션
  const FOOT = {   // 설비 바닥 테두리 (병목 강조용, 칸 좌표 x0 x1 y0 y1)
    "자재 투입기": [-3.95, 0.1, 0.75, 2.25], "프레스 #1": [2.7, 4.9, 0.2, 2.8], "컨베이어": [-0.2, 12.2, 0.8, 2.2],
    "비전 검사기": [6.25, 7.75, -0.5, 2.1], "로봇 적재기": [9.6, 12.5, -1.3, 0.35],
  };
  function focus(name) {
    const f = document.getElementById("tw-focus");
    document.querySelectorAll(".eq.focus").forEach(g => g.classList.remove("focus"));
    if (!name || !FOOT[name]) { f.setAttribute("points", ""); return; }
    const [x0, x1, y0, y1] = FOOT[name];
    f.setAttribute("points", pts([P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)]));
    document.querySelectorAll(`[data-eq="${name}"].eq`).forEach(g => g.classList.add("focus"));
  }
  function ghosts(k) {
    document.querySelectorAll(".tw-prod.ghost").forEach(g => g.classList.toggle("show", +g.dataset.g < k));
  }

  // ---------------------------------------------------------------- 로봇 적재기 (입체 로봇 팔)
  // 컨베이어 끝(PICK)에서 제품을 집어 팔레트(PLACE)에 쌓는 동작을 반복한다.
  // 집게 끝이 갈 곳을 정하면 팔 각도를 거꾸로 계산(역기구학: 두 마디 팔)해서 그린다.
  // 로봇 적재기가 멈추면(.eq.stop) 팔도 그 자리에서 멈춘다.
  const ease = t => t * t * (3 - 2 * t);
  const lerp = (a, b, t) => a + (b - a) * t;
  const polar = p => [Math.atan2(p[1] - ROBOT[1], p[0] - ROBOT[0]), Math.hypot(p[0] - ROBOT[0], p[1] - ROBOT[1]), p[2]];
  const PK = polar(PICK), PL = polar(PLACE), UP = 0.7;
  const up = v => [v[0], v[1], v[2] + UP];
  // [시작, 끝(한 바퀴 비율), 출발, 도착(방향·거리·높이), 제품을 들고 있나]
  const MOVES = [
    [0.00, 0.22, up(PL), up(PK), false],   // 팔레트 위 → 컨베이어 끝 위로 회전
    [0.22, 0.32, up(PK), PK, false],       // 내려가서
    [0.32, 0.38, PK, PK, true],            // 집고
    [0.38, 0.48, PK, up(PK), true],        // 들어 올리고
    [0.48, 0.72, up(PK), up(PL), true],    // 팔레트 위로 회전
    [0.72, 0.82, up(PL), PL, true],        // 내려놓고
    [0.82, 0.88, PL, PL, false],           // 놓고
    [0.88, 1.00, PL, up(PL), false],       // 올라감
  ];
  function armAt(t) {
    const m = MOVES.find(v => t >= v[0] && t < v[1]) || MOVES[MOVES.length - 1];
    const k = ease(Math.min(1, (t - m[0]) / (m[1] - m[0])));
    const yaw = lerp(m[2][0], m[3][0], k), r = lerp(m[2][1], m[3][1], k), z = lerp(m[2][2], m[3][2], k);
    const wz = z + GRIP, h = wz - SHOULDER_Z;                       // 손목은 집게 길이만큼 위
    const d = Math.min(Math.hypot(r, h), L1 + L2 - 0.01);
    const a2 = Math.acos(Math.max(-1, Math.min(1, (d * d - L1 * L1 - L2 * L2) / (2 * L1 * L2))));
    const a1 = Math.atan2(h, r) + Math.atan2(L2 * Math.sin(a2), L1 + L2 * Math.cos(a2));   // 팔꿈치가 위로
    const c = Math.cos(yaw), s = Math.sin(yaw);
    const at = (rr, zz) => P(ROBOT[0] + c * rr, ROBOT[1] + s * rr, zz);
    return {s: P(ROBOT[0], ROBOT[1], SHOULDER_Z), e: at(L1 * Math.cos(a1), SHOULDER_Z + L1 * Math.sin(a1)),
            w: at(r, wz), tip: at(r, z), hold: m[4]};
  }
  // ---------------------------------------------------------------- ★ 라인 시계 (모든 움직임의 박자)
  // 한 주기(CYCLE초) 안의 시각 u 기준으로 맞물린다.
  //   u = 0      : AMR이 입구에서 자재를 내려놓음 → 벨트 처음에 제품이 생김
  //                (동시에 TRAVEL_SEC 전에 출발한 제품이 벨트 끝에 도착 → 로봇이 집음)
  //   u ≈ 3.7초  : 제품이 프레스 밑을 지나는 순간 램이 내려와 찍음
  //   AMR        : 내려놓고 → 선반으로 → 싣고 → 입구로 돌아와 다음 u = 0을 기다림
  // 컨베이어가 멈추면(연동 정지 포함) 시계가 멈춰 AMR·프레스·로봇·제품이 모두 그 자리에 선다.
  const wrap = (v, m) => ((v % m) + m) % m;
  const PRESS_T = (PRESS_X - 0.6) / TRAVEL * TRAVEL_SEC;   // 제품이 나온 뒤 프레스 밑에 오기까지 (초)
  // AMR 한 바퀴(0~1) = 상자 4개가 벨트에 올라가는 동안 (u = 0 · 0.25 · 0.5 · 0.75에 1개씩 투입 대기 칸 → 벨트)
  //   입구 → 창고로 빈 채 이동(~0.35) → 창고에서 4개 싣기(~0.45) → 입구로(~0.8) → 칸이 빈 뒤 4개 내림(~0.9) → 대기
  //   투입 대기 칸: 4 → (투입) 3 → 2 → 1 → 0 → AMR이 4개 채움 → 다음 투입
  const AMR_L1 = AMR_K[1] - AMR_W[1], AMR_L2 = AMR_I[0] - AMR_K[0];
  function amrPath(f) {              // 창고(0) → 입구(1) 경로 위 위치 [x, y]
    const d = f * (AMR_L1 + AMR_L2);
    return d <= AMR_L1 ? [AMR_W[0], AMR_W[1] + d] : [AMR_K[0] + (d - AMR_L1), AMR_K[1]];
  }
  const AMR_DROP = 0.86;              // 이 순간 AMR 짐 4개가 투입 대기 칸으로
  function amrPose(u) {              // → [x, y, 싣고 있나]
    let f, loaded;
    if (u < 0.35) { f = 1 - ease(u / 0.35); loaded = false; }
    else if (u < 0.45) { f = 0; loaded = u > 0.4; }
    else if (u < 0.8) { f = ease((u - 0.45) / 0.35); loaded = true; }
    else { f = 1; loaded = u < AMR_DROP; }
    return [...amrPath(f), loaded];
  }
  const rackCount = u => u >= AMR_DROP ? 4 : 3 - Math.floor(u * 4);     // 투입 대기 칸에 남은 자재
  let amrNow = {u: 0.95, buf: 4};
  const amrRef = {id: 0, t0: null};
  function drawAmr(u, buf) {
    amrNow = {u, buf};
    const [x, y, loaded] = amrPose(u), d = D(x - AMR_W[0], y - AMR_W[1]);
    const g = document.getElementById("tw-amr"); if (!g) return;
    g.setAttribute("transform", `translate(${d[0].toFixed(1)} ${d[1].toFixed(1)})`);
    document.getElementById("tw-amr-cargo").style.visibility = loaded ? "" : "hidden";
    for (let i = 0; i < 4; i++) { const b = document.getElementById("tw-buf" + i); if (b) b.style.visibility = i < buf ? "" : "hidden"; }
  }
  let lineT = 0, lineLast = null, lastHold = false, lastArmN = null;

  // ================================================================ 새 흐름 (FLOW_V2 · static/flow.js)
  //   상자 = 검사 기록 1줄 (번호 표시) · 검사기 앞은 회색 예상 상자 · 로봇 · 지게차 · 트럭 · 숫자는 서버 장부 그대로
  //   리플레이 중에는 예전 방식(자체 시계)으로 그림
  function flowOn() {
    try { return typeof FLOW !== "undefined" && window.FLOW_ON && FLOW.ready() && !(typeof mode !== "undefined" && mode === "replay"); }
    catch (e) { return false; }
  }
  let pool = null, flowKey = "", flowBin = -1;
  const flowDiverted = new Set(), flowFlashed = new Set();
  function ensurePool() {
    if (pool) return pool;
    const base = [...document.querySelectorAll(".tw-prod:not(.ghost)"), ...document.querySelectorAll(".tw-prod-x")];
    if (!base.length) return null;
    const parent = base[0].parentNode;
    while (base.length < 14) { const c = base[0].cloneNode(true); c.classList.remove("tw-prod"); c.classList.add("tw-prod-x"); parent.appendChild(c); base.push(c); }
    const lp = P(0.6, 1.5, 1.45);
    base.forEach(g => {
      if (g.querySelector(".tw-pid")) return;
      const tx = document.createElementNS("http://www.w3.org/2000/svg", "text");
      tx.setAttribute("x", lp[0]); tx.setAttribute("y", lp[1]); tx.setAttribute("class", "tw-pid");
      g.appendChild(tx);
      const ti = document.createElementNS("http://www.w3.org/2000/svg", "title"); g.appendChild(ti);
    });
    if (!document.getElementById("tw-station")) {                // 비전 검사기 위: 검사 카운트다운 · 판정
      const st = document.createElementNS("http://www.w3.org/2000/svg", "text");
      st.id = "tw-station"; st.setAttribute("class", "tw-station");
      // 검사기 몸통에 가리지 않게: 같은 좌표계(제품 그룹의 부모)에서 맨 위 레이어로 · 검사기 머리 위
      const top = parent.getAttribute("transform") ? parent : parent.parentNode;      // 설비 그룹(변환 없음) 밖 = 맨 위
      st.setAttribute("x", (lp[0] + MOVE[0] * P_VISION + 12).toFixed(1)); st.setAttribute("y", (lp[1] + MOVE[1] * P_VISION - 58).toFixed(1));
      top.appendChild(st);
    }
    return (pool = base);
  }
  const PRESS_P = (PRESS_X - 0.6) / TRAVEL;
  function flowFrame() {
    const t = FLOW.tau(); lineT = t;
    const u = wrap(t, CYCLE), nodes = ensurePool(); if (!nodes) return;
    const bx = FLOW.boxes({pv: P_VISION, pdiv: P_RAIL, gap: 0.075});
    bx.sort((a, b) => a.p - b.p);              // 벨트 앞쪽(보는 사람 쪽) 상자를 나중에 그림 → 겹쳐도 앞뒤가 맞음
    let n = 0, dpress = 9, waitN = 0;
    bx.forEach(b => {
      if (b.chute != null) {                                   // 분기점 도착 → 분기 컨베이어 → 불량함 (한 번만)
        if (!flowDiverted.has(b.id)) { flowDiverted.add(b.id); divert(RAIL_X); }
        return;
      }
      const g = nodes[n++]; if (!g) return;
      g.style.visibility = "";
      g.setAttribute("transform", `translate(${(MOVE[0] * b.p).toFixed(1)} ${(MOVE[1] * b.p).toFixed(1)})`);
      const col = b.ng ? "bad" : (b.pred || b.ins) ? "pred" : "box";   // 검사 전 = 골판지색 · 양품 = 주황 · 불량 = 빨강
      if (g.dataset.col !== col) { paintProd(g, C[col]); g.dataset.col = col; }
      const label = b.pred || (b.wait && waitN++ > 0) ? "" : `#${b.id}`;   // 줄 선 상자는 맨 앞만 번호 (개수는 상태 칩에)
      const tx = g.querySelector(".tw-pid");
      if (tx && tx.textContent !== label) {
        tx.textContent = label;
        g.querySelector("title").textContent = b.pred ? "예상 상자 (아직 검사 전)" : `검사 기록 #${b.id} · ${b.ng ? "불량 " + (b.type || "") + " → 불량함" : "정상 → 로봇 적재기"}`;
      }
      tx && tx.setAttribute("class", "tw-pid" + (b.ng ? " ng" : b.wait ? " wait" : b.st ? " st" : ""));
      if (b.ng && !flowFlashed.has(b.id)) { flowFlashed.add(b.id); flashTag(b.type); }
      dpress = Math.min(dpress, Math.abs(b.p - PRESS_P));
    });
    for (let i = n; i < nodes.length; i++) { nodes[i].style.visibility = "hidden"; const x = nodes[i].querySelector(".tw-pid"); if (x) x.textContent = ""; }
    stationLabel(document.getElementById("tw-station"), FLOW.station());

    // 자재 투입기: 투입 대기 칸에서 박자마다 1개씩 벨트로 · AMR은 4개(4박자)마다 한 바퀴 → 칸이 2개 남았을 때 4개 채움
    //   기준 = 장부에 기록된 마지막 상자(번호 · 벨트에 놓인 τ는 바뀌지 않음) → 그 뒤로 박자(CYCLE)마다 1개씩
    //   (예상 상자 시각은 판정이 늦으면 계속 바뀌어서 기준으로 쓰면 AMR이 튐)
    { const C4 = FLOW.C.CYCLE, ps = (FLOW.data() || {}).products || [];
      const last = ps.reduce((a, p) => (!a || p.id > a.id ? p : a), null);
      if (last) { amrRef.id = last.id; amrRef.t0 = last.ws - FLOW.C.MOVE - FLOW.C.D_PRE; }
      const el = t - amrRef.t0, idle = amrRef.t0 == null || el > 6 * C4 || el < -C4;
      let u = 0.95;
      if (!idle) { const k = Math.floor(Math.max(0, el) / C4), m = ((amrRef.id + k) % 4 + 4) % 4; u = (m * C4 + (Math.max(0, el) - k * C4)) / (4 * C4); }
      drawAmr(u, idle ? 4 : rackCount(u)); }
    // 프레스 램: 상자가 밑을 지날 때 내려옴
    const down = Math.max(0, 1 - dpress / 0.035);
    document.getElementById("tw-ram").setAttribute("transform", `translate(0 ${(26 * ease(down)).toFixed(1)})`);

    // 로봇: 장부의 '지금 집는 상자' 동작 진행도 그대로 (없으면 팔레트 위에서 대기)
    const r = FLOW.robot(), a = r ? armAt(r.x) : armAt(0.999);
    const line = (id, p, q) => { const l = document.getElementById(id);
      l.setAttribute("x1", p[0]); l.setAttribute("y1", p[1]); l.setAttribute("x2", q[0]); l.setAttribute("y2", q[1]); };
    const dot = (id, p) => { const c = document.getElementById(id); c.setAttribute("cx", p[0]); c.setAttribute("cy", p[1]); };
    line("rb-a1", a.s, a.e); line("rb-a2", a.e, a.w); line("rb-g", a.w, a.tip);
    dot("rb-j0", a.s); dot("rb-j1", a.e); dot("rb-j2", a.w);
    const cargo = document.getElementById("rb-cargo");
    cargo.style.display = r && a.hold ? "" : "none";
    cargo.setAttribute("transform", `translate(${(a.tip[0] - O[0]).toFixed(1)} ${(a.tip[1] - O[1]).toFixed(1)})`);

    // 지게차 · 팔레트 · 트럭 · 불량함 숫자
    const f = FLOW.fork(), [fk, load] = f ? forkShape(f.u) : [0, false];
    const fd = D(0, FORK_BACK * (1 - fk));
    document.getElementById("tw-fork").setAttribute("transform", `translate(${fd[0].toFixed(1)} ${fd[1].toFixed(1)})`);
    document.getElementById("tw-fork-load").style.visibility = load ? "" : "hidden";
    const c = FLOW.counts();
    FLOW.newDeparts("twin").forEach(id => depart({id, pallets: FLOW.C.TRUCK, good: FLOW.C.TRUCK * FLOW.C.PALLET}));
    ship.size = FLOW.C.PALLET; ship.trucks = FLOW.C.TRUCK; ship.mode = "live"; ship.flow = c;
    ship.shown = c.placed; ship.onTruck = c.onTruck;
    const st = FLOW.status();
    const key = [c.placed, c.onTruck, c.lot, ship.departing, !!ship.msg, st && st.short].join("|");
    if (key !== flowKey) { flowKey = key; drawLot(); }
    if (c.bin !== flowBin) { flowBin = c.bin; if (!document.querySelector("#tw-fx g")) setBin(c.bin); else flowBin = -1; }
  }
  // 검사기 위 글자: "검사 중 3.2/5초" → "불량 · 찌그러짐" / "정상"
  const TYPE_KO = {crushed_can: "찌그러짐", marked_can: "표면 흠집"};
  function stationLabel(el, s) {
    if (!el) return;
    let txt = "", cls = "tw-station";
    if (s) {
      if (s.ng) { txt = `■ 불량 · ${TYPE_KO[s.type] || s.type || ""}`; cls += " ng"; }
      else if (s.ok) { txt = "● 정상"; cls += " ok"; }
      else txt = s.el > s.total + 0.3 ? "🔍 판정 중…" : `🔍 검사 중 ${Math.min(s.el, s.total).toFixed(1)} / ${s.total}초`;
    }
    if (el.textContent !== txt) el.textContent = txt;
    if (el.getAttribute("class") !== cls) el.setAttribute("class", cls);
  }
  // 지게차 왕복 모양 (출발 후 u초 → [트럭 쪽으로 간 비율, 들고 있나]) — 예전 forkAt과 같은 모양
  function forkShape(u) {
    if (u < 1.8) return [ease(u / 1.8), true];
    if (u < 2.4) return [1, u < 2.1];
    if (u < FORK_SEC) return [1 - ease(Math.min(1, (u - 2.4) / 1.8)), false];
    return [0, false];
  }
  const skipPick = new Set();     // 불량으로 빠져서 벨트 끝에 제품이 오지 않는 주기 번호들
  const O = P(0, 0, 0);
  function lineLoop(now) {
    requestAnimationFrame(lineLoop);
    const conv = document.querySelector('[data-eq="컨베이어"].eq');
    if (!conv || !document.getElementById("tw-robot")) { lineLast = now; return; }
    if (flowOn()) { flowFrame(); lineLast = now; return; }
    if (pool) {                                    // 새 흐름 → 예전 방식(리플레이 등)으로 돌아올 때 한 번 정리
      document.querySelectorAll(".tw-prod-x").forEach(g => g.style.visibility = "hidden");
      document.querySelectorAll(".tw-pid").forEach(t => t.textContent = "");
      const st = document.getElementById("tw-station"); if (st) st.textContent = "";
      document.querySelectorAll(".tw-prod:not(.ghost)").forEach(g => { if (g.dataset.col && g.dataset.col !== "box") paintProd(g, C.box); delete g.dataset.col; });
      pool = null; flowKey = "";
    }
    if (lineLast != null && !conv.classList.contains("stop")) lineT += Math.min(0.1, (now - lineLast) / 1000);
    lineLast = now;
    const u = wrap(lineT, CYCLE);

    // 벨트 위 제품 (가정 제품은 반 주기 어긋나게)
    document.querySelectorAll(".tw-prod").forEach(g => {
      const off = (+g.dataset.i) * CYCLE + (g.classList.contains("ghost") ? CYCLE / 2 : 0);
      const p = wrap(lineT - off, TRAVEL_SEC) / TRAVEL_SEC;
      g.setAttribute("transform", `translate(${(MOVE[0] * p).toFixed(1)} ${(MOVE[1] * p).toFixed(1)})`);
      g.dataset.p = p.toFixed(4);
      if (g.dataset.defect) {
        if (g.dataset.wait && p >= P_VISION) { delete g.dataset.wait; paintProd(g, C.bad); }   // 검사기 밑 도착 → 빨갛게
        if (!g.dataset.gone && p >= P_RAIL) { g.dataset.gone = "1"; divert(RAIL_X); }          // 분기점 도착 → 분기 컨베이어로
        if (g.dataset.gone && p < P_VISION - 0.2) {                                           // 다시 처음부터 = 새 제품
          delete g.dataset.defect; delete g.dataset.gone; paintProd(g, C.box); }
      }
      g.style.visibility = p > 0.99 || g.dataset.gone ? "hidden" : "";   // 벨트 끝에 닿으면 로봇이 집어 감 / 불량은 분기됨
    });

    // 자재 투입기 (예전 방식: 자체 시계)
    { const u4 = wrap(lineT, 4 * CYCLE) / (4 * CYCLE); drawAmr(u4, rackCount(u4)); }

    // 프레스 램: 제품이 밑을 지날 때 내려옴 (가장 가까운 순간 기준 ±0.5초)
    const dt = wrap(u - PRESS_T + CYCLE / 2, CYCLE) - CYCLE / 2;
    const down = Math.max(0, 1 - Math.abs(dt) / 0.5);
    document.getElementById("tw-ram").setAttribute("transform", `translate(0 ${(26 * ease(down)).toFixed(1)})`);

    // ⑥ 지게차: 팔레트를 들고 트럭으로 → 내려놓고 → 돌아와 대기
    const [fk, load] = forkAt(lineT);   // 팔레트가 다 찼을 때만 왕복
    const fd = D(0, FORK_BACK * (1 - fk));
    document.getElementById("tw-fork").setAttribute("transform", `translate(${fd[0].toFixed(1)} ${fd[1].toFixed(1)})`);
    document.getElementById("tw-fork-load").style.visibility = load ? "" : "hidden";

    // 로봇 팔: u = 0 에 집도록 위상을 맞춤 (MOVES의 '집기'가 0.32~0.38)
    //   불량이 분기돼 집을 제품이 없는 주기에는 팔레트 위에서 기다림 (빈손으로 집으러 가지 않음)
    const armN = Math.floor(lineT / CYCLE + 0.35);
    skipPick.forEach(n => { if (n < armN - 2) skipPick.delete(n); });
    if (armN !== lastArmN) {                         // 새 동작을 시작할 때: 실제 모드인데 쌓을 양품이 없으면 이번 주기는 대기
      if (lastArmN != null && pending() <= 0) skipPick.add(armN);
      lastArmN = armN;
    }
    const a = skipPick.has(armN) ? armAt(0.999) : armAt(wrap(u / CYCLE + 0.35, 1));
    const line = (id, p, q) => { const l = document.getElementById(id);
      l.setAttribute("x1", p[0]); l.setAttribute("y1", p[1]); l.setAttribute("x2", q[0]); l.setAttribute("y2", q[1]); };
    const dot = (id, p) => { const c = document.getElementById(id); c.setAttribute("cx", p[0]); c.setAttribute("cy", p[1]); };
    line("rb-a1", a.s, a.e); line("rb-a2", a.e, a.w); line("rb-g", a.w, a.tip);
    dot("rb-j0", a.s); dot("rb-j1", a.e); dot("rb-j2", a.w);
    const cargo = document.getElementById("rb-cargo");
    if (lastHold && !a.hold) robotPlaced();            // 집게를 놓는 순간 = 팔레트에 상자 1개 추가
    lastHold = a.hold;
    if (stackN < 0) drawLot();                         // 처음 한 번: 안내판·팔레트 그리기
    cargo.style.display = a.hold ? "" : "none";
    cargo.setAttribute("transform", `translate(${(a.tip[0] - O[0]).toFixed(1)} ${(a.tip[1] - O[1]).toFixed(1)})`);
  }
  requestAnimationFrame(lineLoop);

  return {ship, flowOn, phase: () => amrNow, mechMove, mechAt, MECH_NAME, build, lot: lot_, depart, apply, zone, spawnDefect, setBin, hmiStats, drawHmi, HMI_NAME, gateState, GATE_NAME, SHIP_NAME, paint, unpaint, heat, legendCSS, chip: setChip, focus, ghosts,
          names: Object.keys(EQ), KEY2NAME};
})();
