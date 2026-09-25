/* ============================================
   PUXA.AI — Análise em modo terminal
   Mesmo backend de analisar.html (/upload, /status, /download)
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {

  // === CONFIG ===
  const API_BASE = window.location.hostname === "localhost"
    ? "http://localhost:5000"
    : "https://gibraltar-slope-bacteria-thereby.trycloudflare.com";

  const MAX_FILE_BYTES = 100 * 1024 * 1024; // 100 MB — igual ao backend
  const TIMEOUT_MS     = 25 * 60 * 1000; // biomecânica (pose) pode levar alguns minutos
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // === DOM ===
  const term      = document.getElementById("term");
  const out       = document.getElementById("out");
  const fileInput = document.getElementById("fileInput");

  let busy        = false;
  let promptLine  = null;
  let charts      = [];
  let currentFile = null;   // vídeo original, reaproveitado no player com esqueleto

  // === HELPERS ===
  const sleep = ms => new Promise(r => setTimeout(r, REDUCED_MOTION ? 0 : ms));

  const esc = s => String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function scrollDown() { out.scrollTop = out.scrollHeight; }

  function line(html = "", cls = "") {
    const el = document.createElement("span");
    el.className = `ln in ${cls}`.trim();
    el.innerHTML = html;
    out.appendChild(el);
    scrollDown();
    return el;
  }

  function block(el) {
    out.appendChild(el);
    scrollDown();
    return el;
  }

  function formatSize(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024, sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  }

  function asciiBar(ratio, width = 24) {
    const r = Math.max(0, Math.min(1, ratio || 0));
    const full = Math.round(r * width);
    return `<span class="bar-fill">${"█".repeat(full)}</span><span class="bar-empty">${"░".repeat(width - full)}</span>`;
  }

  const ok   = msg => `<span class="c-green">[ ok ]</span> ${msg}`;
  const info = msg => `<span class="c-blue">[ .. ]</span> ${msg}`;
  const warn = msg => `<span class="c-amber">[warn]</span> ${msg}`;
  const fail = msg => `<span class="c-red">[erro]</span> ${msg}`;

  const PROMPT = `<span class="prompt-user">guest@puxa</span><span class="c-dim">:</span><span class="prompt-path">~/analise</span><span class="c-dim">$</span> `;

  function section(title) {
    const pad = Math.max(4, 58 - title.length);
    line("");
    line(`<span class="c-dim">──</span> <span class="c-accent b">${esc(title)}</span> <span class="c-dim">${"─".repeat(pad)}</span>`);
  }

  async function typeCommand(el, text) {
    el.innerHTML = PROMPT;
    const span = document.createElement("span");
    el.appendChild(span);
    for (const ch of text) {
      span.textContent += ch;
      scrollDown();
      await sleep(14);
    }
  }

  function setStatus(txt) { document.title = `Puxa.ai Terminal · ${txt}`; }

  // === PROMPT ===
  function showPrompt() {
    busy = false;
    line("");
    line(`digite <button class="cmd" data-act="pick">puxa analyze --video</button> ou arraste um vídeo para esta janela  <span class="c-faint">(Enter · Ctrl+U)</span>`, "c-dim");
    promptLine = line(`${PROMPT}<span class="cursor"></span>`);
  }

  out.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn || busy) return;
    if (btn.dataset.act === "pick") fileInput.click();
  });

  // === BOOT ===
  async function boot() {
    busy = true;
    line(`<span class="b">Puxa.ai Analysis Engine</span> <span class="c-dim">· telemetria de desempenho + biomecânica por vídeo</span>`);
    line(`<span class="c-dim">${new Date().toLocaleString("pt-BR")}</span>`);
    line("");

    const health = line(info("verificando servidor…"));
    const t0 = performance.now();
    let bioOn = false, online = false;
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (!res.ok) throw new Error(res.status);
      const ms = Math.round(performance.now() - t0);
      bioOn = !!(await res.json()).biomecanica;
      online = true;
      health.innerHTML = ok(`servidor online <span class="c-dim">(${ms} ms)</span>`);
      setStatus("online");
    } catch {
      health.innerHTML = fail("servidor inacessível — a análise não vai funcionar agora");
      setStatus("offline");
    }
    await sleep(120);
    line(ok(`tracking <span class="c-accent">yolov8n</span> <span class="c-dim">· detecta e trava no cavalo · velocidade, aceleração, distância</span>`));
    await sleep(120);
    if (bioOn) {
      line(ok(`pose <span class="c-accent">superanimal-quadruped</span> <span class="c-dim">· 39 pontos do corpo · esqueleto ao vivo</span>`));
      await sleep(120);
      line(ok(`biomecânica <span class="c-dim">· passada · mão de galope · ângulos de carpo e jarrete · pescoço</span>`));
    } else if (online) {
      line(warn(`pose <span class="c-dim">· módulo de biomecânica desativado neste servidor (BIO_PYTHON)</span>`));
    }
    await sleep(120);
    line(ok(`pista <span class="c-dim">· padrão ABVAQ 160 m (tolerância · corrida · faixa · desaceleração)</span>`));
    await sleep(120);
    line(ok(`formatos <span class="c-dim">· mp4 mov avi mkv · limite 100 MB</span>`));
    if (bioOn) line(`       <span class="c-faint">recomendado: câmera lateral fixa, 60 fps ou mais, clipe de até 30 s</span>`);
    showPrompt();
  }

  // === ENTRADA DE ARQUIVO ===
  async function handleFile(file) {
    if (busy || !file) return;
    busy = true;

    if (promptLine) await typeCommand(promptLine, `puxa analyze --video "${file.name}"`);

    if (!file.type.startsWith("video/")) {
      line(fail(`formato inválido: ${esc(file.type || "desconhecido")} — envie MP4, MOV, AVI ou MKV`));
      return showPrompt();
    }
    if (file.size > MAX_FILE_BYTES) {
      line(fail(`arquivo com ${formatSize(file.size)} — o limite é 100 MB. Comprima ou corte o vídeo.`));
      return showPrompt();
    }

    line(info(`arquivo <span class="c-accent">${esc(file.name)}</span> <span class="c-dim">(${formatSize(file.size)})</span>`));
    currentFile = file;
    startUpload(file);
  }

  // === UPLOAD ===
  function startUpload(file) {
    setStatus("enviando");
    const formData = new FormData();
    formData.append("video", file);
    formData.append("mode", "performance");

    const prog = line(`upload   ${asciiBar(0)}   0%`);
    const xhr  = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/upload`, true);

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const r = e.loaded / e.total;
      prog.innerHTML = `upload   ${asciiBar(r)} ${String(Math.floor(r * 100)).padStart(3)}%  <span class="c-dim">${formatSize(e.loaded)} / ${formatSize(e.total)}</span>`;
    };

    xhr.onload = () => {
      if (xhr.status === 202) {
        try {
          const resp = JSON.parse(xhr.responseText);
          if (!resp.job_id) throw new Error("sem job_id");
          line(ok(`upload concluído · job <span class="c-violet">${esc(resp.job_id.slice(0, 8))}</span>`));
          monitor(resp.job_id);
        } catch {
          finishWithError("resposta inválida do servidor");
        }
      } else {
        let detail = "";
        try { detail = JSON.parse(xhr.responseText).error || ""; } catch {}
        finishWithError(`HTTP ${xhr.status}${detail ? " — " + esc(detail) : ""}`);
      }
    };
    xhr.onerror = () => finishWithError("falha de conexão com o servidor");
    xhr.send(formData);
  }

  // === ACOMPANHAMENTO DO JOB ===
  const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

  function monitor(jobId) {
    setStatus("processando");
    const startedAt = Date.now();
    const prog = line(`análise  ${asciiBar(0)}   0%`);
    const live = line("");
    let spinI = 0, lastMsg = "", lastPct = 0, netErrors = 0;
    let bioProg = null, liveView = null;

    const spinTimer = setInterval(() => {
      const el = live.querySelector(".spin");
      if (el) el.textContent = SPIN[spinI++ % SPIN.length];
    }, 90);

    const stop = () => { clearInterval(poll); clearInterval(spinTimer); if (liveView) liveView.stop(); };

    const poll = setInterval(async () => {
      if (Date.now() - startedAt > TIMEOUT_MS) {
        stop();
        live.remove();
        return finishWithError("tempo limite excedido (25 min)");
      }
      try {
        const res = await fetch(`${API_BASE}/status/${jobId}`);
        if (!res.ok) return;
        netErrors = 0;
        const data = await res.json();

        // Biomecânica: barra própria + prévia ao vivo do esqueleto
        const isBio = /Biomec/i.test(data.message || "");
        if (isBio && data.live && !liveView) {
          lastPct = 100;
          prog.innerHTML = `análise  ${asciiBar(1)} 100%`;
          bioProg = document.createElement("span");
          bioProg.className = "ln in";
          bioProg.innerHTML = `pose     ${asciiBar(0)}   0%`;
          live.insertAdjacentElement("afterend", bioProg);
          liveView = startLiveView(`${API_BASE}${data.live}`, bioProg);
        }

        if (data.message && data.message !== lastMsg) {
          const msg = data.message.replace(/^IA:\s*/, "");
          const m = msg.match(/(\d+)%/);
          if (isBio && bioProg && m) {
            const p = parseInt(m[1], 10);
            bioProg.innerHTML = `pose     ${asciiBar(p / 100)} ${String(p).padStart(3)}%`;
          } else if (m) lastPct = Math.max(lastPct, parseInt(m[1], 10));
          // Mensagens de etapa viram linhas de log; as de frame só atualizam a linha viva
          if (lastMsg && !/frame/i.test(lastMsg)) {
            live.insertAdjacentHTML("beforebegin", `<span class="ln in">${ok(esc(lastMsg.replace(/^IA:\s*/, "")))}</span>`);
          }
          live.innerHTML = `<span class="spin c-accent">${SPIN[0]}</span> ${esc(msg)}`;
          prog.innerHTML = `análise  ${asciiBar(lastPct / 100)} ${String(lastPct).padStart(3)}%`;
          lastMsg = data.message;
          scrollDown();
        }

        if (data.status === "completed") {
          stop();
          const secs = ((Date.now() - startedAt) / 1000).toFixed(1);
          prog.innerHTML = `análise  ${asciiBar(1)} 100%`;
          live.innerHTML = ok(`processamento concluído em <span class="c-accent">${secs}s</span>`);
          if (bioProg) bioProg.innerHTML = `pose     ${asciiBar(1)} 100%`;
          setStatus("concluído");
          renderResult(data);
        } else if (data.status === "error") {
          stop();
          live.remove();
          finishWithError(esc((data.message || "erro no processamento").replace(/^IA:\s*/, "")));
        }
      } catch {
        if (++netErrors >= 5) {
          stop();
          live.remove();
          finishWithError("servidor inacessível");
        }
      }
    }, 1000);
  }

  // Prévia ao vivo: recarrega o último frame processado (live.jpg) em sequência
  function startLiveView(url, after) {
    const wrap = document.createElement("div");
    wrap.className = "live";
    wrap.innerHTML = `<div class="live-head"><span class="rec"></span> pose ao vivo · esqueleto sendo calculado frame a frame</div><img alt="Frame atual da análise de pose com o esqueleto do cavalo">`;
    after.insertAdjacentElement("afterend", wrap);
    const img = wrap.querySelector("img");
    let running = true;
    const next = () => {
      if (!running) return;
      const probe = new Image();
      probe.onload  = () => { img.src = probe.src; wrap.classList.add("on"); scrollDown(); setTimeout(next, 120); };
      probe.onerror = () => setTimeout(next, 400);
      probe.src = `${url}?t=${Date.now()}`;
    };
    next();
    return { stop() { running = false; wrap.classList.add("done"); } };
  }

  function finishWithError(msg) {
    setStatus("erro");
    line(fail(msg));
    showPrompt();
  }

  // === RESULTADO ===
  // Linha de métrica no mesmo padrão do boot: [ ok ] rótulo · detalhe · detalhe
  const num = (v, d = 1) => (v == null || isNaN(v) ? "—" : Number(v).toFixed(d));
  const val = (v, unit = "", d = 1) =>
    `<span class="metric-val">${num(v, d)}${!unit ? "" : /^[°%]/.test(unit) ? unit : " " + unit}</span>`;
  function stat(tag, label, parts) {
    const detail = parts.filter(Boolean).map(p => `<span class="c-dim">·</span> ${p}`).join(" ");
    return tag(`<span class="b">${label}</span> <span class="c-dim">${detail}</span>`);
  }

  function stripTags(html) {
    const d = document.createElement("div");
    d.innerHTML = html || "";
    return d.textContent || "";
  }

  function highlightJSON(obj) {
    return esc(JSON.stringify(obj, null, 2))
      .replace(/(&quot;[^&]*?&quot;)(\s*:)/g, '<span class="j-key">$1</span>$2')
      .replace(/:\s(&quot;.*?&quot;)/g, ': <span class="j-str">$1</span>')
      .replace(/:\s(-?\d+(?:\.\d+)?)/g, ': <span class="j-num">$1</span>')
      .replace(/:\s(true|false)/g, ': <span class="j-bool">$1</span>')
      .replace(/:\s(null)/g, ': <span class="j-null">$1</span>');
  }

  async function renderResult(data) {
    const r  = data.result || {};
    const dl = data.downloads || {};

    await sleep(200);
    section("resultado");
    line(stat(ok, "velocidade", [`máx ${val(r.max_speed, "km/h")}`, `média ${val(r.avg_speed, "km/h")}`, `pico aos ${val(r.time_to_max_speed, "s")}`]));
    line(stat(ok, "distância", [val(r.distance, "m"), `tempo de prova ${val(r.run_time_s, "s")}`]));
    line(stat(ok, "aceleração", [`máx ${val(r.max_accel, "m/s²", 2)}`, `impulsão ${val(r.impulse_m_s2, "m/s²", 2)}`,
      r.max_decel != null ? `frenagem máx ${val(r.max_decel, "m/s²", 2)}` : null, `eficiência ${val(r.efficiency_percent, "%")}`]));

    // Fases detectadas pela própria curva de velocidade (a pista não tem comprimento fixo no regulamento)
    (r.fases || []).forEach(f => {
      line(stat(ok, `fase ${f.fase}`, [
        `a partir de ${val(f.inicio_s, "s")}`, `${val(f.duracao_s, "s")}`, `${val(f.distancia_m, "m")}`,
        f.vel_media_kmh != null ? `média ${val(f.vel_media_kmh, "km/h")}` : null,
      ]));
    });

    // Qualidade da medição
    const qm = r.qualidade;
    if (qm) {
      const good = qm.velocidade_medida_pct >= 80;
      line(stat(good ? ok : warn, "medição", [
        `cavalo rastreado em ${val(qm.frames_rastreados_pct, "%")} dos frames`,
        `velocidade medida em ${val(qm.velocidade_medida_pct, "%")} da corrida`,
        qm.cortes_de_cena ? `${qm.cortes_de_cena} corte(s) de câmera tratados` : null,
        "câmera compensada (panorâmica/zoom)",
      ]));
      line(`       <span class="c-faint">régua: ${esc(qm.regua || "")}</span>`);
    }

    // Vídeo em câmera lenta (detectado pelo ciclo das patas): velocidades acima estão no tempo do vídeo
    const slow = r.biomecanica?.passada?.fator_camera_lenta;
    if (slow) {
      line(stat(warn, "câmera lenta", [
        `ciclo das patas indica vídeo ~${num(slow)}× mais lento que o real`,
        `em tempo real ≈ máx ${val(r.max_speed * slow, "km/h")} · média ${val(r.avg_speed * slow, "km/h")}`,
      ]));
    }

    // Dados brutos
    section("analise.json");
    line(`${PROMPT}cat analise.json`);
    const { output_dir, ai_analysis, fases, qualidade, biomecanica, biomecanica_erro, ...pub } = r;
    const pre = document.createElement("span");
    pre.className = "ln in";
    pre.innerHTML = highlightJSON(pub);
    block(pre);

    // Resumo em texto
    if (ai_analysis) {
      section("resumo");
      line(stripTags(ai_analysis));
    }

    // Gráficos + métricas derivadas do CSV
    if (dl.metrics_csv) {
      try {
        const csv = await (await fetch(`${API_BASE}${dl.metrics_csv}`)).text();
        renderSeries(csv);
      } catch {
        line(warn("não foi possível carregar metrics.csv para os gráficos"));
      }
    }

    // Biomecânica (pose)
    if (biomecanica) {
      renderBio(biomecanica);
      if (dl.bio_keypoints && currentFile) await renderSkeletonPlayer(`${API_BASE}${dl.bio_keypoints}`, currentFile, biomecanica);
    }
    else if (biomecanica_erro) {
      section("biomecânica");
      line(warn(`módulo de pose falhou: ${esc(biomecanica_erro)}`));
    }

    // Arquivos gerados
    section("saída");
    line(`${PROMPT}ls ./saida`);
    const files = [
      ["video",         "resultado.mp4",          "vídeo com tracking e HUD"],
      ["bio_video",     "bio/biomecanica.mp4",    "esqueleto em câmera lenta (0.5x)"],
      ["report_pdf",    "performance_report.pdf", "relatório"],
      ["graph_png",     "performance_report.png", "gráfico"],
      ["bio_keypoints", "bio/keypoints.csv",      "39 pontos do corpo por frame"],
    ];
    files.filter(([k]) => dl[k]).forEach(([k, name, desc]) => {
      line(`  <a class="cmd" href="${API_BASE}${dl[k]}" download target="_blank" rel="noopener">${name}</a>  <span class="c-dim"># ${desc}</span>`);
    });

    line("");
    line(`nova análise: <button class="cmd" data-act="pick">puxa analyze --video</button>`, "c-dim");
    busy = false;
    promptLine = line(`${PROMPT}<span class="cursor"></span>`);
  }

  // === BIOMECÂNICA (bio.json) ===
  function renderBio(b) {
    const q = b.qualidade || {};
    section("biomecânica · pose 39 pontos");
    line(`${PROMPT}puxa bio --pose superanimal-quadruped`);
    line(stat(ok, "pose", [
      `cavalo em ${val(q.frames_com_cavalo_pct, "%")} dos frames`,
      `de perfil em ${val(q.frames_de_perfil_pct, "%")} (só esses entram nas métricas)`,
      `confiança ${val(q.confianca_media, "", 2)}`,
      `lado da câmera ${esc(q.lado_da_camera || "—")}`,
    ]));

    // Passada
    const p = b.passada;
    if (p) {
      const [lo, hi] = p.referencia_hz?.faixa || [0, 0];
      const pos = p.frequencia_hz < lo ? "abaixo da" : p.frequencia_hz > hi ? "acima da" : "dentro da";
      const slowF = p.fator_camera_lenta;
      line(stat(slowF ? warn : ok, "passada", [
        slowF ? `${val(p.frequencia_hz, "Hz", 2)} no vídeo · ≈ ${val(p.frequencia_hz * slowF, "Hz", 2)} em tempo real` : val(p.frequencia_hz, "Hz", 2),
        `ciclo ${val(p.duracao_media_s, "s", 3)}`,
        `${p.n_passadas} passadas`,
        `regularidade ${val(p.regularidade_ciclo, "", 2)}`,
        p.comprimento_m != null ? `comprimento ~${val(p.comprimento_m, "m", 2)}` : null,
        slowF ? null : `${pos} faixa de PSI (${lo}–${hi} Hz)`,
      ]));
      if (p.alerta) line(`       <span class="c-amber">${esc(p.alerta)}</span>`);
    } else {
      line(stat(warn, "passada", ["poucas passadas identificáveis neste vídeo"]));
    }

    // Mão de galope
    const m = b.mao_de_galope || {};
    const leadTxt = (label, s) => !s ? `${label} sem leitura`
      : `${label} <span class="metric-val">${esc(s.predominante)}</span> (${Math.round(s.consistencia * 100)}% de ${s.n}${s.trocas_s.length ? `, trocas ${s.trocas_s.map(t => t.toFixed(1) + "s").join(" ")}` : ""})`;
    const leadConclusive = [m.anteriores, m.posteriores].every(s => s && s.predominante !== "inconclusiva");
    line(stat(leadConclusive ? ok : warn, "mão de galope", [
      leadTxt("anteriores", m.anteriores),
      leadTxt("posteriores", m.posteriores),
      m.galope ? `galope <span class="metric-val">${m.galope}</span>` : null,
    ]));

    // Ângulos (lado da câmera primeiro)
    const ang = b.angulos_graus || {};
    Object.keys(ang).sort((a, c) => (ang[c].lado_da_camera - ang[a].lado_da_camera)).forEach(k => {
      const a = ang[k];
      line(stat(a.lado_da_camera ? ok : warn, k.replace("_", " "), [
        `${num(a.min_p5, 0)}° → ${num(a.max_p95, 0)}°`,
        `amplitude ${val(a.amplitude, "°", 0)}`,
        a.lado_da_camera ? "lado da câmera" : "lado oposto, menos confiável",
      ]));
    });
    const tr = b.tronco_graus, nk = b.pescoco_graus;
    if (tr) line(stat(ok, "tronco", [`inclinação média ${val(tr.media, "°")}`, `${num(tr.min_p5, 0)}° a ${num(tr.max_p95, 0)}°`]));
    if (nk) line(stat(ok, "pescoço", [`ângulo médio ${val(nk.media, "°")}`, `${num(nk.min_p5, 0)}° a ${num(nk.max_p95, 0)}°`]));
    line(`       <span class="c-faint">ângulos em 2D · valem com a câmera perpendicular à pista · referência de passada: ${esc(p?.referencia_hz?.fonte || "Witte et al. 2006")}</span>`);

    // Gráficos
    const s = b.series || {};
    const angKeys = Object.keys(s).filter(k => k.startsWith("angulo_"));
    const protKeys = Object.keys(s).filter(k => k.startsWith("protracao_"));
    if (s.t_s && (angKeys.length || protKeys.length)) {
      line("");
      line(`${PROMPT}puxa plot protracao angulos`);
      const grid = document.createElement("div");
      grid.className = "plots";
      grid.innerHTML = `
        <div class="plot"><div class="plot-title">protração das patas · × comprimento do corpo · tempo (s)</div><canvas id="bProt"></canvas></div>
        <div class="plot"><div class="plot-title">ângulos articulares (lado da câmera) · graus · tempo (s)</div><canvas id="bAng"></canvas></div>`;
      block(grid);

      const mono = "'JetBrains Mono', monospace";
      const axis = { ticks: { color: "#707070", font: { family: mono, size: 10 }, maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,0.05)" }, border: { color: "#2E2E2E" } };
      const opts = {
        responsive: true, maintainAspectRatio: false, spanGaps: false,
        animation: { duration: REDUCED_MOTION ? 0 : 500 },
        plugins: { legend: { display: true, labels: { color: "#A1A1A1", boxWidth: 10, font: { family: mono, size: 10 } } },
                   tooltip: { titleFont: { family: mono }, bodyFont: { family: mono }, backgroundColor: "#1C1C1C", borderColor: "#2E2E2E", borderWidth: 1 } },
        scales: { x: axis, y: axis },
        elements: { point: { radius: 0 } },
      };
      const colors = { anterior_esquerdo: "#3ECF8E", anterior_direito: "#EDEDED", posterior_esquerdo: "#6EE7B7", posterior_direito: "#8F8F8F" };   // esquerdo = verdes, direito = neutros
      const labels = s.t_s.map(t => t.toFixed(2));
      charts.push(new Chart(document.getElementById("bProt"), {
        type: "line",
        data: { labels, datasets: protKeys.map(k => {
          const limb = k.replace("protracao_", "");
          return { label: limb.replace("_", " "), data: s[k], borderColor: colors[limb], borderWidth: 1.3, tension: 0.3 };
        }) },
        options: opts,
      }));
      charts.push(new Chart(document.getElementById("bAng"), {
        type: "line",
        data: { labels, datasets: angKeys.map((k, i) => ({
          label: k.replace("angulo_", "").replace("_", " "), data: s[k],
          borderColor: i === 0 ? "#3ECF8E" : "#EDEDED", borderWidth: 1.3, tension: 0.3,
        })) },
        options: opts,
      }));
      scrollDown();
    }

    line(`       <span class="c-faint">${esc(b.modelo || "")} · protótipo</span>`);
  }

  // === PLAYER: vídeo original + esqueleto desenhado em tempo real ===
  const SKELETON = [
    ["nose", "neck_end"], ["neck_end", "neck_base"], ["neck_base", "back_base"],
    ["back_base", "back_middle"], ["back_middle", "back_end"], ["back_end", "tail_base"], ["tail_base", "tail_end"],
    ["neck_base", "front_left_thai"],  ["front_left_thai", "front_left_knee"],   ["front_left_knee", "front_left_paw"],
    ["neck_base", "front_right_thai"], ["front_right_thai", "front_right_knee"], ["front_right_knee", "front_right_paw"],
    ["back_end", "back_left_thai"],    ["back_left_thai", "back_left_knee"],     ["back_left_knee", "back_left_paw"],
    ["back_end", "back_right_thai"],   ["back_right_thai", "back_right_knee"],   ["back_right_knee", "back_right_paw"],
  ];
  const LIMB_RGB = { front_left: "#3ECF8E", front_right: "#EDEDED", back_left: "#6EE7B7", back_right: "#8F8F8F" };   // esquerdo = verdes, direito = neutros
  const SKIP_DOTS = /antler|ear|mouth/;
  const MIN_P = 0.5;

  function parseKeypoints(csv) {
    const rows = csv.trim().split("\n");
    const head = rows[0].split(",");
    const parts = [...new Set(head.filter(h => h.endsWith("_x")).map(h => h.slice(0, -2)))];
    const col = Object.fromEntries(head.map((h, i) => [h, i]));
    const frames = rows.slice(1).map(r => {
      const c = r.split(",");
      const pts = {};
      for (const p of parts) {
        const x = parseFloat(c[col[p + "_x"]]), y = parseFloat(c[col[p + "_y"]]), pr = parseFloat(c[col[p + "_p"]]);
        if (!isNaN(x) && !isNaN(y) && !(pr < MIN_P)) pts[p] = [x, y];
      }
      return pts;
    });
    return frames;
  }

  function angleAt(a, b, c) {
    const v1 = [a[0] - b[0], a[1] - b[1]], v2 = [c[0] - b[0], c[1] - b[1]];
    const cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (Math.hypot(...v1) * Math.hypot(...v2));
    return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
  }

  async function renderSkeletonPlayer(kpUrl, file, bio) {
    let frames;
    try {
      frames = parseKeypoints(await (await fetch(kpUrl)).text());
    } catch {
      line(warn("não foi possível carregar keypoints.csv para o player"));
      return;
    }
    const fps = bio.fps || 30;
    const near = bio.qualidade?.lado_da_camera === "esquerdo" ? "left" : "right";
    const leads = (bio.mao_de_galope?.passadas || []);
    const leadOk = bio.mao_de_galope?.anteriores?.predominante && bio.mao_de_galope.anteriores.predominante !== "inconclusiva";

    line("");
    line(`${PROMPT}puxa bio --play`);
    const wrap = document.createElement("div");
    wrap.className = "player";
    wrap.innerHTML = `
      <div class="player-stage">
        <video playsinline muted loop preload="auto"></video>
        <canvas></canvas>
      </div>
      <div class="player-bar">
        <button class="cmd" data-rate="0.25">0.25x</button>
        <button class="cmd" data-rate="0.5">0.5x</button>
        <button class="cmd" data-rate="1">1x</button>
        <button class="cmd" data-toggle>pausar</button>
        <span class="player-hud"></span>
      </div>`;
    block(wrap);

    const video  = wrap.querySelector("video");
    const canvas = wrap.querySelector("canvas");
    const hud    = wrap.querySelector(".player-hud");
    const ctx    = canvas.getContext("2d");
    video.src = URL.createObjectURL(file);
    video.playbackRate = 0.5;

    wrap.querySelectorAll("[data-rate]").forEach(b => b.addEventListener("click", () => { video.playbackRate = parseFloat(b.dataset.rate); }));
    const toggle = wrap.querySelector("[data-toggle]");
    toggle.addEventListener("click", () => { video.paused ? video.play() : video.pause(); });
    video.addEventListener("play",  () => { toggle.textContent = "pausar"; });
    video.addEventListener("pause", () => { toggle.textContent = "continuar"; });

    const draw = (mediaTime) => {
      const w = video.clientWidth, h = video.clientHeight;
      if (!video.videoWidth || !w) return;
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      const s = (w / video.videoWidth) * dpr;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const f = Math.min(frames.length - 1, Math.max(0, Math.round(mediaTime * fps)));
      const pts = frames[f] || {};
      ctx.lineCap = "round";
      const segs = SKELETON.filter(([a, b]) => pts[a] && pts[b]);
      const seg = ([a, b]) => { ctx.beginPath(); ctx.moveTo(pts[a][0] * s, pts[a][1] * s); ctx.lineTo(pts[b][0] * s, pts[b][1] * s); ctx.stroke(); };
      // contorno escuro por baixo: o esqueleto fica legível sobre cavalo claro ou escuro
      ctx.lineWidth = 5 * dpr; ctx.strokeStyle = "rgba(10,10,10,0.7)";
      segs.forEach(seg);
      ctx.lineWidth = 2.5 * dpr;
      for (const [a, b] of segs) {
        const limb = Object.keys(LIMB_RGB).find(k => a.startsWith(k) || b.startsWith(k));
        ctx.strokeStyle = limb ? LIMB_RGB[limb] : "#D0D0D0";
        seg([a, b]);
      }
      for (const [p, [x, y]] of Object.entries(pts)) {
        if (SKIP_DOTS.test(p)) continue;
        ctx.beginPath();
        ctx.arc(x * s, y * s, 3 * dpr, 0, Math.PI * 2);
        ctx.fillStyle = "#FAFAFA"; ctx.fill();
        ctx.lineWidth = 1.2 * dpr; ctx.strokeStyle = "rgba(10,10,10,0.8)"; ctx.stroke();
      }

      // HUD textual ao lado dos controles
      const t = f / fps;
      const knee = [`front_${near}_thai`, `front_${near}_knee`, `front_${near}_paw`];
      const hock = [`back_${near}_thai`, `back_${near}_knee`, `back_${near}_paw`];
      const carpo = knee.every(k => pts[k]) ? `${angleAt(...knee.map(k => pts[k])).toFixed(0)}°` : "—";
      const jarr  = hock.every(k => pts[k]) ? `${angleAt(...hock.map(k => pts[k])).toFixed(0)}°` : "—";
      let mao = "—";
      if (leadOk && leads.length) {
        const n = leads.reduce((best, x) => Math.abs(x.t_s - t) < Math.abs(best.t_s - t) ? x : best);
        if (Math.abs(n.t_s - t) < 0.6) mao = n.mao;
      }
      hud.innerHTML = `t ${t.toFixed(2)}s · frame ${f} · carpo <span class="metric-val">${carpo}</span> · jarrete <span class="metric-val">${jarr}</span> · mão <span class="metric-val">${esc(mao)}</span> · <span class="c-dim">${Object.keys(pts).length} pontos</span>`;
    };

    if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
      const loop = (_, meta) => { draw(meta.mediaTime); video.requestVideoFrameCallback(loop); };
      video.requestVideoFrameCallback(loop);
    } else {
      const loop = () => { draw(video.currentTime); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }
    video.addEventListener("seeked", () => draw(video.currentTime));
    window.addEventListener("resize", () => draw(video.currentTime));
    try { await video.play(); } catch { toggle.textContent = "continuar"; }
    scrollDown();
  }

  // === SÉRIES (metrics.csv) ===
  function renderSeries(csv) {
    const rows    = csv.trim().split("\n");
    const headers = rows[0].split(",").map(h => h.trim());
    const iTime   = headers.indexOf("tempo_s");
    const iSpeed  = headers.indexOf("speed_kmh");
    const iAccel  = headers.indexOf("accel_m_s2");

    const times = [], speeds = [], accels = [];
    for (let i = 1; i < rows.length; i++) {
      const cols = rows[i].split(",");
      const t = parseFloat(cols[iTime]);
      const s = parseFloat(cols[iSpeed]);
      const a = parseFloat(cols[iAccel]);
      if (!isNaN(t) && !isNaN(s)) {
        times.push(t.toFixed(2));
        speeds.push(s);
        accels.push(isNaN(a) ? 0 : a);
      }
    }
    const n = speeds.length;
    if (n < 2) {
      line(warn("poucos pontos em metrics.csv — gráficos omitidos"));
      return;
    }

    const smooth = (arr, w = 7) => arr.map((_, i) => {
      const slice = arr.slice(Math.max(0, i - w + 1), i + 1);
      return slice.reduce((a, b) => a + b, 0) / slice.length;
    });

    // Métricas derivadas (mesmas fórmulas de analisar.html)
    const mean  = speeds.reduce((a, b) => a + b, 0) / n;
    const std   = Math.sqrt(speeds.map(s => (s - mean) ** 2).reduce((a, b) => a + b, 0) / n);
    const regularity = Math.max(0, Math.min(100, 100 - (std / (mean || 1)) * 100));
    const maxSpeed   = Math.max(...speeds);
    const half  = Math.floor(n / 2);
    const avg1  = speeds.slice(0, half).reduce((a, b) => a + b, 0) / (half || 1);
    const avg2  = speeds.slice(half).reduce((a, b) => a + b, 0) / ((n - half) || 1);

    section("ritmo · metrics.csv");
    line(stat(ok, "ritmo", [`regularidade ${val(regularity, "/ 100")}`, `queda 1ª→2ª metade ${val(avg1 - avg2, "km/h")}`, `${n} amostras`]));

    // Gráficos
    section("séries temporais");
    line(`${PROMPT}puxa plot velocidade aceleracao`);
    const grid = document.createElement("div");
    grid.className = "plots";
    grid.innerHTML = `
      <div class="plot"><div class="plot-title">velocidade · km/h × tempo (s)</div><canvas id="tSpeed"></canvas></div>
      <div class="plot"><div class="plot-title">aceleração · m/s² × tempo (s)</div><canvas id="tAccel"></canvas></div>`;
    block(grid);

    const mono = "'JetBrains Mono', monospace";
    const axis = {
      ticks: { color: "#707070", font: { family: mono, size: 10 }, maxTicksLimit: 8 },
      grid:  { color: "rgba(255,255,255,0.05)" },
      border:{ color: "#2E2E2E" },
    };
    const opts = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: REDUCED_MOTION ? 0 : 500 },
      plugins: {
        legend: { display: false },
        tooltip: { titleFont: { family: mono }, bodyFont: { family: mono }, backgroundColor: "#1C1C1C", borderColor: "#2E2E2E", borderWidth: 1 },
      },
      scales: { x: axis, y: axis },
      elements: { point: { radius: 0 } },
    };

    charts.forEach(c => c.destroy());
    charts = [
      new Chart(document.getElementById("tSpeed"), {
        type: "line",
        data: { labels: times, datasets: [{ data: smooth(speeds), borderColor: "#3ECF8E", borderWidth: 1.5, tension: 0.3 }] },
        options: opts,
      }),
      new Chart(document.getElementById("tAccel"), {
        type: "line",
        data: { labels: times, datasets: [{ data: smooth(accels), borderColor: "#A1A1A1", borderWidth: 1.5, tension: 0.3 }] },
        options: opts,
      }),
    ];
    scrollDown();

    // Histograma em texto
    section("distribuição de velocidade");
    line(`${PROMPT}puxa hist velocidade --bin 5`);
    const bin = 5;
    const buckets = Math.max(1, Math.ceil(maxSpeed / bin));
    const counts = Array(buckets).fill(0);
    speeds.forEach(s => { counts[Math.min(Math.floor(s / bin), buckets - 1)]++; });
    const maxCount = Math.max(...counts);
    counts.forEach((c, i) => {
      const label = `${i * bin}–${(i + 1) * bin}`.padStart(7);
      const pct = ((c / n) * 100).toFixed(1).padStart(5);
      line(`  <span class="c-dim">${label} km/h</span>  ${asciiBar(c / maxCount, 30)} <span class="metric-val">${pct}%</span>`);
    });
  }

  // === DRAG & DROP ===
  let dragDepth = 0;
  term.addEventListener("dragenter", (e) => { e.preventDefault(); if (!busy) { dragDepth++; term.classList.add("dragging"); } });
  term.addEventListener("dragover",  (e) => { e.preventDefault(); });
  term.addEventListener("dragleave", (e) => { e.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; term.classList.remove("dragging"); } });
  term.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    term.classList.remove("dragging");
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (file) handleFile(file);
  });

  // === TECLADO ===
  document.addEventListener("keydown", (e) => {
    if (busy) return;
    const isPick = e.key === "Enter" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "u");
    if (isPick && !e.target.closest("a, button")) {
      e.preventDefault();
      fileInput.click();
    }
  });

  boot();
});
