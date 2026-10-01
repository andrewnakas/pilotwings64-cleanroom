window.CLEANROOM_PAD = {"adapter": "gamepad", "waitFor": "#overlay", "canvas": "#stage", "float": true};
// Clean-room N64 pad: one on-screen controller shared by every N64 web build (our own code).
//
// Shown on touch devices when no physical controller is connected; a controller that connects later hides it
// and takes over. ?touch=1 forces it on, ?touch=0 forces it off.
// Portrait: game screen on top, controls below. Landscape: full-height screen, translucent controls on the sides.
//
// Per-game settings come from window.CLEANROOM_PAD, set before this file loads (see games/<g>/pad.json):
//   labels   {A:'FIRE', ...}   small caption under a button
//   hide     ['L', 'CR']       buttons the game does not use
//   hint     'text'            one line shown in portrait
//   adapter  'n64wasm' | 'ejs' | 'gamepad' | 'mask' | 'keys' | 'none'   how state reaches the game (default 'gamepad')
//   keys     {A:['KeyE','Enter'], up:'KeyW', ...}   for adapter 'keys': keyboard codes per button and stick direction
//   sink     'module' | 'touchPad'   for 'mask': Module._web_touch_input(mask, x, y) or window.__touchPad
//   map      {A:0, B:2, ...}   for 'gamepad': N64 button -> standard gamepad button index
//   canvas   '#canvas'         the game canvas to place in the screen area
//   takeover true              hide the rest of the page while the pad is shown
//   float    true              leave the game element where it is in the page and position it under the pad
//                              (for runtimes that break when their element is moved, such as EmulatorJS)
//   css      '...'             extra page CSS while the pad or embedded mode is active
//   waitFor  '#start'          for 'gamepad': a start screen that must be gone before the pad appears
//
// State is always available to a shell's own code as window.cleanroomPad.sample():
//   {A,B,Start,Z,L,R,CU,CD,CL,CR,DU,DD,DL,DR, x, y}   buttons 0/1, stick -1..1 with up = +y
(function () {
  const CFG = Object.assign({ labels: {}, hide: [], hint: '', adapter: 'gamepad', canvas: '#canvas', takeover: true, map: {} },
    window.CLEANROOM_PAD || {});
  const q = new URLSearchParams(location.search);
  const forced = q.get('touch') === '1';
  const coarse = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
  const want = forced || (q.get('touch') !== '0' && coarse);
  window.cleanroomTouchWanted = want;   // read by the N64Wasm page hook
  // Framed in another page (the catalogue site) without touch: show only the game, with no pad.
  const framed = !want && (q.get('embed') === '1' || window.top !== window);

  // A start screen the build shows first: still there and visible?
  function waiting() {
    const e = CFG.waitFor && document.querySelector(CFG.waitFor);
    return !!e && getComputedStyle(e).display !== 'none';
  }

  const KEYS = ['A', 'B', 'Start', 'Z', 'L', 'R', 'CU', 'CD', 'CL', 'CR', 'DU', 'DD', 'DL', 'DR'];
  const S = { x: 0, y: 0 };
  for (const k of KEYS) S[k] = 0;
  window.cleanroomTouchState = S;

  // ---- physical controller -------------------------------------------------------------------------------
  // The browser's own list, kept before any virtual pad is installed over it.
  const nativePads = navigator.getGamepads ? navigator.getGamepads.bind(navigator) : () => [];
  function realPad() {
    for (const p of nativePads()) if (p && p.connected && !p.cleanroom) return p;
    return null;
  }
  // Standard-mapping controller -> N64. C buttons are the right stick.
  function fromPad(p) {
    const b = i => (p.buttons[i] && (p.buttons[i].pressed || p.buttons[i].value > 0.4) ? 1 : 0);
    const ax = i => p.axes[i] || 0, dead = v => (Math.abs(v) < 0.15 ? 0 : v);
    return {
      A: b(0), B: b(2) | b(1), Start: b(9), Z: b(6), L: b(4), R: b(5) | b(7),
      CU: ax(3) < -0.5 ? 1 : 0, CD: (ax(3) > 0.5 ? 1 : 0) | b(3), CL: ax(2) < -0.5 ? 1 : 0, CR: ax(2) > 0.5 ? 1 : 0,
      DU: b(12), DD: b(13), DL: b(14), DR: b(15), x: dead(ax(0)), y: -dead(ax(1)),
    };
  }
  function sample() {
    const p = realPad();
    return p ? fromPad(p) : S;
  }

  // ---- overlay --------------------------------------------------------------------------------------------
  const css = `
  html.cr-on, html.cr-on body { background:#000 !important; overscroll-behavior:none; }
  body.cr-touch { margin:0; overflow:hidden; touch-action:none; -webkit-user-select:none; user-select:none;
                  -webkit-touch-callout:none; position:fixed; inset:0; }
  body.cr-touch.cr-takeover > *:not(#cr-root):not(#soundBtn):not(.cr-float):not(script) { display:none !important; }
  body.cr-floating #cr-root, body.cr-floating #cr-screen { background:transparent; pointer-events:none; }
  body.cr-floating #cr-root > * { pointer-events:auto; }
  body.cr-floating #cr-screen { pointer-events:none !important; }
  .cr-float { position:fixed !important; margin:0 !important; z-index:2147482000; }
  #cr-root { position:fixed; inset:0; background:#000; color:#fff; z-index:2147483000;
             font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  #cr-screen { position:absolute; background:#000; display:flex; align-items:center; justify-content:center; }
  #cr-screen > * { width:100% !important; height:100% !important; max-width:none !important; max-height:none !important; }
  #cr-screen canvas { width:100% !important; height:100% !important; object-fit:contain; display:block; image-rendering:auto; }
  .cr-btn { position:absolute; display:flex; flex-direction:column; align-items:center; justify-content:center;
            border-radius:50%; font-weight:800; letter-spacing:.5px; touch-action:none; box-sizing:border-box;
            border:2px solid rgba(255,255,255,.35); box-shadow:0 3px 10px rgba(0,0,0,.5), inset 0 -4px 0 rgba(0,0,0,.25);
            transition:transform .05s, filter .05s; }
  .cr-btn small { font-size:10px; font-weight:700; opacity:.85; margin-top:1px; }
  .cr-btn.on { transform:scale(.92); filter:brightness(1.35); }
  .cr-pill { border-radius:14px; }
  #cr-A { background:radial-gradient(circle at 35% 30%, #5d8cff, #1d3fb8); }
  #cr-B { background:radial-gradient(circle at 35% 30%, #4fd06a, #16803a); }
  #cr-Z, #cr-L, #cr-R { background:linear-gradient(#6b6f80, #3a3d4a); }
  #cr-CL, #cr-CD, #cr-CU, #cr-CR { background:radial-gradient(circle at 35% 30%, #ffd84a, #c99a00); color:#2a2100; }
  #cr-Start { background:linear-gradient(#e24b4b, #9b1c1c); }
  #cr-stick { position:absolute; touch-action:none; }
  #cr-base { position:absolute; border-radius:50%; border:3px solid rgba(255,255,255,.35);
             background:radial-gradient(circle, rgba(255,255,255,.10), rgba(255,255,255,.03)); pointer-events:none; }
  #cr-knob { position:absolute; border-radius:50%; pointer-events:none;
             background:radial-gradient(circle at 35% 30%, #d9dce6, #7c8194); box-shadow:0 3px 10px rgba(0,0,0,.6); }
  body.cr-dpad #cr-base { border-radius:22%; }
  body.cr-dpad #cr-knob { border-radius:22%; }
  #cr-bar { position:absolute; top:max(6px, env(safe-area-inset-top)); left:max(8px, env(safe-area-inset-left)); display:flex; gap:8px; z-index:5; }
  #cr-bar button { background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.25);
                   border-radius:14px; padding:5px 10px; font-size:13px; font-weight:700; }
  #cr-hint { position:absolute; left:0; right:0; text-align:center; font-size:11px; opacity:.55; pointer-events:none; }
  body.cr-land .cr-btn, body.cr-land #cr-base, body.cr-land #cr-knob { opacity:.72; }
  body.cr-framed #cr-bar { display:none; }
  #cr-loading { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:15px; opacity:.7; }
  body.cr-pad .cr-btn, body.cr-pad #cr-stick, body.cr-pad #cr-hint, body.cr-pad #cr-mode { display:none !important; }
  `;

  const NAMES = { CL: '&#9664;C', CD: '&#9660;C', CU: '&#9650;C', CR: '&#9654;C', Start: 'START' };
  const BUTTONS = ['A', 'B', 'Z', 'L', 'R', 'CL', 'CD', 'CU', 'CR', 'Start'].filter(k => !CFG.hide.includes(k));
  const PILLS = ['Z', 'L', 'R', 'Start'];

  function el(tag, id, html, parent) {
    const e = document.createElement(tag);
    if (id) e.id = id;
    if (html) e.innerHTML = html;
    (parent || document.body).appendChild(e);
    return e;
  }

  let root, screen, stick, base, knob, hint, built = false, padOn = false, dpad = false;

  function build() {
    if (built) return;
    built = true;
    el('style', null, css + (CFG.css || ''), document.head);
    const vp = document.querySelector('meta[name=viewport]') || el('meta', null, null, document.head);
    vp.setAttribute('name', 'viewport');
    vp.setAttribute('content', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover');
    root = el('div', 'cr-root');
    screen = el('div', 'cr-screen', null, root);
    stick = el('div', 'cr-stick', null, root);
    base = el('div', 'cr-base', null, stick);
    knob = el('div', 'cr-knob', null, stick);
    for (const k of BUTTONS) {
      const cap = CFG.labels[k] ? '<small>' + CFG.labels[k] + '</small>' : '';
      const b = el('div', 'cr-' + k, (NAMES[k] || k) + cap, root);
      b.className = 'cr-btn' + (PILLS.includes(k) ? ' cr-pill' : '');
      bindButton(b, k);
    }
    const bar = el('div', 'cr-bar', null, root);
    const fs = el('button', null, 'Fullscreen', bar);
    fs.addEventListener('click', () => {
      const d = document.documentElement;
      (d.requestFullscreen || d.webkitRequestFullscreen || function () {}).call(d);
      try { window.screen.orientation.lock('landscape').catch(() => {}); } catch (e) {}
    });
    // Menus in some games read the D-pad, not the stick: this switches what the left thumb drives.
    const mode = el('button', 'cr-mode', 'Stick', bar);
    mode.addEventListener('click', () => {
      dpad = !dpad;
      mode.textContent = dpad ? 'D-pad' : 'Stick';
      document.body.classList.toggle('cr-dpad', dpad);
      S.x = S.y = S.DU = S.DD = S.DL = S.DR = 0;
    });
    hint = el('div', 'cr-hint', CFG.hint || 'Drag the left side to move', root);
    bindStick();
    document.documentElement.classList.add('cr-on');
    document.body.classList.add('cr-touch');
    if (CFG.takeover) document.body.classList.add('cr-takeover');
    window.addEventListener('resize', layout);
    window.addEventListener('orientationchange', () => setTimeout(layout, 200));
    adopt();
    layout();
  }

  // Move the game canvas into the screen area (it may not exist yet when the pad is built).
  let hold = false, floated = null;
  function adopt() {
    if (hold) return false;
    const c = document.querySelector(CFG.canvas);
    if (c && CFG.float) {
      floated = c;
      c.classList.add('cr-float');
      document.body.classList.add('cr-floating');
    } else if (c && screen && c.parentNode !== screen) screen.appendChild(c);
    return !!c;
  }

  function place(e, x, y, w, h, fs) {
    if (!e) return;
    if (e === screen && floated) place(floated, x, y, w, h);
    e.style.left = x + 'px'; e.style.top = y + 'px'; e.style.width = w + 'px'; e.style.height = h + 'px';
    if (fs) e.style.fontSize = fs + 'px';
  }

  let stickR = 60, rest = { x: 0, y: 0 }, origin = null, stickId = null;

  function layout() {
    if (!built) return;
    const W = window.innerWidth, H = window.innerHeight;
    const land = W > H;
    document.body.classList.toggle('cr-land', land);
    document.body.classList.toggle('cr-pad', padOn || framed);
    document.body.classList.toggle('cr-framed', framed);
    const $ = id => document.getElementById('cr-' + id);
    if (padOn || framed) {   // a controller is in use, or there is no pad: the screen takes everything
      const sw = Math.min(W, H / 0.75), sh = sw * 0.75;
      place(screen, (W - sw) / 2, (H - sh) / 2, sw, sh);
      return;
    }
    if (!land) {
      // portrait: screen on top (4:3), controls below
      const sh = Math.min(W * 0.75, H * 0.52);
      const sw = sh / 0.75;
      place(screen, (W - sw) / 2, 0, sw, sh);
      const top = sh, ch = H - sh, u = Math.min(W / 7.6, ch / 4.6);
      // top row: L  Z  C-up  START  C-right  R, evenly spaced
      const row = [['L', 1.05, 0.8, 0.3], ['Z', 1.05, 0.8, 0.3], ['CU', 0.9, 0.9, 0.22], ['Start', 1.4, 0.7, 0.24],
        ['CR', 0.9, 0.9, 0.22], ['R', 1.05, 0.8, 0.3]].filter(r => $(r[0]));
      const tot = row.reduce((a, r) => a + r[1] * u, 0), gap = (W * 0.94 - tot) / Math.max(1, row.length - 1);
      let x = W * 0.03;
      for (const [k, w, h, f] of row) { place($(k), x, top + u * 0.25 + (0.9 - h) * u / 2, w * u, h * u, f * u); x += w * u + gap; }
      stickR = u * 1.25;
      place(stick, 0, top + u * 1.2, W * 0.5, ch - u * 1.2);
      const bx = W * 0.96, by = top + ch - u * 0.4;
      place($('A'), bx - u * 1.55, by - u * 1.6, u * 1.55, u * 1.55, u * 0.42);
      place($('B'), bx - u * 3.05, by - u * 1.1, u * 1.3, u * 1.3, u * 0.38);
      place($('CL'), bx - u * 2.95, by - u * 2.95, u * 1.15, u * 1.15, u * 0.3);
      place($('CD'), bx - u * 1.45, by - u * 3.25, u * 1.15, u * 1.15, u * 0.3);
      hint.style.display = '';
      hint.style.top = (top + ch - 16) + 'px';
    } else {
      // landscape: full-height screen, controls float on the sides
      const sh = H, sw = Math.min(W, H / 0.75);
      place(screen, (W - sw) / 2, 0, sw, sh);
      const u = Math.min(H / 5.2, W / 11);
      place($('L'), u * 0.3, u * 0.6, u * 1.5, u * 0.7, u * 0.28);
      if ($('L')) place($('Z'), u * 2.0, u * 0.6, u * 1.5, u * 0.7, u * 0.28);
      else place($('Z'), u * 0.3, u * 0.6, u * 1.9, u * 0.7, u * 0.28);
      place($('R'), W - u * 2.2, u * 0.6, u * 1.9, u * 0.7, u * 0.28);
      place($('Start'), W / 2 - u * 0.8, H - u * 0.8, u * 1.6, u * 0.62, u * 0.24);
      stickR = u * 1.1;
      place(stick, 0, u * 1.5, W * 0.4, H - u * 1.5);
      const bx = W - u * 0.3, by = H - u * 0.3;
      place($('A'), bx - u * 1.45, by - u * 1.5, u * 1.45, u * 1.45, u * 0.4);
      place($('B'), bx - u * 2.85, by - u * 1.0, u * 1.2, u * 1.2, u * 0.35);
      place($('CL'), bx - u * 2.75, by - u * 2.75, u * 1.05, u * 1.05, u * 0.28);
      place($('CD'), bx - u * 1.35, by - u * 3.0, u * 1.05, u * 1.05, u * 0.28);
      place($('CU'), bx - u * 3.9, by - u * 2.0, u * 0.9, u * 0.9, u * 0.24);
      place($('CR'), bx - u * 4.0, by - u * 0.9, u * 0.8, u * 0.8, u * 0.24);
      hint.style.display = 'none';
    }
    // resting stick position: centre of its zone, lower half
    const r = stick.getBoundingClientRect();
    rest = { x: r.width * 0.5, y: r.height * 0.55 };
    drawStick(rest.x, rest.y, 0, 0);
  }

  function drawStick(ox, oy, dx, dy) {
    const R = stickR;
    place(base, ox - R, oy - R, 2 * R, 2 * R);
    const k = R * 0.55;
    place(knob, ox + dx - k, oy + dy - k, 2 * k, 2 * k);
  }

  function setStick(x, y) {
    if (dpad) {
      S.x = S.y = 0;
      S.DL = x < -0.4 ? 1 : 0; S.DR = x > 0.4 ? 1 : 0; S.DU = y > 0.4 ? 1 : 0; S.DD = y < -0.4 ? 1 : 0;
    } else { S.x = x; S.y = y; }
  }

  function bindStick() {
    stick.addEventListener('pointerdown', ev => {
      if (stickId !== null) return;
      stickId = ev.pointerId;
      stick.setPointerCapture(ev.pointerId);
      const r = stick.getBoundingClientRect();
      origin = { x: ev.clientX - r.left, y: ev.clientY - r.top };   // floating stick: centre where the thumb lands
      move(ev);
      ev.preventDefault();
    });
    const move = ev => {
      if (ev.pointerId !== stickId) return;
      const r = stick.getBoundingClientRect();
      let dx = ev.clientX - r.left - origin.x, dy = ev.clientY - r.top - origin.y;
      const R = stickR, d = Math.hypot(dx, dy);
      if (d > R) {   // drag the base along so the thumb never "loses" the stick
        origin.x += dx * (1 - R / d); origin.y += dy * (1 - R / d);
        dx *= R / d; dy *= R / d;
      }
      let x = dx / R, y = -dy / R;
      const m = Math.hypot(x, y), dead = 0.1;
      if (m < dead) { x = 0; y = 0; } else { const s = (m - dead) / (1 - dead) / m; x *= s; y *= s; }
      setStick(x, y);
      drawStick(origin.x, origin.y, dx, dy);
      ev.preventDefault();
    };
    stick.addEventListener('pointermove', move);
    const end = ev => {
      if (ev.pointerId !== stickId) return;
      stickId = null;
      setStick(0, 0);
      drawStick(rest.x, rest.y, 0, 0);
    };
    stick.addEventListener('pointerup', end);
    stick.addEventListener('pointercancel', end);
  }

  // A tap shorter than a game frame would be missed, so every press is held for at least this long.
  const MIN_HOLD = 90;
  function bindButton(b, k) {
    let since = 0, timer = 0;
    const down = ev => {
      b.setPointerCapture && b.setPointerCapture(ev.pointerId);
      clearTimeout(timer);
      since = performance.now();
      S[k] = 1; b.classList.add('on');
      if (navigator.vibrate) try { navigator.vibrate(8); } catch (e) {}
      ev.preventDefault();
    };
    const up = ev => {
      const release = () => { S[k] = 0; b.classList.remove('on'); };
      const held = performance.now() - since;
      if (held < MIN_HOLD) timer = setTimeout(release, MIN_HOLD - held); else release();
      ev.preventDefault();
    };
    b.addEventListener('pointerdown', down);
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('contextmenu', e => e.preventDefault());
  }

  // dev hook: ?touchscript=t:key:dur,... presses buttons (A B Z L R CL CD CU CR Start DU DD DL DR) or the stick
  // (up/down/left/right) as the overlay would, for headless checks.
  const ts = q.get('touchscript');
  if (ts) ts.split(',').forEach(item => {
    const [t, k, dur] = item.split(':');
    setTimeout(() => {
      const dir = { up: [0, 1], down: [0, -1], left: [-1, 0], right: [1, 0] }[k];
      if (dir) { S.x = dir[0]; S.y = dir[1]; } else S[k] = 1;
      setTimeout(() => { if (dir) { S.x = 0; S.y = 0; } else S[k] = 0; }, 1000 * parseFloat(dur || '0.2'));
    }, 1000 * parseFloat(t));
  });

  // ---- controller hot-plug --------------------------------------------------------------------------------
  function watchPads() {
    const now = !!realPad();
    if (now !== padOn) { padOn = now; layout(); }
  }
  if (want) {
    window.addEventListener('gamepadconnected', watchPads);
    window.addEventListener('gamepaddisconnected', watchPads);
    setInterval(watchPads, 1000);
  }

  // ---- adapters -------------------------------------------------------------------------------------------
  // N64Wasm: called from the page's module-ready hook; takes over its mobile input path, which is chosen at
  // boot. A controller plugged in later is read here and sent down the same path.
  window.cleanroomTouchInstall = function (app) {
    app.mobileMode = true;
    app.setupMobileMode = function () {
      build();
      adopt();
      const div = document.getElementById('canvasDiv');
      if (div) div.style.display = 'none';
      layout();
    };
    const ic = app.rivetsData.inputController;
    ic.updateMobileControls = function () {
      const s = sample(), b = v => (v ? '1' : '0');
      const bits = b(s.DU) + b(s.DD) + b(s.DL) + b(s.DR) + b(s.A) + b(s.B) + b(s.Start) + b(s.Z) + b(s.L) + b(s.R) +
                   b(s.CU) + b(s.CD) + b(s.CL) + b(s.CR);
      app.sendMobileControls(bits, s.x.toString(), s.y.toString());
    };
    ic.VectorX = 0; ic.VectorY = 0;
  };

  // Virtual gamepad: for runtimes that already read the Gamepad API (SDL builds, EmulatorJS). The pad reports
  // the standard mapping; CFG.map says which standard button each N64 button is in this game.
  const MAP = Object.assign({ A: 0, B: 2, Start: 9, Z: 6, L: 4, R: 5, DU: 12, DD: 13, DL: 14, DR: 15 }, CFG.map);
  function virtualPad() {
    const buttons = [];
    for (let i = 0; i < 17; i++) buttons.push({ pressed: false, touched: false, value: 0 });
    for (const k of KEYS) if (MAP[k] !== undefined && S[k]) buttons[MAP[k]] = { pressed: true, touched: true, value: 1 };
    // C buttons are the right stick unless the game maps them to buttons.
    const cx = MAP.CL === undefined ? S.CR - S.CL : 0, cy = MAP.CU === undefined ? S.CD - S.CU : 0;
    return { id: 'Clean Room Touch Pad (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard', cleanroom: true,
      timestamp: performance.now(), axes: [S.x, -S.y, cx, cy], buttons, vibrationActuator: null };
  }
  function installVirtualPad() {
    navigator.getGamepads = function () {
      if (realPad() || !built) return nativePads();
      return [virtualPad(), null, null, null];
    };
    const announce = () => {
      const ev = new Event('gamepadconnected');
      ev.gamepad = virtualPad();
      window.dispatchEvent(ev);
    };
    const start = () => {
      // A shell with its own start screen keeps it until the player has tapped it.
      if (waiting()) { setTimeout(start, 300); return; }
      build(); announce();
      const wait = setInterval(() => { if (adopt()) { clearInterval(wait); layout(); } }, 300);
    };
    if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
  }

  // EmulatorJS: inject into its input manager once the game has started. A physical controller is handled by
  // EmulatorJS itself, so only touch state is sent. Ids: 0 A, 1 B, 3 Start, 4-7 D-pad, 10 L, 11 R, 12 Z,
  // 16/17 stick right/left, 18/19 stick down/up, 20-23 C right/left/down/up.
  function installEJS() {
    const ID = { A: 0, B: 1, Start: 3, DU: 4, DD: 5, DL: 6, DR: 7, L: 10, R: 11, Z: 12, CR: 20, CL: 21, CD: 22, CU: 23 };
    const sent = {};
    const send = (gm, id, v) => { if (sent[id] !== v) { sent[id] = v; gm.simulateInput(0, id, v); } };
    el('style', null, '.ejs_virtualGamepad_parent { display:none !important; }', document.head);
    const tick = () => {
      requestAnimationFrame(tick);
      const e = window.EJS_emulator, gm = e && e.started && e.gameManager;
      if (!gm) return;
      if (!built) build();
      if (realPad()) return;
      for (const k in ID) send(gm, ID[k], S[k] ? 1 : 0);
      const ax = v => Math.round(Math.max(0, v) * 0x7fff);
      send(gm, 16, ax(S.x)); send(gm, 17, ax(-S.x)); send(gm, 18, ax(-S.y)); send(gm, 19, ax(S.y));
    };
    requestAnimationFrame(tick);
  }

  // N64 button mask + stick in -80..80: for shells whose own touch code already feeds the game this way.
  const BIT = { A: 0x8000, B: 0x4000, Z: 0x2000, Start: 0x1000, DU: 0x0800, DD: 0x0400, DL: 0x0200, DR: 0x0100,
    L: 0x0020, R: 0x0010, CU: 0x0008, CD: 0x0004, CL: 0x0002, CR: 0x0001 };
  function installMask() {
    const start = () => {
      if (waiting()) { setTimeout(start, 300); return; }
      build();
      const wait = setInterval(() => { if (adopt()) { clearInterval(wait); layout(); } }, 300);
      // The exported function aborts the program if it is called before the runtime is up.
      let ready = false;
      if (CFG.sink !== 'touchPad' && window.Module) {
        if (Module.calledRun) ready = true;
        const prev = Module.onRuntimeInitialized;
        Module.onRuntimeInitialized = function () { if (prev) prev.apply(this, arguments); ready = true; };
      }
      const tick = () => {
        requestAnimationFrame(tick);
        // A physical controller is read by the game itself.
        const live = !realPad();
        let mask = 0;
        if (live) for (const k in BIT) if (S[k]) mask |= BIT[k];
        const x = live ? Math.round(S.x * 80) : 0, y = live ? Math.round(S.y * 80) : 0;
        if (CFG.sink === 'touchPad') {
          const t = window.__touchPad;
          if (t) { t.buttons = mask; t.sx = x; t.sy = y; }
        } else if (ready) Module._web_touch_input(mask, x, y);
      };
      requestAnimationFrame(tick);
    };
    if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
  }

  // Keyboard: for builds that only take keys. Buttons and the four stick directions become key presses.
  const KEYCODE = { Enter: 13, Tab: 9, Space: 32, Escape: 27, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40,
    ShiftLeft: 16, ControlLeft: 17 };
  function keyEvent(type, code) {
    const letter = /^Key([A-Z])$/.exec(code);
    const kc = letter ? letter[1].charCodeAt(0) : KEYCODE[code] || 0;
    const key = letter ? letter[1].toLowerCase() : code === 'Space' ? ' ' : code;
    window.dispatchEvent(new KeyboardEvent(type, { code, key, keyCode: kc, which: kc, bubbles: true }));
  }
  function installKeys() {
    const map = CFG.keys || {}, down = {};
    const start = () => {
      if (waiting()) { setTimeout(start, 300); return; }
      build();
      const wait = setInterval(() => { if (adopt()) { clearInterval(wait); layout(); } }, 300);
      const tick = () => {
        requestAnimationFrame(tick);
        const on = { up: S.y > 0.4, down: S.y < -0.4, left: S.x < -0.4, right: S.x > 0.4 };
        for (const k of KEYS) on[k] = !!S[k];
        for (const k in map) {
          const want = !!on[k] && !realPad();
          if (want === !!down[k]) continue;
          down[k] = want;
          for (const code of [].concat(map[k])) keyEvent(want ? 'keydown' : 'keyup', code);
        }
      };
      requestAnimationFrame(tick);
    };
    if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
  }

  window.cleanroomPad = {
    wanted: want, state: S, sample,
    // For shells with their own input hook: build the overlay, then read sample() each frame.
    show() { if (document.body) build(); else document.addEventListener('DOMContentLoaded', build); },
    adopt, layout,
  };
  if (framed) {
    // Hide the build's own page until the game is running, then show just its canvas.
    const begin = () => {
      // The build's own start screen stays visible until it has been clicked.
      if (waiting()) { setTimeout(begin, 300); return; }
      hold = true;
      build();
      const note = el('div', 'cr-loading', 'Loading game…', root);
      const ready = () => {
        if (CFG.adapter === 'n64wasm') { const a = window.myApp; return !!(a && a.rivetsData && a.rivetsData.beforeEmulatorStarted === false); }
        if (CFG.adapter === 'ejs') { const e = window.EJS_emulator; return !!(e && e.started); }
        return !(waiting()) && !!document.querySelector(CFG.canvas);
      };
      const wait = setInterval(() => {
        if (!ready()) return;
        hold = false;
        if (adopt()) { clearInterval(wait); note.remove(); layout(); }
      }, 300);
    };
    if (document.body) begin(); else document.addEventListener('DOMContentLoaded', begin);
  }
  if (want && CFG.adapter === 'gamepad') installVirtualPad();
  if (want && CFG.adapter === 'mask') installMask();
  if (want && CFG.adapter === 'keys') installKeys();
  if (want && CFG.adapter === 'ejs') {
    if (document.head) installEJS(); else document.addEventListener('DOMContentLoaded', installEJS);
  }
})();
