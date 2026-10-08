// 안전 게이트 화면: 보호구 착용 작업자 그림 — on = {helmet, vest, gloves}
//   확인된 보호구: 제 색 (안전모 노랑 · 조끼 주황+반사띠 · 장갑 파랑)
//   아직 안 보이는 보호구: 그 자리를 회색 점선 윤곽으로만 (사람은 맨머리 · 셔츠 · 맨손)
window.ppeFigure = (on, w = 300) => {
  const ok = k => !!on[k];
  const ghost = 'fill="none" stroke="#6B7A84" stroke-width="2" stroke-dasharray="6 5" opacity=".9"';
  const tag = (k, label, x, y, ax, ay, right, col) => {
    const c = ok(k) ? col : "#93A3AD", bx = right ? x : x - 104;
    return `<path d="M${ax} ${ay} L${right ? x - 14 : x + 14} ${y} L${x} ${y}" fill="none" stroke="${c}" stroke-width="1.6" ${ok(k) ? "" : 'stroke-dasharray="3 3"'}/>
      <circle cx="${ax}" cy="${ay}" r="4" fill="${c}" stroke="#0E1317" stroke-width="1.5"/>
      <g transform="translate(${bx} ${y - 16})"><rect width="104" height="32" rx="9" fill="${ok(k) ? c : "#151C21"}" stroke="${c}" stroke-width="1.5" ${ok(k) ? "" : 'stroke-dasharray="4 3"'}/>
      <text x="52" y="21" text-anchor="middle" font-size="15" font-weight="700" fill="${ok(k) ? "#0E1317" : "#93A3AD"}">${ok(k) ? "✓ " : "○ "}${label}</text></g>`;
  };
  // 손 (장갑 또는 맨손) — 손가락 4개 + 엄지
  const hand = (cx, cy, flip, gl) => {
    const s = flip ? -1 : 1, fill = gl ? "url(#gGlove)" : "#D9A882", st = gl ? "#2E8FC2" : "#B98663";
    return `<g transform="translate(${cx} ${cy}) scale(${s} 1)">
      ${gl ? `<rect x="-15" y="-16" width="30" height="14" rx="4" fill="#1F6E99"/>` : ""}
      <path d="M-13 -4 Q-15 14 -12 26 Q-10 34 -6 36 L8 36 Q14 34 15 24 L16 2 Q16 -4 10 -4 Z" fill="${fill}" stroke="${st}" stroke-width="1.5"/>
      <path d="M-13 2 Q-24 6 -22 16 Q-20 20 -12 16" fill="${fill}" stroke="${st}" stroke-width="1.5"/>
      <path d="M-6 36 L-7 46 M-1 36 L-1 49 M4 36 L5 48 M9 35 L11 44" stroke="${st}" stroke-width="6" stroke-linecap="round"/>
      <path d="M-6 36 L-7 46 M-1 36 L-1 49 M4 36 L5 48 M9 35 L11 44" stroke="${fill === "url(#gGlove)" ? "#5BC8FF" : "#D9A882"}" stroke-width="4" stroke-linecap="round"/>
    </g>`;
  };
  return `<svg viewBox="0 0 400 470" width="${w}" font-family="IBM Plex Sans KR, sans-serif" role="img" aria-label="보호구 착용 상태">
  <defs>
    <linearGradient id="gHelmet" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFE27A"/><stop offset=".55" stop-color="#F5C542"/><stop offset="1" stop-color="#C99A1E"/></linearGradient>
    <linearGradient id="gVest" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#D9701A"/><stop offset=".45" stop-color="#F7922E"/><stop offset="1" stop-color="#C9631A"/></linearGradient>
    <linearGradient id="gShirt" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2A3640"/><stop offset=".5" stop-color="#3A4954"/><stop offset="1" stop-color="#26313A"/></linearGradient>
    <linearGradient id="gPants" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#26324A"/><stop offset=".5" stop-color="#34425E"/><stop offset="1" stop-color="#222C42"/></linearGradient>
    <linearGradient id="gGlove" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7FD8FF"/><stop offset="1" stop-color="#2E8FC2"/></linearGradient>
    <linearGradient id="gSkin" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#D9A882"/><stop offset=".5" stop-color="#E8BC97"/><stop offset="1" stop-color="#C99572"/></linearGradient>
    <radialGradient id="gFloor" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#000" stop-opacity=".55"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
  </defs>
  <ellipse cx="200" cy="452" rx="105" ry="13" fill="url(#gFloor)"/>
  <!-- 안전화 -->
  <path d="M158 418 h34 v18 q0 8 -8 8 h-40 q-8 0 -6 -8 q2 -10 20 -18 z" fill="#1B2228" stroke="#0E1317" stroke-width="1.5"/>
  <path d="M208 418 h34 q18 8 20 18 q2 8 -6 8 h-40 q-8 0 -8 -8 z" fill="#1B2228" stroke="#0E1317" stroke-width="1.5"/>
  <rect x="136" y="438" width="58" height="6" rx="3" fill="#F5C542" opacity=".8"/><rect x="206" y="438" width="58" height="6" rx="3" fill="#F5C542" opacity=".8"/>
  <!-- 바지 -->
  <path d="M152 286 L248 286 L246 420 L208 420 L200 318 L192 420 L154 420 Z" fill="url(#gPants)" stroke="#1A2233" stroke-width="1.5"/>
  <path d="M172 360 h20 M208 360 h20" stroke="#4A5878" stroke-width="2"/>
  <!-- 팔 (셔츠 소매) -->
  <path d="M146 150 Q118 158 112 210 Q108 250 112 286" fill="none" stroke="url(#gShirt)" stroke-width="30" stroke-linecap="round"/>
  <path d="M254 150 Q282 158 288 210 Q292 250 288 286" fill="none" stroke="url(#gShirt)" stroke-width="30" stroke-linecap="round"/>
  <!-- 몸통 (셔츠) -->
  <path d="M146 146 Q200 130 254 146 L258 292 Q200 304 142 292 Z" fill="url(#gShirt)" stroke="#1E272E" stroke-width="1.5"/>
  <path d="M184 140 L200 168 L216 140" fill="#2A3640" stroke="#1E272E" stroke-width="1.5"/>
  <!-- 조끼 -->
  ${ok("vest") ? `
  <path d="M148 150 L184 140 L200 182 L216 140 L252 150 L256 292 Q200 304 144 292 Z" fill="url(#gVest)" stroke="#A8541A" stroke-width="2"/>
  <path d="M200 182 L200 296" stroke="#A8541A" stroke-width="2"/>
  <rect x="146" y="236" width="108" height="12" fill="#E3E8EB"/><rect x="146" y="262" width="108" height="12" fill="#E3E8EB"/>
  <rect x="146" y="236" width="108" height="3" fill="#FFFFFF" opacity=".8"/><rect x="146" y="262" width="108" height="3" fill="#FFFFFF" opacity=".8"/>
  <rect x="160" y="150" width="10" height="86" fill="#E3E8EB"/><rect x="230" y="150" width="10" height="86" fill="#E3E8EB"/>
  <rect x="210" y="200" width="28" height="20" rx="3" fill="none" stroke="#A8541A" stroke-width="2"/>` :
  `<path d="M148 150 L184 140 L200 182 L216 140 L252 150 L256 292 Q200 304 144 292 Z" ${ghost}/>`}
  <!-- 손 -->
  ${hand(112, 300, false, ok("gloves"))}${hand(288, 300, true, ok("gloves"))}
  ${ok("gloves") ? "" : `<rect x="88" y="278" width="48" height="76" rx="14" ${ghost}/><rect x="264" y="278" width="48" height="76" rx="14" ${ghost}/>`}
  <!-- 목 · 머리 -->
  <rect x="188" y="116" width="24" height="26" rx="6" fill="#C99572"/>
  <ellipse cx="162" cy="92" rx="7" ry="11" fill="#C99572"/><ellipse cx="238" cy="92" rx="7" ry="11" fill="#C99572"/>
  <ellipse cx="200" cy="88" rx="38" ry="44" fill="url(#gSkin)"/>
  ${ok("helmet") ? "" : `<path d="M162 80 Q160 44 200 42 Q240 44 238 80 Q226 60 200 60 Q174 60 162 80 Z" fill="#2B2420"/>`}
  <ellipse cx="186" cy="92" rx="4" ry="5" fill="#1E1A18"/><ellipse cx="214" cy="92" rx="4" ry="5" fill="#1E1A18"/>
  <path d="M178 80 q8 -4 16 0 M206 80 q8 -4 16 0" stroke="#3A2E28" stroke-width="3" fill="none" stroke-linecap="round"/>
  <path d="M190 112 q10 7 20 0" stroke="#8A5A48" stroke-width="3" fill="none" stroke-linecap="round"/>
  <!-- 안전모 -->
  ${ok("helmet") ? `
  <path d="M158 76 Q156 30 200 26 Q244 30 242 76 Z" fill="url(#gHelmet)" stroke="#B08518" stroke-width="2"/>
  <path d="M200 26 L200 76" stroke="#E0B02E" stroke-width="10" opacity=".7"/>
  <path d="M146 80 Q200 64 254 80 Q256 88 246 88 Q200 76 154 88 Q144 88 146 80 Z" fill="#E8B830" stroke="#B08518" stroke-width="2"/>
  <ellipse cx="180" cy="50" rx="10" ry="6" fill="#FFF4C2" opacity=".7" transform="rotate(-25 180 50)"/>
  <path d="M164 86 Q170 120 200 128 Q230 120 236 86" fill="none" stroke="#3A4852" stroke-width="2.5"/>` :
  `<path d="M158 76 Q156 30 200 26 Q244 30 242 76 Z M146 82 Q200 66 254 82" ${ghost}/>`}
  ${tag("helmet", "안전모", 290, 46, 238, 52, true, "#F5C542")}
  ${tag("vest", "조끼", 106, 206, 150, 206, false, "#F28C28")}
  ${tag("gloves", "장갑", 292, 396, 302, 344, true, "#4CC3FF")}
  </svg>`;
};
