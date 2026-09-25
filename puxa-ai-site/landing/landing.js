/* ============================================
   PUXA.AI — Landing (landing.html)
   Menu, revelação ao rolar, Odd's ao vivo e globo pontilhado.
   Formulário de acesso antecipado: puxa-ai-site/js/main.js (mesmos IDs).
   ============================================ */

const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ── Menu mobile ─────────────────────────────────────────────────────────────
const toggle = document.querySelector(".nav-toggle");
const links = document.querySelector(".nav-links");
if (toggle && links) {
  toggle.addEventListener("click", () => {
    const open = links.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });
  links.querySelectorAll("a").forEach(a => a.addEventListener("click", () => {
    links.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  }));
}

// ── Revelar ao rolar ────────────────────────────────────────────────────────
const io = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
  });
}, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
document.querySelectorAll(".rv").forEach(el => io.observe(el));

// ── Odd's ao vivo (dados simulados, como no site atual) ─────────────────────
if (!REDUCED) {
  setInterval(() => {
    document.querySelectorAll(".odd").forEach(el => {
      const v = parseFloat(el.textContent);
      if (!isFinite(v)) return;
      const d = (Math.random() - 0.5) * 0.1;
      el.textContent = Math.max(1.01, v + d).toFixed(2);
      el.classList.remove("up", "down");
      el.classList.add(d > 0 ? "up" : "down");
      setTimeout(() => el.classList.remove("up", "down"), 700);
    });
  }, 4000);
}

// ── Globo ───────────────────────────────────────────────────────────────────
const LAND_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";
const BRAZIL_ID = "076";          // ISO 3166-1 numérico do Brasil (em destaque)
const WORLD_DOT_STRENGTH = 0.2;   // opacidade relativa dos outros países
const BRAND = [62, 207, 142];   // verde da marca (tema escuro)

// Arenas (câmeras) e serviços da plataforma. [lon, lat]
const NODES = [
  { id: "fortaleza", at: [-38.52, -3.73],  icon: "i-video" },
  { id: "salvador",  at: [-38.50, -12.97], icon: "i-video" },
  { id: "araguaina", at: [-48.20, -7.19],  icon: "i-video" },
  { id: "campo",     at: [-54.62, -20.47], icon: "i-video" },
  { id: "ia",        at: [-47.88, -15.79], icon: "i-cpu", label: "IA Puxa.ai", solid: true, labelLeft: true },
  { id: "dados",     at: [-43.20, -22.90], icon: "i-db",  label: "Banco de dados", solid: true },
];
const ARCS = [
  ["fortaleza", "ia"], ["salvador", "ia"], ["araguaina", "ia"], ["campo", "ia"], ["ia", "dados"],
];

