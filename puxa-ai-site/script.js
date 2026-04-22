/* ============================================
   PUXA.AI — Upload Designer
   JavaScript
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  // === DOM ELEMENTS ===
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const btnSelect = document.getElementById("btnSelect");
  const queueList = document.getElementById("queueList");
  const queueEmpty = document.getElementById("queueEmpty");
  const uploadActions = document.getElementById("uploadActions");
  const btnClear = document.getElementById("btnClear");
  const btnUpload = document.getElementById("btnUpload");
  const totalFilesEl = document.getElementById("totalFiles");
  const totalSizeEl = document.getElementById("totalSize");
  const progressBar = document.getElementById("progressBar");
  const progressText = document.getElementById("progressText");
  const progressSpeed = document.getElementById("progressSpeed");
  const toastContainer = document.getElementById("toastContainer");

  // === STATE ===
  let fileQueue = [];
  let isUploading = false;

  // === INJECT IA ANIMATION KEYFRAMES (apenas uma vez) ===
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

  // === FILE TYPE HELPERS ===
  function getFileCategory(file) {
    const ext = file.name.split(".").pop().toLowerCase();
    const type = file.type;
    if (type.startsWith("video/") || ["mp4","avi","mov","mkv","webm"].includes(ext)) return "video";
    if (type.startsWith("image/") || ["jpg","jpeg","png","gif","webp","svg","bmp"].includes(ext)) return "image";
    if (type === "application/pdf" || ext === "pdf") return "pdf";
    if (["csv","xlsx","xls","json","xml"].includes(ext)) return "data";
    if (["doc","docx","txt","rtf","odt"].includes(ext)) return "doc";
    return "other";
  }

  function getFileIcon(category) {
    const icons = {
      video: "fas fa-video", image: "fas fa-image", pdf: "fas fa-file-pdf",
      data: "fas fa-file-csv", doc: "fas fa-file-alt", other: "fas fa-file",
    };
    return icons[category] || icons.other;
  }

  function formatSize(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024, sizes = ["B","KB","MB","GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  }

  function getExtension(name) { return name.split(".").pop().toUpperCase(); }

  // === GENERATE UNIQUE ID ===
  let idCounter = 0;
  function uniqueId() { return "file_" + Date.now() + "_" + idCounter++; }

  // === ADD FILES TO QUEUE ===
  function addFiles(files) {
    const newFiles = Array.from(files);
    if (newFiles.length === 0) return;
    newFiles.forEach((file) => {
      fileQueue.push({
        id: uniqueId(), file, name: file.name, size: file.size,
        category: getFileCategory(file), progress: 0, status: "pending",
      });
    });
    renderQueue();
    showToast("info", "Arquivos adicionados", `${newFiles.length} arquivo(s) na fila`);
  }

  // === RENDER QUEUE ===
  function renderQueue() {
    if (totalFilesEl) totalFilesEl.textContent = fileQueue.length + " arquivo" + (fileQueue.length !== 1 ? "s" : "");
    const totalBytes = fileQueue.reduce((sum, f) => sum + f.size, 0);
    if (totalSizeEl) totalSizeEl.textContent = formatSize(totalBytes);

    if (fileQueue.length === 0) {
      if (queueEmpty) queueEmpty.style.display = "flex";
      if (uploadActions) uploadActions.style.display = "none";
      queueList.innerHTML = "";
      return;
    }

    if (queueEmpty) queueEmpty.style.display = "none";
    if (uploadActions) uploadActions.style.display = "block";

    queueList.innerHTML = "";
    fileQueue.forEach((item) => queueList.appendChild(createFileCard(item)));
    updateGlobalProgress();
  }

  // === CREATE FILE CARD ===
  function createFileCard(item) {
    const card = document.createElement("div");
    card.className = `file-card ${item.status}`;
    card.dataset.id = item.id;

    const isActive   = item.status === "uploading" || item.status === "processing";
    const isError    = item.status === "error";
    const isComplete = item.status === "complete";
    const isPending  = item.status === "pending";

    const accent = isComplete ? "#4ade80" : isError ? "#f87171" : "#E8722A";
    const barBg  = isComplete ? "#4ade80" : isError ? "#f87171"
                 : "linear-gradient(90deg,#E8722A,#2E5BBA)";

    // Painel IA: frames + barra de progresso + log
    const iaPanel = (isActive || isError) ? `
      <div data-ia-frames style="display:flex;gap:4px;margin-top:10px;">
        ${Array.from({length:8}, (_, i) => `
          <div data-frame="${i}" style="
               flex:1; height:26px; border-radius:4px;
               background:rgba(255,255,255,0.04);
               border:1px solid rgba(255,255,255,0.08);
               position:relative; overflow:hidden;">
            <div class="puxa-scan-bar"></div>
          </div>`).join("")}
      </div>

      <div style="margin-top:8px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
          <span data-ia-pct style="font-family:'Space Mono',monospace;font-size:10px;color:#E8722A;">0%</span>
          <span data-ia-eta style="font-family:'Space Mono',monospace;font-size:10px;color:#6B7280;"></span>
        </div>
        <div style="height:5px;background:rgba(255,255,255,0.06);border-radius:99px;overflow:hidden;">
          <div class="bar-fill" style="
               height:100%; width:${item.status === 'uploading' ? item.progress : 0}%;
               border-radius:99px; background:${barBg}; transition:width .35s ease;"></div>
        </div>
      </div>

      <div data-ia-log style="
           margin-top:10px;
           background:rgba(255,255,255,0.02);
           border:1px solid rgba(255,255,255,0.07);
           border-radius:8px; padding:8px 12px;
           min-height:50px; display:flex; flex-direction:column;
           gap:3px; overflow:hidden;">
        <span style="font-family:'Space Mono',monospace;font-size:10px;
              color:#4B5563;font-style:italic;">Aguardando servidor...</span>
      </div>` : "";

    // Botões de download após conclusão
    const dlBtns = (isComplete && item.downloadLinks) ? `
      <div style="margin-top:12px;display:flex;flex-wrap:wrap;gap:6px;">
        <a href="http://127.0.0.1:5000${item.downloadLinks.report_pdf}" target="_blank"
           style="background:#27ae60;color:#fff;padding:5px 11px;border-radius:5px;
                  text-decoration:none;font-size:.72rem;font-weight:700;
                  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;">
          <i class="fas fa-file-pdf"></i> PDF
        </a>
        <a href="http://127.0.0.1:5000${item.downloadLinks.video}" target="_blank"
           style="background:#27ae60;color:#fff;padding:5px 11px;border-radius:5px;
                  text-decoration:none;font-size:.72rem;font-weight:700;
                  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;">
          <i class="fas fa-video"></i> VÍDEO
        </a>
        <a href="http://127.0.0.1:5000${item.downloadLinks.graph_png}" target="_blank"
           style="background:#27ae60;color:#fff;padding:5px 11px;border-radius:5px;
                  text-decoration:none;font-size:.72rem;font-weight:700;
                  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;">
          <i class="fas fa-image"></i> GRÁFICO
        </a>
        <a href="http://127.0.0.1:5000${item.downloadLinks.metrics_csv}" target="_blank"
           style="background:#27ae60;color:#fff;padding:5px 11px;border-radius:5px;
                  text-decoration:none;font-size:.72rem;font-weight:700;
                  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;">
          <i class="fas fa-table"></i> MÉTRICAS
        </a>
        <a href="http://127.0.0.1:5000${item.downloadLinks.summary_csv}" target="_blank"
           style="background:#27ae60;color:#fff;padding:5px 11px;border-radius:5px;
                  text-decoration:none;font-size:.72rem;font-weight:700;
                  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;">
          <i class="fas fa-list"></i> RESUMO
        </a>
      </div>` : "";

    card.innerHTML = `
      <div class="file-icon ${item.category}">
        <i class="${getFileIcon(item.category)}"></i>
      </div>

      <div class="file-info">
        <div class="file-name" title="${item.name}">${item.name}</div>
        <div class="file-meta">
          <span class="file-size">${formatSize(item.size)}</span>
          <span class="file-type">${getExtension(item.name)}</span>
        </div>

        ${!isPending ? `
        <div style="margin-top:8px;display:flex;align-items:center;gap:7px;">
          ${isActive
            ? `<div style="display:flex;gap:3px;align-items:center;">
                 <span class="puxa-dot" style="background:${accent};"></span>
                 <span class="puxa-dot" style="background:${accent};"></span>
                 <span class="puxa-dot" style="background:${accent};"></span>
                 <span class="puxa-dot" style="background:${accent};"></span>
                 <span class="puxa-dot" style="background:${accent};"></span>
               </div>`
            : `<i class="fas ${isComplete ? 'fa-check-circle' : 'fa-exclamation-circle'}"
                  style="color:${accent};font-size:12px;"></i>`}
          <span class="ia-message" style="
                font-family:'Space Mono',monospace; font-size:10px;
                font-weight:700; text-transform:uppercase;
                letter-spacing:.6px; color:${accent};">
            ${item.statusMessage
              || (isActive   ? "IA: Iniciando..."
                : isComplete ? "IA: Análise concluída"
                :              "IA: Erro no processamento")}
          </span>
        </div>` : ""}

        ${iaPanel}
        ${dlBtns}
      </div>

      <div class="file-actions">
        ${isComplete
          ? `<i class="fas fa-check-circle" style="color:#4ade80;font-size:18px;"></i>`
          : `<button class="file-action-btn" onclick="removeFile('${item.id}')" title="Remover">
               <i class="fas fa-times"></i>
             </button>`}
      </div>
    `;

    return card;
  }

  // === REMOVE FILE ===
  window.removeFile = function (id) {
    if (isUploading) return;
    fileQueue = fileQueue.filter((f) => f.id !== id);
    renderQueue();
  };

  // === CLEAR QUEUE ===
  btnClear.addEventListener("click", () => {
    if (isUploading) return;
    fileQueue = [];
    renderQueue();
    showToast("info", "Fila limpa", "Todos os arquivos foram removidos");
  });

  btnUpload.addEventListener("click", (e) => {
    e.preventDefault();
    console.log("Clique detectado!");
    if (isUploading) return;
    const pendingFiles = fileQueue.filter((f) => f.status === "pending");
    if (pendingFiles.length === 0) {
      showToast("info", "Nada para enviar", "Todos os arquivos já foram enviados");
      return;
    }
    console.log("Enviando arquivos:", pendingFiles);
    startUpload(pendingFiles);
  });

  async function startUpload(files) {
    isUploading = true;
    btnUpload.disabled = true;
    btnUpload.innerHTML = '<i class="fas fa-spinner fa-spin"></i> PROCESSANDO IA...';

    const category = document.getElementById("categorySelect").value;
    const mode = (category === "prova") ? "performance" : "var";
    const pendingFiles = files.filter(f => f.status === "pending" || f.status === "error");

    for (let i = 0; i < pendingFiles.length; i++) {
      const item = pendingFiles[i];
      item.status = "uploading";
      item.progress = 0;
      item.statusMessage = "IA: Preparando conexão...";
      renderQueue();

      try {
        await realFileUpload(item, mode);
        console.log(`✅ Upload concluído para: ${item.name}`);
      } catch (error) {
        console.error(`❌ Erro no arquivo ${item.name}:`, error);
        item.status = "error";
        item.statusMessage = "IA: Falha no envio do arquivo.";
        renderQueue();
      }
    }

    isUploading = false;
    btnUpload.disabled = false;
    btnUpload.innerHTML = '<i class="fas fa-rocket"></i> ENVIAR TODOS';
  }

  function realFileUpload(item, mode) {
    return new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append("video", item.file);
      formData.append("mode", mode);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "http://127.0.0.1:5000/upload", true);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.floor((e.loaded / e.total) * 100);
          item.progress = pct;
          item.statusMessage = pct < 100
            ? `IA: Subindo arquivo (${pct}%)`
            : "IA: Recebido! Aguardando servidor...";

          // Atualização cirúrgica — sem re-render completo
          const card = document.querySelector(`.file-card[data-id="${item.id}"]`);
          if (card) {
            const msgEl = card.querySelector(".ia-message");
            const barEl = card.querySelector(".bar-fill");
            const pctEl = card.querySelector("[data-ia-pct]");
            if (msgEl) msgEl.textContent = item.statusMessage;
            if (barEl) barEl.style.width = pct + "%";
            if (pctEl) pctEl.textContent = pct + "%";
            _updateFrames(card, pct);
          }
        }
      };

      xhr.onload = function () {
        if (xhr.status === 202) {
          try {
            const response = JSON.parse(xhr.responseText);
            if (response.job_id) {
              console.log(`[${item.name}] Job ID recebido: ${response.job_id}`);
              monitorarProcessamento(item, response.job_id, resolve);
            } else {
              throw new Error("Job ID não retornado pelo servidor.");
            }
          } catch (err) {
            item.status = "error";
            item.statusMessage = "IA: Erro na resposta do servidor.";
            renderQueue();
            reject(err);
          }
        } else {
          item.status = "error";
          item.statusMessage = `Erro ${xhr.status}: Falha no servidor.`;
          renderQueue();
          reject(new Error(`Erro ${xhr.status}`));
        }
      };

      xhr.onerror = () => {
        item.status = "error";
        item.statusMessage = "IA: Erro de conexão com o servidor.";
        renderQueue();
        reject(new Error("Erro de rede."));
      };

      xhr.send(formData);
    });
  }

  // === HELPERS: atualização direta no DOM (sem re-render) ===

  // Marca frames conforme a porcentagem avança
  function _updateFrames(card, pct) {
    const frames = card.querySelectorAll("[data-frame]");
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

  // Adiciona linha no log (máximo 3 visíveis, circular)
  function _pushLog(card, text) {
    const logBox = card.querySelector("[data-ia-log]");
    if (!logBox) return;
    const colors = ["#E8722A", "#9CA3AF", "#6B7280"];
    const line = document.createElement("span");
    line.className = "puxa-log-line";
    line.style.cssText = `
      font-family:'Space Mono',monospace; font-size:10px;
      color:${colors[logBox.children.length % colors.length]};
      white-space:nowrap; overflow:hidden; text-overflow:ellipsis; display:block;`;
    line.textContent = text;
    logBox.appendChild(line);
    while (logBox.children.length > 3) logBox.removeChild(logBox.firstChild);
  }

  // === POLLING: Monitora processamento da IA no servidor ===
  function monitorarProcessamento(item, jobId, resolve) {
    item.status = "processing";
    item.statusMessage = "IA: Iniciando motores...";

    // Renderiza uma vez para montar o painel de IA no card
    renderQueue();

    let lastPct = 0;

    const checkInterval = setInterval(async () => {
      try {
        const res = await fetch(`http://127.0.0.1:5000/status/${jobId}`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.message) {
          item.statusMessage = data.message;

          const match = data.message.match(/(\d+)%/);
          const pct = match ? parseInt(match[1]) : lastPct;

          // Atualização cirúrgica no DOM — sem piscar
          const card = document.querySelector(`.file-card[data-id="${item.id}"]`);
          if (card) {
            const msgEl = card.querySelector(".ia-message");
            if (msgEl) msgEl.textContent = data.message;

            if (pct > lastPct) {
              const barEl = card.querySelector(".bar-fill");
              const pctEl = card.querySelector("[data-ia-pct]");
              if (barEl) barEl.style.width = pct + "%";
              if (pctEl) pctEl.textContent = pct + "%";
              _updateFrames(card, pct);
              lastPct = pct;
            }

            _pushLog(card, "› " + data.message);
          }
        }

        if (data.status === "completed") {
          clearInterval(checkInterval);
          item.status = "complete";
          item.downloadLinks = data.downloads;
          renderQueue();

          resolve();

        } else if (data.status === "error") {
          clearInterval(checkInterval);
          item.status = "error";
          item.statusMessage = "IA: Erro no processamento.";
          renderQueue();
          resolve();
        }
      } catch (err) {
        console.error("Erro no polling:", err);
      }
    }, 1000);
  }

  function updateGlobalProgress() {
    if (!progressBar) return;
    if (fileQueue.length === 0) { progressBar.style.width = "0%"; return; }
    const totalProgress = fileQueue.reduce((sum, f) => sum + f.progress, 0);
    const avg = Math.floor(totalProgress / fileQueue.length);
    progressBar.style.width = avg + "%";
    if (progressText) progressText.textContent = avg + "% concluído";
    const completed = fileQueue.filter((f) => f.status === "complete").length;
    if (progressSpeed) progressSpeed.textContent = completed + "/" + fileQueue.length + " arquivos";
  }

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
    addFiles(e.dataTransfer.files);
  });

  // === CLICK TO SELECT ===
  dropZone.addEventListener("click", (e) => {
    if (e.target === btnSelect || btnSelect.contains(e.target)) return;
    fileInput.click();
  });
  btnSelect.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
  fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });

  // === TOAST NOTIFICATIONS ===
  function showToast(type, title, message) {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icons = {
      success: "fas fa-check-circle",
      error: "fas fa-exclamation-triangle",
      info: "fas fa-info-circle",
    };
    toast.innerHTML = `
      <div class="toast-icon"><i class="${icons[type]}"></i></div>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        <div class="toast-message">${message}</div>
      </div>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.classList.add("removing");
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  // === KEYBOARD SHORTCUT ===
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "u") { e.preventDefault(); fileInput.click(); }
  });
});