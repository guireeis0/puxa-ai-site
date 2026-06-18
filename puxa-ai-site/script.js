/* ============================================
   PUXA.AI — Análise Biomecânica
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {

  // === CONFIG ===
  const API_BASE = window.location.hostname === "localhost"
    ? "http://localhost:5000"
    : "https://guireeis0-puxa-ai-var.hf.space";

  // === DOM ===
  const dropZone       = document.getElementById("dropZone");
  const fileInput      = document.getElementById("fileInput");
  const btnSelect      = document.getElementById("btnSelect");
  const toastContainer = document.getElementById("toastContainer");
  const btnNewAnalysis = document.getElementById("btnNewAnalysis");

  // Processamento
  const procFilename = document.getElementById("procFilename");
  const procFilesize = document.getElementById("procFilesize");
  const procMessage  = document.getElementById("procMessage");
  const procPct      = document.getElementById("procPct");
  const procBar      = document.getElementById("procBar");
  const procLog      = document.getElementById("procLog");
  const procFrames   = document.querySelector("[data-ia-frames]");

  // === INJECT ANIMATION KEYFRAMES ===
  if (!document.getElementById("puxa-ia-styles")) {
    const s = document.createElement("style");
    s.id = "puxa-ia-styles";
    s.textContent = `
      @keyframes puxa-blink {
        0%,100% { opacity:.2; transform:scale(.75); }
        50%      { opacity:1;  transform:scale(1);   }
      }
      @keyframes puxa-scan {
        from { left:-100%; }
        to   { left: 200%; }
      }
      @keyframes puxa-log-in {
        from { opacity:0; transform:translateY(5px); }
        to   { opacity:1; transform:translateY(0);   }
      }
      .puxa-dot {
        display:inline-block; width:5px; height:5px; border-radius:50%;
        animation:puxa-blink 1.2s ease-in-out infinite;
      }
      .puxa-dot:nth-child(2){animation-delay:.15s}
      .puxa-dot:nth-child(3){animation-delay:.30s}
      .puxa-dot:nth-child(4){animation-delay:.45s}
      .puxa-dot:nth-child(5){animation-delay:.60s}
      .puxa-scan-bar {
        position:absolute; top:0; left:-100%; width:100%; height:100%;
        background:linear-gradient(90deg,transparent,rgba(232,114,42,.3),transparent);
        animation:puxa-scan 2s linear infinite;
      }
      .puxa-log-line { animation:puxa-log-in .2s ease forwards; }
    `;
    document.head.appendChild(s);
  }

  // === HELPERS ===
  function formatSize(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024, sizes = ["B","KB","MB","GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  }

  // === STAGE CONTROL ===
  function showStage(name) {
    document.querySelectorAll(".stage").forEach(s => s.classList.remove("active"));
    document.getElementById("stage" + name).classList.add("active");
  }

  // === PROCESSING UI HELPERS ===
  function updatePct(pct) {
    if (procPct) procPct.textContent = pct + "%";
    if (procBar) procBar.style.width = pct + "%";
    _updateFrames(pct);
  }

  function _updateFrames(pct) {
    if (!procFrames) return;
    const frames = procFrames.querySelectorAll("[data-frame]");
    const done = Math.round((pct / 100) * frames.length);
    frames.forEach((f, i) => {
      if (i < done && !f.dataset.done) {
        f.dataset.done = "1";
        f.style.background = "rgba(232,114,42,0.18)";
        f.style.borderColor = "rgba(232,114,42,0.45)";
        const scan = f.querySelector(".puxa-scan-bar");
        if (scan) scan.style.display = "none";
      }
    });
  }

  function resetFrames() {
    if (!procFrames) return;
    procFrames.querySelectorAll("[data-frame]").forEach(f => {
      delete f.dataset.done;
      f.style.background = "";
      f.style.borderColor = "";
      const scan = f.querySelector(".puxa-scan-bar");
      if (scan) scan.style.display = "";
    });
  }

  function pushLog(text) {
    if (!procLog) return;
    const colors = ["#E8722A", "#9CA3AF", "#6B7280"];
    const line = document.createElement("span");
    line.className = "puxa-log-line";
    line.style.cssText = `
      font-family:'Space Mono',monospace; font-size:10px;
      color:${colors[procLog.children.length % colors.length]};
      white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block;`;
    line.textContent = text;
    procLog.appendChild(line);
    while (procLog.children.length > 3) procLog.removeChild(procLog.firstChild);
  }

  function resetProcessingUI(file) {
    if (procFilename) procFilename.textContent = file.name;
    if (procFilesize) procFilesize.textContent = formatSize(file.size);
    if (procMessage)  procMessage.textContent  = "IA: Iniciando...";
    if (procLog) procLog.innerHTML = `<span style="font-family:'Space Mono',monospace;font-size:10px;color:#4B5563;font-style:italic;">Aguardando servidor...</span>`;
    updatePct(0);
    resetFrames();
  }

  // === UPLOAD & PIPELINE ===
  const MAX_FILE_BYTES    = 100 * 1024 * 1024; // 100 MB — igual ao backend
  const MAX_DURATION_WARN = 120;               // 2 min — avisa mas não bloqueia

  function handleFile(file) {
    if (!file || !file.type.startsWith("video/")) {
      showToast("error", "Formato inválido", "Envie um arquivo de vídeo (MP4, MOV, AVI, MKV)");
      return;
    }

    if (file.size > MAX_FILE_BYTES) {
      showToast("error", "Arquivo muito grande", `O limite é 100 MB. O seu arquivo tem ${formatSize(file.size)}. Comprima ou corte o vídeo antes de enviar.`);
      return;
    }

    const tempVideo = document.createElement("video");
    tempVideo.preload = "metadata";
    const url = URL.createObjectURL(file);
    tempVideo.src = url;

    tempVideo.onloadedmetadata = () => {
      URL.revokeObjectURL(url);
      const dur = tempVideo.duration;
      if (dur > MAX_DURATION_WARN) {
        const m = Math.floor(dur / 60);
        const s = Math.round(dur % 60);
        showToast("info", "Vídeo longo detectado", `Este vídeo tem ${m}m ${s}s. O processamento pode demorar. Para melhores resultados, use clipes de até 2 minutos.`);
      }
      resetProcessingUI(file);
      showStage("Processing");
      startUpload(file);
    };

    tempVideo.onerror = () => {
      URL.revokeObjectURL(url);
      resetProcessingUI(file);
      showStage("Processing");
      startUpload(file);
    };
  }

  function startUpload(file) {
    const formData = new FormData();
    formData.append("video", file);
    formData.append("mode", "performance");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/upload`, true);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.floor((e.loaded / e.total) * 100);
        const msg = pct < 100 ? `IA: Subindo arquivo (${pct}%)` : "IA: Recebido! Aguardando servidor...";
        if (procMessage) procMessage.textContent = msg;
        updatePct(pct);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 202) {
        try {
          const resp = JSON.parse(xhr.responseText);
          if (resp.job_id) monitorarProcessamento(resp.job_id);
          else throw new Error("Job ID não retornado");
        } catch (err) {
          showError("Erro na resposta do servidor.");
        }
      } else {
        showError(`Erro ${xhr.status}: Falha no servidor.`);
      }
    };

    xhr.onerror = () => showError("Erro de conexão com o servidor.");
    xhr.send(formData);
  }

  function monitorarProcessamento(jobId) {
    // Reseta UI para a fase de processamento do servidor
    resetFrames();
    updatePct(0);
    if (procMessage) procMessage.textContent = "IA: Iniciando motores...";

    let lastPct = -1;
    let networkErrors = 0;
    const MAX_NETWORK_ERRORS = 5;
    const startedAt = Date.now();
    const TIMEOUT_MS = 10 * 60 * 1000;

    const interval = setInterval(async () => {
      if (Date.now() - startedAt > TIMEOUT_MS) {
        clearInterval(interval);
        showError("Tempo limite excedido.");
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/status/${jobId}`);
        if (!res.ok) return;
        networkErrors = 0;
        const data = await res.json();

        if (data.message) {
          if (procMessage) procMessage.textContent = data.message;
          const match = data.message.match(/(\d+)%/);
          const pct = match ? parseInt(match[1]) : lastPct;
          if (pct > lastPct) { updatePct(pct); lastPct = pct; }
          pushLog("› " + data.message);
        }

        if (data.status === "completed") {
          clearInterval(interval);
          showDashboard(data);
        } else if (data.status === "error") {
          clearInterval(interval);
          showError("Erro no processamento.");
        }
      } catch (err) {
        networkErrors++;
        if (networkErrors >= MAX_NETWORK_ERRORS) {
          clearInterval(interval);
          showError("Servidor inacessível.");
        }
      }
    }, 1000);
  }

  function showError(msg) {
    if (procMessage) procMessage.textContent = "IA: " + msg;
    showToast("error", "Erro", msg);
  }

  // === DASHBOARD ===
  let speedChart   = null;
  let accelChart   = null;
  let jerkChart    = null;
  let fatigueChart = null;
  let distChart    = null;
  let phasesChart  = null;

  function showDashboard(data) {
    const r  = data.result || {};
    const dl = data.downloads || {};

    document.getElementById("dashFilename").textContent     = procFilename ? procFilename.textContent : "—";
    document.getElementById("dashMaxSpeed").textContent     = r.max_speed         != null ? parseFloat(r.max_speed).toFixed(1)         : "—";
    document.getElementById("dashAvgSpeed").textContent     = r.avg_speed         != null ? parseFloat(r.avg_speed).toFixed(1)         : "—";
    document.getElementById("dashDistance").textContent     = r.distance          != null ? parseFloat(r.distance).toFixed(1)          : "—";
    document.getElementById("dashRunTime").textContent      = r.run_time_s        != null ? parseFloat(r.run_time_s).toFixed(1)        : "—";
    document.getElementById("dashMaxAccel").textContent     = r.max_accel         != null ? parseFloat(r.max_accel).toFixed(2)         : "—";
    document.getElementById("dashEfficiency").textContent   = r.efficiency_percent != null ? parseFloat(r.efficiency_percent).toFixed(1) : "—";
    document.getElementById("dashAiAnalysis").innerHTML     = r.ai_analysis || "Análise biomecânica concluída.";

    const dlMap = [
      { key: "report_pdf",  icon: "fa-file-pdf",   label: "Relatório PDF" },
      { key: "video",       icon: "fa-video",       label: "Vídeo Resultado" },
      { key: "graph_png",   icon: "fa-image",       label: "Gráfico PNG" },
      { key: "share_card",  icon: "fa-horse",       label: "Card Cavalo PNG" },
    ];
    const dlBtns = document.getElementById("dashDlBtns");
    dlBtns.innerHTML = dlMap.filter(d => dl[d.key]).map(d =>
      `<a class="dash-dl-btn" href="${API_BASE}${dl[d.key]}" download target="_blank">
         <i class="fas ${d.icon}"></i> ${d.label}
       </a>`
    ).join("");

    const metricsBtn = document.createElement('button');
    metricsBtn.className = 'dash-dl-btn';
    metricsBtn.style.cursor = 'pointer';
    metricsBtn.style.background = 'rgba(232,114,42,0.08)';
    metricsBtn.style.borderColor = 'rgba(232,114,42,0.3)';
    metricsBtn.style.color = '#E8722A';
    metricsBtn.innerHTML = '<i class="fas fa-share-alt"></i> Card Métricas PNG';
    metricsBtn.onclick = downloadMetricsCard;
    dlBtns.appendChild(metricsBtn);

    showStage("Dashboard");
    setTimeout(() => showFeedbackModal(), 13000);

    if (dl.metrics_csv) {
      fetch(`${API_BASE}${dl.metrics_csv}`)
        .then(res => res.text())
        .then(csv => {
          renderCharts(csv);
          renderHeatmap(csv, r.video_width, r.video_height);
        })
        .catch(() => {});
    }
  }

  function renderHeatmap(csv, videoWidth, videoHeight) {
    const canvas = document.getElementById("heatmapCanvas");
    if (!canvas) return;
    const rows    = csv.trim().split("\n");
    const headers = rows[0].split(",").map(h => h.trim());
    const iSpeed  = headers.indexOf("speed_kmh");
    const iCx     = headers.indexOf("cx");
    const iCy     = headers.indexOf("cy");
    if (iCx === -1 || iCy === -1) {
      const ctx2 = canvas.getContext("2d");
      canvas.width  = canvas.parentElement.clientWidth || 800;
      canvas.height = 160;
      ctx2.fillStyle = "rgba(10,20,40,0.85)";
      ctx2.fillRect(0, 0, canvas.width, canvas.height);
      ctx2.fillStyle = "#4B5563";
      ctx2.font = "13px 'Space Mono', monospace";
      ctx2.textAlign = "center";
      ctx2.fillText("Reinicie o servidor e processe um novo vídeo para ver o mapa de calor.", canvas.width / 2, canvas.height / 2);
      return;
    }
    const points = [];
    let maxSpeed = 0;
    for (let i = 1; i < rows.length; i++) {
      const cols = rows[i].split(",");
      const cx = parseFloat(cols[iCx]);
      const cy = parseFloat(cols[iCy]);
      const sp = parseFloat(cols[iSpeed]);
      if (!isNaN(cx) && !isNaN(cy) && !isNaN(sp)) {
        points.push({ cx, cy, sp });
        if (sp > maxSpeed) maxSpeed = sp;
      }
    }
    if (points.length === 0) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of points) {
      if (p.cx < minX) minX = p.cx;
      if (p.cx > maxX) maxX = p.cx;
      if (p.cy < minY) minY = p.cy;
      if (p.cy > maxY) maxY = p.cy;
    }
    const padX = (maxX - minX) * 0.08;
    const padY = (maxY - minY) * 0.08;
    minX -= padX; maxX += padX;
    minY -= padY; maxY += padY;
    const displayW = canvas.parentElement.clientWidth || 800;
    const displayH = Math.min(320, Math.round(displayW * 0.38));
    canvas.width  = displayW;
    canvas.height = displayH;
    const scaleX = displayW / (maxX - minX || 1);
    const scaleY = displayH / (maxY - minY || 1);
    const radius = Math.max(10, Math.round(Math.min(displayW, displayH) / 35));
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, displayW, displayH);
    ctx.fillStyle = "rgba(10,20,40,0.85)";
    ctx.fillRect(0, 0, displayW, displayH);
    for (const p of points) {
      const x = (p.cx - minX) * scaleX;
      const y = (p.cy - minY) * scaleY;
      const t = maxSpeed > 0 ? p.sp / maxSpeed : 0;
      let r, g, b;
      if (t < 0.4) {
        const f = t / 0.4;
        r = Math.round(59  + f * (16  - 59));
        g = Math.round(130 + f * (185 - 130));
        b = Math.round(246 + f * (129 - 246));
      } else if (t < 0.7) {
        const f = (t - 0.4) / 0.3;
        r = Math.round(16  + f * (232 - 16));
        g = Math.round(185 + f * (114 - 185));
        b = Math.round(129 + f * (42  - 129));
      } else {
        const f = (t - 0.7) / 0.3;
        r = Math.round(232 + f * (239 - 232));
        g = Math.round(114 + f * (68  - 114));
        b = Math.round(42  + f * (68  - 42));
      }
      const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
      grad.addColorStop(0,   `rgba(${r},${g},${b},0.55)`);
      grad.addColorStop(0.5, `rgba(${r},${g},${b},0.2)`);
      grad.addColorStop(1,   `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function renderCharts(csv) {
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

    const smooth = (arr, w = 7) => arr.map((_, i) => {
      const slice = arr.slice(Math.max(0, i - w + 1), i + 1);
      return slice.reduce((a, b) => a + b, 0) / slice.length;
    });

    // ── Novas métricas calculadas do CSV ──
    const n = speeds.length;
    const mean = speeds.reduce((a, b) => a + b, 0) / n;
    const std  = Math.sqrt(speeds.map(s => (s - mean) ** 2).reduce((a, b) => a + b, 0) / n);
    const regularity = Math.max(0, Math.min(100, 100 - (std / (mean || 1)) * 100)).toFixed(1);

    const maxSpeedVal = Math.max(...speeds);
    const maxIdx      = speeds.indexOf(maxSpeedVal);
    const timeToMax   = parseFloat(times[maxIdx] || 0).toFixed(1);

    const half  = Math.floor(n / 2);
    const avg1  = speeds.slice(0, half).reduce((a, b) => a + b, 0) / (half || 1);
    const avg2  = speeds.slice(half).reduce((a, b) => a + b, 0) / ((n - half) || 1);
    const delta = (avg1 - avg2).toFixed(1);

    const elReg   = document.getElementById("dashRegularity");
    const elTtM   = document.getElementById("dashTimeToMax");
    const elDelta = document.getElementById("dashFatigueDelta");
    if (elReg)   elReg.textContent   = regularity;
    if (elTtM)   elTtM.textContent   = timeToMax;
    if (elDelta) elDelta.textContent = delta;

    // ── Distância cumulativa (para curva de fadiga) ──
    const distances = [0];
    for (let i = 1; i < n; i++) {
      const dt = parseFloat(times[i]) - parseFloat(times[i - 1]);
      distances.push(distances[i - 1] + (speeds[i - 1] / 3.6) * Math.max(0, dt));
    }
    const distLabels = distances.map(d => d.toFixed(1));

    // ── Jerk (derivada da aceleração suavizada) ──
    const accelSm = smooth(accels, 7);
    const jerk = accelSm.map((a, i) => {
      if (i === 0) return 0;
      const dt = parseFloat(times[i]) - parseFloat(times[i - 1]);
      return dt > 0 ? (accelSm[i] - accelSm[i - 1]) / dt : 0;
    });

    // ── Distribuição de velocidade (histograma) ──
    const bucketSize = 5;
    const maxBucket  = Math.ceil(maxSpeedVal / bucketSize) * bucketSize;
    const numBuckets = Math.max(1, maxBucket / bucketSize);
    const counts     = Array(numBuckets).fill(0);
    speeds.forEach(s => {
      const i = Math.min(Math.floor(s / bucketSize), numBuckets - 1);
      counts[i]++;
    });
    const distBucketLabels = Array.from({ length: numBuckets }, (_, i) => `${i * bucketSize}–${(i + 1) * bucketSize}`);
    const pcts = counts.map(c => ((c / n) * 100).toFixed(1));

    // ── Velocidade média por fase ──
    const third  = Math.floor(n / 3);
    const pAvg   = arr => (arr.reduce((a, b) => a + b, 0) / (arr.length || 1)).toFixed(1);
    const phaseAvgs = [
      parseFloat(pAvg(speeds.slice(0, third))),
      parseFloat(pAvg(speeds.slice(third, third * 2))),
      parseFloat(pAvg(speeds.slice(third * 2))),
    ];

    const base = {
      responsive: true,
      animation: { duration: 600 },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#6B7280", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { ticks: { color: "#6B7280", font: { size: 10 } }, grid: { color: "rgba(255,255,255,0.05)" } },
      }
    };

    if (speedChart) speedChart.destroy();
    speedChart = new Chart(document.getElementById("chartSpeed"), {
      type: "line",
      data: {
        labels: times,
        datasets: [{ data: smooth(speeds), borderColor: "#3B82F6", backgroundColor: "rgba(59,130,246,0.1)", fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
      },
      options: { ...base, scales: { ...base.scales, y: { ...base.scales.y, title: { display: true, text: "km/h", color: "#9CA3AF" } } } }
    });

    if (accelChart) accelChart.destroy();
    accelChart = new Chart(document.getElementById("chartAccel"), {
      type: "line",
      data: {
        labels: times,
        datasets: [{ data: smooth(accels), borderColor: "#10B981", backgroundColor: "rgba(16,185,129,0.08)", fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
      },
      options: { ...base, scales: { ...base.scales, y: { ...base.scales.y, title: { display: true, text: "m/s²", color: "#9CA3AF" } } } }
    });

    // ── Jerk ──
    if (jerkChart) jerkChart.destroy();
    jerkChart = new Chart(document.getElementById("chartJerk"), {
      type: "line",
      data: {
        labels: times,
        datasets: [{ data: smooth(jerk, 12), borderColor: "#A855F7", backgroundColor: "rgba(168,85,247,0.07)", fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
      },
      options: { ...base, scales: { ...base.scales, y: { ...base.scales.y, title: { display: true, text: "m/s³", color: "#9CA3AF" } } } }
    });

    // ── Curva de Fadiga ──
    if (fatigueChart) fatigueChart.destroy();
    fatigueChart = new Chart(document.getElementById("chartFatigue"), {
      type: "line",
      data: {
        labels: distLabels,
        datasets: [{ data: smooth(speeds, 9), borderColor: "#E8722A", backgroundColor: "rgba(232,114,42,0.08)", fill: true, tension: 0.4, pointRadius: 0, borderWidth: 2 }]
      },
      options: { ...base, scales: {
        x: { ...base.scales.x, title: { display: true, text: "Distância (m)", color: "#9CA3AF" }, ticks: { ...base.scales.x.ticks, maxTicksLimit: 8 } },
        y: { ...base.scales.y, title: { display: true, text: "km/h", color: "#9CA3AF" } }
      }}
    });

    // ── Distribuição de Velocidade ──
    if (distChart) distChart.destroy();
    distChart = new Chart(document.getElementById("chartDist"), {
      type: "bar",
      data: {
        labels: distBucketLabels,
        datasets: [{
          data: pcts,
          backgroundColor: distBucketLabels.map((_, i) => `hsla(${200 + i * 10}, 80%, 60%, 0.7)`),
          borderColor:     distBucketLabels.map((_, i) => `hsla(${200 + i * 10}, 80%, 60%, 1)`),
          borderWidth: 1, borderRadius: 4
        }]
      },
      options: { ...base, scales: {
        x: { ...base.scales.x, title: { display: true, text: "Faixa (km/h)", color: "#9CA3AF" } },
        y: { ...base.scales.y, title: { display: true, text: "% do tempo", color: "#9CA3AF" } }
      }}
    });

    // ── Velocidade por Fase ──
    if (phasesChart) phasesChart.destroy();
    phasesChart = new Chart(document.getElementById("chartPhases"), {
      type: "bar",
      data: {
        labels: ["Arrancada (1ª fase)", "Desenvolvimento (2ª fase)", "Final (3ª fase)"],
        datasets: [{
          data: phaseAvgs,
          backgroundColor: ["rgba(59,130,246,0.7)", "rgba(16,185,129,0.7)", "rgba(232,114,42,0.7)"],
          borderColor:     ["#3B82F6", "#10B981", "#E8722A"],
          borderWidth: 1, borderRadius: 6
        }]
      },
      options: { ...base, indexAxis: "y", scales: {
        x: { ...base.scales.x, title: { display: true, text: "km/h", color: "#9CA3AF" } },
        y: { ...base.scales.y }
      }}
    });
  }

  // === CARD MÉTRICAS PNG (Canvas) ===
  function downloadMetricsCard() {
    const W = 1080, H = 680;
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = '#0d1f35';
    ctx.fillRect(0, 0, W, H);

    ctx.fillStyle = '#E8722A';
    ctx.fillRect(0, 0, W, 6);

    ctx.font = 'bold 54px Montserrat, Arial';
    ctx.fillStyle = '#FFFFFF';
    ctx.fillText('Puxa', 60, 82);
    const bw = ctx.measureText('Puxa').width;
    ctx.fillStyle = '#E8722A';
    ctx.fillText('.ai', 60 + bw, 82);

    const get = id => document.getElementById(id)?.textContent ?? '—';
    const metrics = [
      ['VEL. MÁXIMA',  get('dashMaxSpeed'),   'km/h'],
      ['VEL. MÉDIA',   get('dashAvgSpeed'),    'km/h'],
      ['DISTÂNCIA',    get('dashDistance'),    'm'],
      ['TEMPO',        get('dashRunTime'),     's'],
      ['ARRANCADA',    get('dashMaxAccel'),    'm/s²'],
      ['EFICIÊNCIA',   get('dashEfficiency'),  '%'],
    ];

    const cols = 3, colW = W / cols, startY = 160;
    metrics.forEach(([label, val, unit], i) => {
      const x = (i % cols) * colW + 60;
      const y = startY + Math.floor(i / cols) * 200;

      ctx.font = '600 18px Inter, Arial';
      ctx.fillStyle = '#9CA3AF';
      ctx.fillText(label, x, y);

      ctx.font = 'bold 64px Montserrat, Arial';
      ctx.fillStyle = '#FFFFFF';
      ctx.fillText(val, x, y + 74);

      const vw = ctx.measureText(val).width;
      ctx.font = '600 22px Inter, Arial';
      ctx.fillStyle = '#E8722A';
      ctx.fillText(unit, x + vw + 10, y + 64);
    });

    ctx.font = '400 22px Inter, Arial';
    ctx.fillStyle = '#4B5563';
    ctx.fillText('puxaai.com', 60, H - 28);

    canvas.toBlob(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'puxa-ai-metricas.png';
      a.click();
    });
  }

  // === FEEDBACK MODAL ===
  function showFeedbackModal() {
    const el = document.getElementById("feedbackModal");
    if (el) el.style.display = "flex";
  }

  window._feedbackStars = 0;

  window.setFeedbackStar = function(n) {
    window._feedbackStars = n;
    document.querySelectorAll(".fb-star").forEach((s, i) => {
      s.style.color = i < n ? "#E8722A" : "rgba(255,255,255,0.2)";
    });
  };

  window.closeFeedbackModal = function() {
    const el = document.getElementById("feedbackModal");
    if (el) el.style.display = "none";
  };

  window.submitFeedback = async function() {
    const stars = window._feedbackStars;
    const msg   = document.getElementById("fbMensagem").value.trim();
    const token = new URLSearchParams(window.location.search).get("token") || "";

    if (!stars) { alert("Selecione quantas estrelas!"); return; }

    const btn = document.getElementById("fbSubmitBtn");
    btn.disabled = true;
    btn.textContent = "Enviando...";

    try {
      await fetch(`${API_BASE}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ estrelas: stars, mensagem: msg, token })
      });
      document.getElementById("fbForm").style.display = "none";
      document.getElementById("fbSuccess").style.display = "flex";
      setTimeout(() => closeFeedbackModal(), 2500);
    } catch {
      btn.disabled = false;
      btn.textContent = "Enviar";
      alert("Erro ao enviar. Tente novamente.");
    }
  };

  // === NOVA ANÁLISE ===
  btnNewAnalysis.addEventListener("click", () => {
    [speedChart, accelChart, jerkChart, fatigueChart, distChart, phasesChart].forEach(c => { if (c) c.destroy(); });
    speedChart = accelChart = jerkChart = fatigueChart = distChart = phasesChart = null;
    fileInput.value = "";
    showStage("Upload");
  });

  // === DRAG & DROP ===
  dropZone.addEventListener("dragenter", (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragover",  (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove("drag-over");
  });
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  // === CLICK TO SELECT ===
  dropZone.addEventListener("click", (e) => {
    if (e.target === btnSelect || btnSelect.contains(e.target)) return;
    fileInput.click();
  });
  btnSelect.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) handleFile(file);
    fileInput.value = "";
  });

  // === TOAST ===
  function showToast(type, title, message) {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icons = { success: "fas fa-check-circle", error: "fas fa-exclamation-triangle", info: "fas fa-info-circle" };
    toast.innerHTML = `
      <div class="toast-icon"><i class="${icons[type]}"></i></div>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        <div class="toast-message">${message}</div>
      </div>`;
    toastContainer.appendChild(toast);
    setTimeout(() => { toast.classList.add("removing"); setTimeout(() => toast.remove(), 300); }, 3500);
  }

  // === KEYBOARD ===
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "u") { e.preventDefault(); fileInput.click(); }
  });
});