async function initGlobe() {
  const canvas = document.getElementById("globe");
  const nodesEl = document.getElementById("globe-nodes");
  if (!canvas || !window.d3 || !window.topojson) return;
  const ctx = canvas.getContext("2d");

  let world, countries, brazil;
  try {
    const topo = await (await fetch(LAND_URL)).json();
    countries = window.topojson.feature(topo, topo.objects.countries);
    brazil = countries.features.find(f => f.id === BRAZIL_ID);
    world = { type: "FeatureCollection", features: countries.features.filter(f => f.id !== BRAZIL_ID) };
    if (!brazil) return;
  } catch {
    return; // sem rede: a seção continua com os cartões
  }

  // 1) rasteriza (equiretangular) o Brasil e o resto do mundo em máscaras separadas
  const RW = 1440, RH = 720;
  const eq = d3.geoEquirectangular().scale(RW / (2 * Math.PI)).translate([RW / 2, RH / 2]);
  function rasterize(geo) {
    const m = document.createElement("canvas");
    m.width = RW; m.height = RH;
    const c = m.getContext("2d", { willReadFrequently: true });
    c.fillStyle = "#000"; c.beginPath(); d3.geoPath(eq, c)(geo); c.fill();
    const data = c.getImageData(0, 0, RW, RH).data;
    return (lon, lat) => {
      const x = Math.floor((lon + 180) / 360 * RW), y = Math.floor((90 - lat) / 180 * RH);
      return data[(Math.min(RH - 1, Math.max(0, y)) * RW + Math.min(RW - 1, Math.max(0, x))) * 4 + 3] > 0;
    };
  }
  const inBrazil = rasterize(brazil);
  const inWorld = rasterize(world);

  // 2) grade de pontos com espaçamento uniforme na esfera
  function sample(step, test) {
    const out = [];
    for (let lat = -80; lat <= 82; lat += step) {
      const dLon = step / Math.max(0.15, Math.cos(lat * Math.PI / 180));
      for (let lon = -180; lon < 180; lon += dLon) if (test(lon, lat)) out.push([lon, lat]);
    }
    return out;
  }
  const dotsBR = sample(0.55, inBrazil);                       // Brasil: denso e forte
  const dotsWorld = sample(0.95, (lon, lat) => inWorld(lon, lat) && !inBrazil(lon, lat));   // resto: apagado

  // 3) nós no DOM (ícones)
  nodesEl.innerHTML = NODES.map(n =>
    `<div class="gnode${n.solid ? " solid" : ""}${n.labelLeft ? " label-left" : ""}" data-id="${n.id}"><svg><use href="#${n.icon}"/></svg>${n.label ? `<span class="glabel">${n.label}</span>` : ""}</div>`
  ).join("");
  const nodeEls = Object.fromEntries([...nodesEl.children].map(el => [el.dataset.id, el]));
  const byId = Object.fromEntries(NODES.map(n => [n.id, n]));
  const graticule = d3.geoGraticule10();
  const proj = d3.geoOrthographic().clipAngle(90);
  const path = d3.geoPath(proj, ctx);

  let size = 0, dpr = 1;
  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    size = canvas.clientWidth;
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    proj.scale(size / 2 - 2).translate([size / 2, size / 2]);
  }
  resize();
  window.addEventListener("resize", () => { resize(); draw(performance.now()); });

  const wrap = canvas.parentElement;
  const offX = () => (wrap.clientWidth - size) / 2;   // canvas centralizado no container

  function arcPoints(a, b, n = 48) {
    const interp = d3.geoInterpolate(a, b);
    const [cx, cy] = proj.translate();
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const p = proj(interp(t));
      if (!p) return null;
      const lift = 1 + 0.14 * Math.sin(Math.PI * t);       // arco "levantado" da superfície
      pts.push([cx + (p[0] - cx) * lift, cy + (p[1] - cy) * lift]);
    }
    return pts;
  }

  // Rotação: começa centrada no Brasil (vista ao sul para o Brasil subir no quadro).
  // Antes da primeira interação o globo balança devagar; depois fica onde o usuário deixou.
  const rot = { lon: 53, lat: 30, vLon: 0, vLat: 0 };
  let touched = false, dragging = false;

  function draw(now) {
    const t = now / 1000;
    if (!dragging) {                                    // inércia depois de soltar
      rot.lon += rot.vLon; rot.lat += rot.vLat;
      rot.vLon *= 0.94; rot.vLat *= 0.94;
      if (Math.abs(rot.vLon) < 0.01) rot.vLon = 0;
      if (Math.abs(rot.vLat) < 0.01) rot.vLat = 0;
    }
    rot.lat = Math.max(-60, Math.min(70, rot.lat));
    const sway = touched || REDUCED ? 0 : Math.sin(t / 9) * 6;
    const lon0 = rot.lon + sway;
    const lat0 = rot.lat;
    proj.rotate([lon0, lat0, 0]);
    const center = [-lon0, -lat0];

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);

    // esfera + graticulado
    ctx.beginPath(); path({ type: "Sphere" });
    ctx.fillStyle = "#141414"; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = "#2E2E2E"; ctx.stroke();
    ctx.beginPath(); path(graticule);
    ctx.strokeStyle = "rgba(255,255,255,0.05)"; ctx.lineWidth = 0.8; ctx.stroke();

    // pontos (mais fortes no centro, somem na borda); resto do mundo bem apagado, Brasil em destaque
    const r = Math.max(1.1, size / 430);
    const drawDots = (list, strength) => {
      for (const d of list) {
        const dist = d3.geoDistance(d, center);
        if (dist > Math.PI / 2) continue;
        const p = proj(d);
        const a = (0.22 + 0.78 * Math.cos(dist)) * strength;
        ctx.fillStyle = `rgba(${BRAND[0]},${BRAND[1]},${BRAND[2]},${a.toFixed(3)})`;
        ctx.fillRect(p[0] - r / 2, p[1] - r / 2, r, r);
      }
    };
    drawDots(dotsWorld, WORLD_DOT_STRENGTH);
    drawDots(dotsBR, 1);

    // arcos + pulso viajando
    ctx.lineWidth = 1.5;
    ARCS.forEach(([a, b], k) => {
      const pts = arcPoints(byId[a].at, byId[b].at);
      if (!pts) return;
      ctx.beginPath();
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.strokeStyle = "rgba(62,207,142,0.75)"; ctx.stroke();
      if (!REDUCED) {
        const u = ((t * 0.45 + k * 0.23) % 1);
        const [x, y] = pts[Math.floor(u * (pts.length - 1))];
        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = "#6EE7B7"; ctx.fill();
      }
    });

    // posiciona os nós
    NODES.forEach(n => {
      const el = nodeEls[n.id];
      const visible = d3.geoDistance(n.at, center) < Math.PI / 2 - 0.05;
      const p = proj(n.at);
      el.style.opacity = visible ? "1" : "0";
      if (p) el.style.transform = `translate(${offX() + p[0]}px, ${p[1]}px)`;
    });
  }

  // anima só quando o globo está na tela
  let running = false, raf = 0;
  const loop = now => { draw(now); if (running) raf = requestAnimationFrame(loop); };
  draw(performance.now());
  if (!REDUCED) {
    new IntersectionObserver(([e]) => {
      running = e.isIntersecting;
      cancelAnimationFrame(raf);
      if (running) raf = requestAnimationFrame(loop);
    }).observe(canvas);
  }

  // ── Arrastar para girar (mouse, caneta e toque) ──
  // graus por pixel: o ponto sob o cursor acompanha a mão no centro do globo
  const degPerPx = () => 180 / (Math.PI * proj.scale());
  let last = null, lastT = 0;
  canvas.style.cursor = "grab";
  canvas.style.touchAction = "pan-y";               // no celular, arrastar na vertical ainda rola a página
  canvas.addEventListener("pointerdown", e => {
    // incorpora o balanço atual na rotação: o globo não salta quando o balanço para
    if (!touched && !REDUCED) rot.lon += Math.sin(performance.now() / 1000 / 9) * 6;
    dragging = true; touched = true;
    last = [e.clientX, e.clientY]; lastT = performance.now();
    rot.vLon = rot.vLat = 0;
    canvas.setPointerCapture(e.pointerId);
    canvas.style.cursor = "grabbing";
  });
  canvas.addEventListener("pointermove", e => {
    if (!dragging || !last) return;
    const k = degPerPx();
    const dx = e.clientX - last[0], dy = e.clientY - last[1];
    const now = performance.now(), dt = Math.max(1, now - lastT);
    rot.lon += dx * k;
    rot.lat -= dy * k;
    // velocidade (graus por quadro de ~16 ms) para a inércia
    rot.vLon = dx * k * (16 / dt);
    rot.vLat = -dy * k * (16 / dt);
    last = [e.clientX, e.clientY]; lastT = now;
    if (!running) draw(now);                         // movimento reduzido: redesenha só no arraste
  });
  const end = e => {
    if (!dragging) return;
    dragging = false; last = null;
    if (performance.now() - lastT > 80) rot.vLon = rot.vLat = 0;   // parou antes de soltar: sem inércia
    if (REDUCED) rot.vLon = rot.vLat = 0;
    canvas.style.cursor = "grab";
    try { canvas.releasePointerCapture(e.pointerId); } catch {}
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
}

initGlobe();

// ── Arena: replay animado da prova (vista de cima) ──────────────────────────
// Tudo em metros: pista 120 × 30 m, faixa de pontuação de 9 m (Regulamento ABVAQ).
const ARENA = { L: 120, W: 30, faixa: [92, 101], largada: 8 };
const C = {
  floor: "#0F0F0F", grain: "rgba(255,255,255,0.045)", edge: "#3A3A3A", label: "#6F6F6F",
  faixaFill: "rgba(62,207,142,0.06)", faixaLine: "#4A4A4A",
  boi: "#3ECF8E", boiGlow: "rgba(62,207,142,0.9)", pux: "#FAFAFA", est: "#8B8B8B",
  hudBg: "rgba(14,14,14,0.82)", hudLine: "#2E2E2E", text: "#EDEDED", muted: "#A1A1A1",
};

/** Simula a prova a 60 Hz: posições (m) de boi, puxador e esteireiro + velocidade do boi. */
function simulateRun() {
  const dt = 1 / 60, frames = [];
  const smooth = (a, b, x) => { const u = Math.min(1, Math.max(0, (x - a) / (b - a))); return u * u * (3 - 2 * u); };
  let s = 0, t = 0, v = 3, tD = null, boiStop = null;
  const hx = [0, 0], hv = [0, 0];                     // horses após a derrubada
  while (t < 14) {
    let bx, by, px, py, ex, ey, vb;
    if (tD === null) {
      v = 3 + 8.5 * smooth(0, 2.6, t);                // arrancada até ~11,5 m/s (≈41 km/h)
      s += v * dt;
      bx = s + 2;
      const lat = 15 + 3.2 * Math.sin(bx / 17) * (1 - smooth(70, 92, bx)) + 1.2 * smooth(70, 92, bx);
      const off = -1.6 + 1.9 * smooth(10, 45, bx);    // cavalos alcançam e emparelham o boi
      by = lat; px = bx + off; py = lat + 2.4; ex = bx + off - 0.4; ey = lat - 2.4; vb = v;
      if (bx >= (ARENA.faixa[0] + ARENA.faixa[1]) / 2) { tD = t; boiStop = { x: bx, y: by, v }; hx[0] = px; hx[1] = ex; hv[0] = hv[1] = v; }
    } else {
      const k = t - tD;
      // boi derrubado: desliza ~2,5 m e para, deitando para o lado do puxador
      const slide = boiStop.v * 0.22 * (1 - Math.exp(-k / 0.22));
      bx = boiStop.x + slide; by = boiStop.y + 0.9 * smooth(0, 0.5, k); vb = boiStop.v * Math.exp(-k / 0.22);
      // cavalos freiam e abrem para os lados
      hv[0] = hv[1] = Math.max(2.5, boiStop.v - 4.2 * k);
      hx[0] += hv[0] * dt; hx[1] += hv[1] * dt;
      px = hx[0]; py = boiStop.y + 2.4 + 3.2 * smooth(0, 2.2, k);
      ex = hx[1]; ey = boiStop.y - 2.4 - 2.2 * smooth(0, 2.2, k);
      if (k > 2.6 || px > ARENA.L - 3) break;
    }
    frames.push({ t, bx, by, px, py, ex, ey, vb, dist: bx - 2 });
    t += dt;
  }
  return { frames, tD, dt };
}

function initArena() {
  const canvas = document.getElementById("arena");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const run = simulateRun();
  const F = run.frames, N = F.length, iD = Math.round(run.tD / run.dt);
  const HOLD = 1.6, FADE = 0.7;                       // segundos parado no fim e de transição
  const cycle = N * run.dt + HOLD + FADE;
  const TRAIL = 1.4;                                  // segundos de rastro

  let W = 0, H = 0, dpr = 1, bg, heat, hctx, lastStamp = -1;
  let pad, top, bottom;
  const X = m => pad + (m / ARENA.L) * (W - 2 * pad);
  const Y = m => top + (m / ARENA.W) * (H - top - bottom);

  function layout() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth; H = Math.round(W / 2);
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    pad = Math.max(14, W * 0.035); top = Math.max(26, H * 0.12); bottom = Math.max(30, H * 0.14);
    bg = document.createElement("canvas"); bg.width = canvas.width; bg.height = canvas.height;
    heat = document.createElement("canvas"); heat.width = canvas.width; heat.height = canvas.height;
    hctx = heat.getContext("2d");
    drawBackground();
    lastStamp = -1;
  }

  function drawBackground() {
    const b = bg.getContext("2d");
    b.setTransform(dpr, 0, 0, dpr, 0, 0);
    b.fillStyle = C.floor; b.fillRect(0, 0, W, H);
    const x0 = X(0), x1 = X(ARENA.L), y0 = Y(0), y1 = Y(ARENA.W), r = 10;
    // piso com granulação (areia)
    b.save(); b.beginPath(); b.roundRect(x0, y0, x1 - x0, y1 - y0, r); b.clip();
    b.fillStyle = C.grain;
    for (let yy = y0 + 3; yy < y1; yy += 7) for (let xx = x0 + ((yy / 7) % 2) * 3.5; xx < x1; xx += 7) b.fillRect(xx, yy, 1, 1);
    // zona de largada hachurada
    b.strokeStyle = "rgba(255,255,255,0.05)"; b.lineWidth = 1;
    for (let k = -H; k < X(ARENA.largada) - x0; k += 8) { b.beginPath(); b.moveTo(x0 + k, y1); b.lineTo(x0 + k + (y1 - y0), y0); b.stroke(); }
    b.fillStyle = C.floor; b.fillRect(X(ARENA.largada), y0, x1 - X(ARENA.largada), y1 - y0);
    for (let yy = y0 + 3; yy < y1; yy += 7) for (let xx = X(ARENA.largada) + ((yy / 7) % 2) * 3.5; xx < x1; xx += 7) { b.fillStyle = C.grain; b.fillRect(xx, yy, 1, 1); }
    // faixa de pontuação
    b.fillStyle = C.faixaFill; b.fillRect(X(ARENA.faixa[0]), y0, X(ARENA.faixa[1]) - X(ARENA.faixa[0]), y1 - y0);
    b.restore();
    // linha central tracejada
    b.setLineDash([2, 6]); b.strokeStyle = "rgba(255,255,255,0.07)";
    b.beginPath(); b.moveTo(X(ARENA.largada), Y(ARENA.W / 2)); b.lineTo(x1 - 6, Y(ARENA.W / 2)); b.stroke();
    // borda
    b.setLineDash([5, 5]); b.strokeStyle = C.edge; b.lineWidth = 1;
    b.beginPath(); b.roundRect(x0 + .5, y0 + .5, x1 - x0 - 1, y1 - y0 - 1, r); b.stroke();
    b.setLineDash([]);
    // linhas da faixa
    b.strokeStyle = C.faixaLine; b.lineWidth = 2;
    ARENA.faixa.forEach(m => { b.beginPath(); b.moveTo(X(m), y0); b.lineTo(X(m), y1); b.stroke(); });
    // rótulos
    b.font = `600 ${Math.max(9, W / 60)}px "JetBrains Mono", monospace`; b.fillStyle = C.label; b.textAlign = "center"; b.textBaseline = "alphabetic";
    b.fillText("LARGADA", X(ARENA.largada / 2) + 18, y0 - 9);
    b.fillText("PISTA", X(50), y0 - 9);
    b.fillText("FAIXA · 9 m", X((ARENA.faixa[0] + ARENA.faixa[1]) / 2), y0 - 9);
    // régua em metros
    b.strokeStyle = "#3A3A3A"; b.fillStyle = "#5E5E5E"; b.lineWidth = 1;
    b.font = `500 ${Math.max(8, W / 70)}px "JetBrains Mono", monospace`;
    const ry = y1 + 10;
    b.beginPath(); b.moveTo(x0, ry); b.lineTo(x1, ry); b.stroke();
    for (let m = 0; m <= ARENA.L; m += 5) {
      const big = m % 20 === 0;
      b.beginPath(); b.moveTo(X(m), ry); b.lineTo(X(m), ry + (big ? 6 : 3)); b.stroke();
      if (big) b.fillText(m === 0 ? "0 m" : String(m), X(m), ry + 18);
    }
  }

  function stampHeat(i) {
    // acumula calor nas posições por onde a disputa passou
    hctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (let j = lastStamp + 1; j <= i; j++) {
      if (j % 3) continue;                            // 20 Hz basta para o calor
      const f = F[j];
      const inD = j >= iD;                            // derrubada concentra o calor
      if (inD && f.vb < 1.5) continue;                // boi parado: não satura o ponto da queda
      const r = H * (inD ? 0.12 : 0.095);
      const a = inD ? 0.05 : 0.022;
      const g = hctx.createRadialGradient(X(f.bx), Y(f.by), 0, X(f.bx), Y(f.by), r);
      g.addColorStop(0, `rgba(62,207,142,${a})`); g.addColorStop(1, "rgba(62,207,142,0)");
      hctx.fillStyle = g; hctx.fillRect(X(f.bx) - r, Y(f.by) - r, 2 * r, 2 * r);
    }
    lastStamp = i;
  }

  function trail(i, kx, ky, color, width) {
    const n = Math.round(TRAIL / run.dt), s0 = Math.max(1, i - n);
    ctx.lineCap = "round"; ctx.lineWidth = width;
    for (let j = s0; j <= i; j++) {
      const a = (j - s0) / (i - s0 + 1);
      ctx.strokeStyle = color.replace("A)", `${(a * a * 0.95).toFixed(3)})`);
      ctx.beginPath(); ctx.moveTo(X(F[j - 1][kx]), Y(F[j - 1][ky])); ctx.lineTo(X(F[j][kx]), Y(F[j][ky])); ctx.stroke();
    }
  }

  function head(x, y, color, glow, r) {
    ctx.save();
    ctx.shadowColor = glow; ctx.shadowBlur = 14;
    ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
    // contorno escuro: separa o ponto do mapa de calor por baixo
    ctx.strokeStyle = "rgba(10,10,10,0.9)"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(x, y, r + 0.75, 0, Math.PI * 2); ctx.stroke();
  }

  function pill(text, x, y, fg, bd) {
    ctx.font = `600 ${Math.max(9, W / 64)}px "JetBrains Mono", monospace`;
    const w = ctx.measureText(text).width + 12, h = Math.max(16, W / 36);
    ctx.fillStyle = C.hudBg; ctx.strokeStyle = bd; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(x - w / 2, y - h / 2, w, h, 4); ctx.fill(); ctx.stroke();
    ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, x, y + 0.5);
  }

  function hud(f, elapsed) {
    // painel no canto inferior esquerdo da pista (área livre do percurso)
    const fs = Math.max(9, W / 64);
    const hh = 3 * fs * 1.7 + 10;
    const x = X(0) + 10, y = Y(ARENA.W) - hh - 10;
    const rows = [
      ["REPLAY", `${elapsed.toFixed(1).padStart(4, "0")} s`],
      ["VEL. BOI", `${(f.vb * 3.6).toFixed(1)} km/h`],
      ["DISTÂNCIA", `${Math.max(0, f.dist).toFixed(0)} m`],
    ];
    ctx.font = `500 ${fs}px "JetBrains Mono", monospace`;
    const w = fs * 15.5, h = rows.length * fs * 1.7 + 10;
    ctx.fillStyle = C.hudBg; ctx.strokeStyle = C.hudLine; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(x, y, w, h, 6); ctx.fill(); ctx.stroke();
    rows.forEach(([k, v], i) => {
      const yy = y + 8 + fs + i * fs * 1.7;
      ctx.textAlign = "left"; ctx.textBaseline = "alphabetic"; ctx.fillStyle = C.muted; ctx.fillText(k, x + 10, yy);
      ctx.textAlign = "right"; ctx.fillStyle = i === 1 ? C.boi : C.text; ctx.fillText(v, x + w - 10, yy);
    });
  }

  function frame(time) {
    const tc = time % cycle;
    const runT = N * run.dt;
    const i = Math.min(N - 1, Math.floor(tc / run.dt));
    const f = F[i];
    if (i < lastStamp) { hctx.setTransform(1, 0, 0, 1, 0, 0); hctx.clearRect(0, 0, heat.width, heat.height); lastStamp = -1; }
    stampHeat(i);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(bg, 0, 0);
    // calor (aditivo, levemente desfocado)
    ctx.save(); ctx.globalCompositeOperation = "lighter"; ctx.filter = "blur(6px)"; ctx.drawImage(heat, 0, 0); ctx.restore();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // faixa acende no instante da derrubada
    const sinceD = (i - iD) * run.dt;
    if (sinceD >= 0) {
      const a = Math.max(0.1, 0.55 * Math.exp(-sinceD / 0.6));
      ctx.fillStyle = `rgba(62,207,142,${a * 0.35})`;
      ctx.fillRect(X(ARENA.faixa[0]), Y(0), X(ARENA.faixa[1]) - X(ARENA.faixa[0]), Y(ARENA.W) - Y(0));
      ctx.strokeStyle = `rgba(62,207,142,${Math.min(1, a + 0.25)})`; ctx.lineWidth = 2;
      ARENA.faixa.forEach(m => { ctx.beginPath(); ctx.moveTo(X(m), Y(0)); ctx.lineTo(X(m), Y(ARENA.W)); ctx.stroke(); });
    }

    // rastros
    trail(i, "ex", "ey", "rgba(139,139,139,A)", 1.6);
    trail(i, "px", "py", "rgba(250,250,250,A)", 1.8);
    trail(i, "bx", "by", "rgba(62,207,142,A)", 2.4);

    // onda de impacto da derrubada
    if (sinceD >= 0 && sinceD < 1.2) {
      const d = F[iD], k = sinceD / 1.2;
      ctx.strokeStyle = `rgba(110,231,183,${(1 - k) * 0.9})`; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(X(d.bx), Y(d.by), 6 + k * H * 0.22, 0, Math.PI * 2); ctx.stroke();
    }

    // pulso do boi enquanto corre
    if (sinceD < 0) {
      const k = (tc % 1);
      ctx.strokeStyle = `rgba(62,207,142,${(1 - k) * 0.5})`; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.arc(X(f.bx), Y(f.by), 5 + k * 14, 0, Math.PI * 2); ctx.stroke();
    }

    // animais
    head(X(f.ex), Y(f.ey), C.est, "rgba(139,139,139,0.6)", 3.8);
    head(X(f.px), Y(f.py), C.pux, "rgba(250,250,250,0.7)", 4.2);
    head(X(f.bx), Y(f.by), C.boi, C.boiGlow, 5);

    // rótulos que acompanham
    hud(f, Math.min(tc, runT));   // painel antes dos rótulos: rótulos ficam por cima
    const lab = Math.min(1, Math.max(0, (tc - 1.0) / 0.6));   // rótulos entram depois da largada
    const clearOfHud = X(Math.min(f.px, f.ex)) > X(0) + 10 + Math.max(9, W / 64) * 15.5 + 30;
    if (lab > 0.2 && W > 420 && clearOfHud) {
      ctx.globalAlpha = lab;
      pill("PUXADOR", X(f.px), Y(f.py) + H * 0.075, C.text, C.hudLine);
      pill("ESTEIREIRO", X(f.ex), Y(f.ey) - H * 0.075, C.muted, C.hudLine);
      ctx.globalAlpha = 1;
    }

    // resultado
    if (sinceD >= 0.25) {
      const a = Math.min(1, (sinceD - 0.25) / 0.35);
      const d = F[iD];
      ctx.globalAlpha = a;
      pill("✓ VALEU O BOI", X(d.bx), Y(0) + H * 0.09, C.boi, "rgba(62,207,142,0.55)");
      ctx.globalAlpha = 1;
    }

    // transição de volta ao início
    if (tc > runT + HOLD) {
      const a = (tc - runT - HOLD) / FADE;
      ctx.fillStyle = `rgba(14,14,14,${Math.min(1, a)})`;
      ctx.fillRect(0, 0, W, H);
    }
  }

  layout();
  window.addEventListener("resize", () => { layout(); });

  if (REDUCED) {
    // sem animação: mostra o quadro final, com o calor acumulado da prova inteira
    const t = (iD / 60) + 1.2;
    frame(t);
    return;
  }
  let running = false, raf = 0, t0 = performance.now(), paused = 0;
  const loop = now => { frame((now - t0) / 1000); if (running) raf = requestAnimationFrame(loop); };
  new IntersectionObserver(([e]) => {
    if (e.isIntersecting && !running) { running = true; t0 = performance.now() - paused * 1000; raf = requestAnimationFrame(loop); }
    else if (!e.isIntersecting && running) { running = false; paused = ((performance.now() - t0) / 1000) % cycle; cancelAnimationFrame(raf); }
  }, { threshold: 0.15 }).observe(canvas);
  frame(0);
}

initArena();

// ── Cavalo holográfico (Métricas) ───────────────────────────────────────────
// Nuvem de pontos de um ciclo de galope (tools/build_horse_holo.py): patas em verde, corpo em cinza.
const HOLO_URL = "puxa-ai-site/landing/horse-holo.json";

async function initHolo() {
  const canvas = document.getElementById("holo");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let data;
  try { data = await (await fetch(HOLO_URL)).json(); } catch { return; }

  const GW = data.w, GH = data.h;
  const unpack = b64 => {
    const bin = atob(b64), idx = [];
    for (let i = 0; i < GW * GH; i++) if ((bin.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1) idx.push(i);
    return idx;
  };
  const frames = data.frames.map(f => ({ body: unpack(f.body), legs: unpack(f.legs) }));

  let W = 0, H = 0, dpr = 1, cell = 1, ox = 0, oy = 0, floorY = 0, dot = 1;
  const glow = document.createElement("canvas");
  const gctx = glow.getContext("2d");
  function layout() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    glow.width = canvas.width; glow.height = canvas.height;
    cell = Math.min((W * 0.86) / GW, (H * 0.70) / GH);
    ox = (W - GW * cell) / 2;
    floorY = H * 0.80;
    oy = floorY - GH * cell * 0.97;              // cascos tocam o chão
    dot = Math.max(1.2, cell * 0.62);
  }
  layout();
  window.addEventListener("resize", layout);

  function drawCloud(list, color, alpha, t, scanY, yFlip, rowJitter) {
    for (const i of list) {
      const gx = i % GW, gy = (i / GW) | 0;
      let x = ox + gx * cell, y = oy + gy * cell;
      if (rowJitter) x += rowJitter(gy);
      if (yFlip) y = floorY + (floorY - y) * 0.55;   // reflexo achatado
      let a = alpha;
      const d = Math.abs(y - scanY);
      if (!yFlip && d < 26) a = Math.min(1, a + (1 - d / 26) * 0.55);   // varredura ilumina
      if (yFlip) a *= Math.max(0, 1 - (y - floorY) / (H - floorY));      // reflexo some
      ctx.fillStyle = `rgba(${color},${a.toFixed(3)})`;
      ctx.fillRect(x, y, dot, dot);
    }
  }

  function floor(t) {
    ctx.save();
    const cx = W / 2, rx = GW * cell * 0.62, ry = rx * 0.16;
    // anéis da base
    for (let k = 0; k < 4; k++) {
      const s = 1 - k * 0.2, pulse = 0.5 + 0.5 * Math.sin(t * 1.6 - k);
      ctx.strokeStyle = `rgba(62,207,142,${(0.10 + 0.10 * pulse) * s})`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.ellipse(cx, floorY + 2, rx * s, ry * s, 0, 0, Math.PI * 2); ctx.stroke();
    }
    // grade em perspectiva
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    for (let k = -6; k <= 6; k++) {
      ctx.beginPath(); ctx.moveTo(cx + k * rx * 0.18, floorY); ctx.lineTo(cx + k * rx * 0.42, H); ctx.stroke();
    }
    for (let k = 1; k <= 4; k++) {
      const y = floorY + (H - floorY) * (k / 5) ** 1.6;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
    ctx.restore();
  }

  const period = 1 / data.fps;                     // segundos por quadro do ciclo
  function draw(now) {
    const t = now / 1000;
    const f = frames[Math.floor(t / period) % frames.length];
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    floor(t);
    const flicker = REDUCED ? 1 : 0.9 + 0.1 * Math.sin(t * 13) * Math.sin(t * 7.3);
    const scanY = oy + ((t % 3.2) / 3.2) * (floorY - oy + 40) - 20;
    // interferência: a cada ~5 s, 180 ms de linhas deslocadas
    const glitchOn = !REDUCED && (t % 5.3) < 0.18;
    const jitter = glitchOn ? gy => (Math.sin(gy * 1.7 + t * 90) > 0.6 ? (Math.sin(gy + t * 50) * 6) : 0) : null;

    // reflexo no chão
    drawCloud(f.body, "143,143,143", 0.10 * flicker, t, scanY, true, null);
    drawCloud(f.legs, "62,207,142", 0.16 * flicker, t, scanY, true, null);
    // corpo (cinza) e patas (verde)
    drawCloud(f.body, "150,150,150", 0.42 * flicker, t, scanY, false, jitter);
    drawCloud(f.legs, "62,207,142", 0.95 * flicker, t, scanY, false, jitter);
    // brilho aditivo nas patas: pontos numa camada à parte, desfocada uma vez só por quadro
    gctx.setTransform(1, 0, 0, 1, 0, 0);
    gctx.clearRect(0, 0, glow.width, glow.height);
    gctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    gctx.fillStyle = "rgba(62,207,142,0.9)";
    for (const i of f.legs) gctx.fillRect(ox + (i % GW) * cell, oy + ((i / GW) | 0) * cell, dot, dot);
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = 0.35 * flicker; ctx.filter = `blur(${4 * dpr}px)`;
    ctx.drawImage(glow, 0, 0);
    ctx.restore();

    // linha de varredura
    if (!REDUCED) {
      const g = ctx.createLinearGradient(0, scanY - 14, 0, scanY + 14);
      g.addColorStop(0, "rgba(62,207,142,0)"); g.addColorStop(0.5, "rgba(62,207,142,0.18)"); g.addColorStop(1, "rgba(62,207,142,0)");
      ctx.fillStyle = g; ctx.fillRect(ox - 20, scanY - 14, GW * cell + 40, 28);
      ctx.fillStyle = "rgba(110,231,183,0.55)"; ctx.fillRect(ox - 20, scanY, GW * cell + 40, 1);
    }
    // linhas de TV bem sutis por cima
    ctx.fillStyle = "rgba(0,0,0,0.12)";
    for (let y = 0; y < H; y += 3) ctx.fillRect(0, y, W, 1);
  }

  if (REDUCED) { draw(0); return; }
  let running = false, raf = 0;
  const loop = now => { draw(now); if (running) raf = requestAnimationFrame(loop); };
  new IntersectionObserver(([e]) => {
    running = e.isIntersecting; cancelAnimationFrame(raf);
    if (running) raf = requestAnimationFrame(loop);
  }).observe(canvas);
  draw(performance.now());
}

initHolo();

// ── Painel de análise: dispersão por fase + percentis ───────────────────────
// Dados de exemplo (semente fixa) em faixas coerentes com as análises reais da plataforma.
// Sem controles: a medida alterna sozinha (pausa com o mouse em cima).
const AN_PHASES = ["Largada", "Arrancada", "Corrida", "Frenagem"];
const AN_MEASURES = [
  { label: "Velocidade",            unit: "km/h", dec: 1, params: [[12, 5], [28, 6], [40, 3.5], [20, 6]] },
  { label: "Aceleração",            unit: "m/s²", dec: 2, params: [[0.8, .7], [3.4, 1.1], [0.2, .7], [-3.8, 1.4]], signed: true },
  { label: "Frequência de passada", unit: "Hz",   dec: 2, params: [[1.7, .12], [2.15, .12], [2.3, .08], [1.95, .15]] },
  { label: "Ângulo do carpo",       unit: "°",    dec: 0, params: [[150, 14], [132, 22], [128, 24], [140, 18]], max: 180 },
  { label: "Ângulo do jarrete",     unit: "°",    dec: 0, params: [[152, 10], [140, 16], [136, 18], [146, 14]], max: 180 },
];
const AN_N = 64, AN_OUT = 4;                       // pontos por fase + outliers
const AN_CYCLE_MS = 6000;
const PCT = [{ p: 95, color: "#F87171" }, { p: 75, color: "#F5B94B" }, { p: 50, color: "#A1A1A1" }];

function mulberry32(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function gauss(rnd) { let u = 0, v = 0; while (!u) u = rnd(); while (!v) v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
function percentile(sorted, p) { if (!sorted.length) return NaN; const k = (sorted.length - 1) * p / 100, f = Math.floor(k); return sorted[f] + (sorted[Math.min(f + 1, sorted.length - 1)] - sorted[f]) * (k - f); }

function initAnalytics() {
  const canvas = document.getElementById("an-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const tip = document.getElementById("an-tip"), title = document.getElementById("an-title");
  let mi = 0;                                        // medida atual

  // jitter horizontal fixo por ponto (a nuvem não "treme" ao trocar de medida)
  const jr = mulberry32(7);
  const jitter = Array.from({ length: 4 * (AN_N + AN_OUT) }, () => Math.max(-1, Math.min(1, gauss(jr) * 0.42)));

  function dataset(m, seed) {
    const rnd = mulberry32(seed * 977 + 131), pts = [];
    m.params.forEach(([mu, sd], g) => {
      for (let i = 0; i < AN_N; i++) pts.push({ g, v: mu + gauss(rnd) * sd, out: false });
      for (let i = 0; i < AN_OUT; i++) pts.push({ g, v: mu + (rnd() < 0.5 ? -1 : 1) * sd * (2.7 + rnd() * 0.8), out: true });
    });
    if (!m.signed) pts.forEach(p => { p.v = Math.max(m.dec ? 0.05 : 1, p.v); });
    if (m.max) pts.forEach(p => { p.v = Math.min(m.max, p.v); });   // articulação estendida = 180°
    return pts;
  }

  let W = 0, H = 0, dpr = 1;
  const pad = { l: 40, r: 8, t: 10, b: 30 };
  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
  }

  let pts = [], cur = [], target = [], lines = null, linesTarget = null, yTicks = [], anim = null, hover = -1;

  function compute() {
    const m = AN_MEASURES[mi];
    pts = dataset(m, mi + 1);
    const vals = pts.map(p => p.v);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1; lo -= span * 0.08; hi += span * 0.08;
    const y = v => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
    const colW = (W - pad.l - pad.r) / 4;
    target = pts.map((p, i) => ({ x: pad.l + colW * (p.g + 0.5) + jitter[i] * colW * 0.22, y: y(p.v) }));
    linesTarget = PCT.map(({ p }) => [0, 1, 2, 3].map(g => y(percentile(pts.filter(q => q.g === g).map(q => q.v).sort((a, b) => a - b), p))));
    yTicks = [0.15, 0.4, 0.65, 0.9].map(f => {
      const yy = pad.t + f * (H - pad.t - pad.b);
      return { y: yy, label: (lo + (1 - f) * (hi - lo)).toFixed(m.dec > 1 ? 1 : 0) };
    });
    title.textContent = `${m.label} · ${m.unit}`.toUpperCase();
  }

  function start(fromBottom) {
    const from = cur.length === target.length ? cur.map(c => ({ ...c })) : target.map(t => ({ x: t.x, y: fromBottom ? H - pad.b : t.y }));
    const lFrom = lines ? lines.map(r => r.slice()) : linesTarget.map(r => r.map(() => H - pad.b));
    const t0 = performance.now(), dur = REDUCED ? 1 : 750;
    anim = now => {
      const k = Math.min(1, (now - t0) / dur), e = k < .5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
      cur = target.map((t, i) => ({ x: from[i].x + (t.x - from[i].x) * e, y: from[i].y + (t.y - from[i].y) * e }));
      lines = linesTarget.map((r, j) => r.map((v, g) => lFrom[j][g] + (v - lFrom[j][g]) * e));
      draw();
      if (k < 1) requestAnimationFrame(anim); else anim = null;
    };
    requestAnimationFrame(anim);
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const colW = (W - pad.l - pad.r) / 4;
    // grade tracejada + valores do eixo
    ctx.setLineDash([2, 5]); ctx.strokeStyle = "rgba(255,255,255,0.09)"; ctx.lineWidth = 1;
    ctx.font = `500 10px "JetBrains Mono", monospace`; ctx.fillStyle = "#5E5E5E"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
    yTicks.forEach(t => { ctx.beginPath(); ctx.moveTo(pad.l, t.y); ctx.lineTo(W - pad.r, t.y); ctx.stroke(); ctx.fillText(t.label, pad.l - 8, t.y); });
    ctx.setLineDash([]);
    ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.beginPath(); ctx.moveTo(pad.l, H - pad.b); ctx.lineTo(W - pad.r, H - pad.b); ctx.stroke();
    ctx.fillStyle = "#707070"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic"; ctx.font = `500 12px Inter, sans-serif`;
    AN_PHASES.forEach((g, i) => ctx.fillText(g, pad.l + colW * (i + 0.5), H - 8));
    // pontos (mais claros no alto, como uma nuvem com profundidade)
    cur.forEach((c, i) => {
      const f = 1 - (c.y - pad.t) / (H - pad.t - pad.b);
      ctx.beginPath(); ctx.arc(c.x, c.y, i === hover ? 5 : 3.3, 0, Math.PI * 2);
      ctx.fillStyle = pts[i].out ? "rgba(110,231,183,0.35)" : `rgba(62,207,142,${(0.45 + 0.5 * f).toFixed(3)})`;
      ctx.fill();
      if (i === hover) { ctx.strokeStyle = "#FAFAFA"; ctx.lineWidth = 1.5; ctx.stroke(); }
    });
    // percentis em degraus com transição suave entre as fases
    if (lines) PCT.forEach((pc, j) => {
      const r = lines[j];
      ctx.strokeStyle = pc.color; ctx.lineWidth = 1.3; ctx.globalAlpha = 0.9;
      ctx.beginPath();
      for (let g = 0; g < 4; g++) {
        const x0 = g === 0 ? pad.l : pad.l + colW * g + colW * 0.14;
        const x1 = g === 3 ? W - pad.r : pad.l + colW * (g + 1) - colW * 0.14;
        if (g === 0) ctx.moveTo(x0, r[g]); else ctx.lineTo(x0, r[g]);
        ctx.lineTo(x1, r[g]);
        if (g < 3) { const xm = x1 + colW * 0.14; ctx.bezierCurveTo(xm, r[g], xm, r[g + 1], x1 + colW * 0.28, r[g + 1]); }
      }
      ctx.stroke(); ctx.globalAlpha = 1;
    });
  }

  // dica ao passar o mouse
  let hovering = false;
  canvas.addEventListener("mousemove", e => {
    hovering = true;
    const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = -1, bd = 100;
    cur.forEach((c, i) => { const d = (c.x - mx) ** 2 + (c.y - my) ** 2; if (d < bd) { bd = d; best = i; } });
    if (best !== hover) { hover = best; if (!anim) draw(); }
    if (best < 0) { tip.hidden = true; return; }
    const m = AN_MEASURES[mi], p = pts[best], unit = m.unit === "°" ? "°" : ` ${m.unit}`;
    tip.innerHTML = `<b>${p.v.toFixed(m.dec).replace(".", ",")}${unit}</b> · ${AN_PHASES[p.g]}${p.out ? " · outlier" : ""}`;
    tip.style.left = `${cur[best].x + 8}px`; tip.style.top = `${cur[best].y}px`;
    tip.hidden = false;
  });
  canvas.addEventListener("mouseleave", () => { hovering = false; hover = -1; tip.hidden = true; if (!anim) draw(); });
  window.addEventListener("resize", () => { resize(); compute(); cur = target.map(t => ({ ...t })); lines = linesTarget; draw(); });

  // entra animado quando aparece e alterna a medida sozinho enquanto visível
  let started = false, visible = false;
  new IntersectionObserver(([e]) => {
    visible = e.isIntersecting;
    if (visible && !started) { started = true; resize(); compute(); start(true); }
  }, { threshold: 0.2 }).observe(canvas);
  if (!REDUCED) setInterval(() => {
    if (!visible || hovering || anim) return;
    mi = (mi + 1) % AN_MEASURES.length;
    compute(); start(false);
  }, AN_CYCLE_MS);
}

initAnalytics();