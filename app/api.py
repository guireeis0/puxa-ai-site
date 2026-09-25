import os
import sys
import uuid
import logging
import json
import threading
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask import Flask, request, jsonify, send_file, send_from_directory, redirect
from flask_cors import CORS
from werkzeug.utils import secure_filename
from analytics import generate_report
from report import generate_pdf_report
from var import var_bp
from main import process_video as process_performance
from config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, PHASE_HIGH_FRAC

MIN_ACCEL_TO_REPORT = 2.0   # m/s² — abaixo disso não há arrancada/frenagem digna de nota
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Passa caminhos para o Blueprint via environ
app.wsgi_app.__class__  # garante que wsgi_app existe
OUTPUT_FOLDER_VAR = os.path.join(os.path.abspath(os.path.join(BASE_DIR, "..")), "output")
MODEL_PATH_VAR    = os.path.join(os.path.abspath(os.path.join(BASE_DIR, "..")), "models", "yolov8n.pt")

@app.before_request
def _inject_var_env():
    from flask import request as req
    req.environ.setdefault("VAR_OUTPUT_ROOT", OUTPUT_FOLDER_VAR)
    req.environ.setdefault("MODEL_PATH",      MODEL_PATH_VAR)

app.register_blueprint(var_bp, url_prefix="/var")

PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

# === SUPABASE CONFIG ===
_SUPA_URL  = os.environ.get('SUPABASE_URL', '')
_SUPA_KEY  = os.environ.get('SUPABASE_SERVICE_KEY', '')
ADMIN_KEY  = os.environ.get('ADMIN_KEY', '')

def _supa(method, table, data=None, params=None):
    headers = {
        'apikey': _SUPA_KEY,
        'Authorization': f'Bearer {_SUPA_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    return requests.request(
        method,
        f"{_SUPA_URL}/rest/v1/{table}",
        headers=headers, json=data, params=params, timeout=5
    )

def _token_valido(token):
    if not _SUPA_KEY:
        return True  # dev sem Supabase configurado: libera acesso
    resp = _supa('GET', 'access_tokens', params={'token': f'eq.{token}', 'select': 'expires_at'})
    if resp.status_code != 200 or not resp.json():
        return False
    exp = datetime.fromisoformat(resp.json()[0]['expires_at'].replace('Z', '+00:00'))
    return exp > datetime.now(timezone.utc)

UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, "uploads")
OUTPUT_FOLDER = os.path.join(PROJECT_ROOT, "output")
DIST_FOLDER   = os.path.join(PROJECT_ROOT, "dist")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES

# ── Servir o frontend (build do Vite) ──────────────────────────
@app.route("/")
def serve_index():
    return send_from_directory(DIST_FOLDER, "index.html")

@app.route("/var.html")
@app.route("/var-page")
def serve_var():
    return send_from_directory(DIST_FOLDER, "var.html")

@app.route("/analisar.html")
@app.route("/analisar")
def serve_analisar():
    return send_from_directory(DIST_FOLDER, "analisar.html")

@app.route("/assets/<path:filename>")
def serve_assets(filename):
    return send_from_directory(os.path.join(DIST_FOLDER, "assets"), filename)

@app.route("/puxa-ai-site/<path:filename>")
def serve_puxa_static(filename):
    return send_from_directory(os.path.join(DIST_FOLDER, "puxa-ai-site"), filename)

JOBS_STATUS = {} 

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================================================
# 🧠 GERAÇÃO DE ANÁLISE TEXTUAL DA IA
# ============================================================
def generate_ai_analysis(result: dict) -> str:
    """
    Gera um parágrafo de análise biomecânica em português
    a partir das métricas retornadas pelo process_video.
    """
    parts = []
    speed, max_speed = result.get("avg_speed"), result.get("max_speed")
    bio = result.get("biomecanica") or {}
    passada = bio.get("passada") or {}
    slow = passada.get("fator_camera_lenta")

    if speed:
        if slow:
            parts.append(f"O vídeo parece estar em câmera lenta (~{slow:.1f}×); em tempo real, a velocidade média "
                         f"fica em torno de <strong>{speed * slow:.1f} km/h</strong> e o pico em "
                         f"<strong>{(max_speed or 0) * slow:.1f} km/h</strong>.")
        else:
            parts.append(f"Velocidade média de <strong>{float(speed):.1f} km/h</strong> na corrida, com pico de "
                         f"<strong>{float(max_speed or 0):.1f} km/h</strong> aos {result.get('time_to_max_speed', 0):.1f} s.")

    fases = {f["fase"]: f for f in result.get("fases") or []}
    arr, fre = fases.get("arrancada"), fases.get("frenagem")
    # só comenta arrancada/frenagem quando elas existem no vídeo (largada parada, freada de verdade)
    if arr and arr["duracao_s"] >= 1.0 and result.get("max_accel", 0) >= MIN_ACCEL_TO_REPORT:
        parts.append(f"A arrancada levou <strong>{arr['duracao_s']:.1f} s</strong> até "
                     f"{int(PHASE_HIGH_FRAC * 100)}% do pico, com aceleração máxima de "
                     f"<strong>{result['max_accel']:.1f} m/s²</strong>.")
    if fre and fre["duracao_s"] >= 1.0 and result.get("max_decel", 0) >= MIN_ACCEL_TO_REPORT:
        parts.append(f"Na frenagem/derrubada a desaceleração chegou a <strong>{result['max_decel']:.1f} m/s²</strong>.")

    if passada.get("frequencia_hz"):
        f_real = passada["frequencia_hz"] * (slow or 1)
        txt = f"Passada de <strong>{f_real:.2f} Hz</strong>"
        if passada.get("comprimento_m"):
            txt += f" e comprimento de ~<strong>{passada['comprimento_m']:.1f} m</strong>"
        parts.append(txt + ".")

    if not parts:
        parts.append("Análise biomecânica concluída. Verifique os arquivos de métricas para detalhes completos.")

    return " ".join(parts)


# ============================================================
# 🦴 BIOMECÂNICA (pose) — ambiente Python separado com DeepLabCut
# ============================================================
# Ativada só quando BIO_PYTHON aponta para o python do ambiente de pose.
BIO_PYTHON  = os.environ.get("BIO_PYTHON", "")
BIO_RUNNER  = os.path.join(PROJECT_ROOT, "bio", "run_bio.py")
BIO_TIMEOUT = int(os.environ.get("BIO_TIMEOUT_S", "1200"))

def run_biomechanics(video_path, out_dir, update_msg):
    """Roda bio/run_bio.py no ambiente de pose, repassa o progresso e devolve o bio.json (ou None)."""
    if not BIO_PYTHON or not os.path.exists(BIO_PYTHON):
        return None
    bio_dir = os.path.join(out_dir, "bio")
    os.makedirs(bio_dir, exist_ok=True)
    cmd = [BIO_PYTHON, BIO_RUNNER, video_path, bio_dir, "--track", os.path.join(out_dir, "metrics.csv")]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    err_log = open(os.path.join(bio_dir, "stderr.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_log, text=True,
                            encoding="utf-8", errors="replace", env=env)
    try:
        for raw in proc.stdout:
            msg = raw.strip()
            if msg.startswith("[bio] frame"):
                update_msg("IA: Biomecânica — pose " + msg[len("[bio] "):])
            elif msg.startswith("[bio] pose ok"):
                update_msg("IA: Biomecânica — calculando passada, mão de galope e ângulos...")
        proc.wait(timeout=BIO_TIMEOUT)
    finally:
        err_log.close()
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        with open(os.path.join(bio_dir, "stderr.log"), encoding="utf-8") as f:
            lines = [l for l in f.read().strip().splitlines() if l.strip()]
        raise RuntimeError(lines[-1] if lines else "falha na biomecânica")
    with open(os.path.join(bio_dir, "bio.json"), encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 🚀 MOTOR DE BIOMECÂNICA (Background)
# ============================================================
def run_ai_pipeline(job_id, video_path, mode="performance"):

    def update_msg(msg):
        if job_id in JOBS_STATUS:
            JOBS_STATUS[job_id]["message"] = msg
            logging.info("[%s] %s", job_id, msg)

    JOBS_STATUS[job_id] = {
        "status": "processing", 
        "message": "Extraindo dados biomecânicos...", 
        "mode": mode
    }
    
    try:
        # 1) IA processa o vídeo (YOLO + compensação de câmera + cinemática offline)
        result = process_performance(
            video_path, 
            job_id=job_id, 
            base_output=OUTPUT_FOLDER, 
            status_callback=update_msg
        )

        # Garante que result é um dict
        if result is None:
            result = {}

        # 2) Gera gráficos (PNG) e relatórios (PDF)
        update_msg("IA: Desenhando gráficos de telemetria...")
        generate_report(job_id, base_output=OUTPUT_FOLDER) 

        update_msg("IA: Costurando relatório em PDF...")
        generate_pdf_report(job_id, base_output=OUTPUT_FOLDER)

        # 3) Biomecânica (opcional — não derruba o job se falhar)
        downloads_extra = {}
        if BIO_PYTHON:
            update_msg("IA: Biomecânica — carregando modelo de pose (39 pontos)...")
            JOBS_STATUS[job_id]["live"] = f"/live/{job_id}"
            try:
                bio = run_biomechanics(video_path, os.path.join(OUTPUT_FOLDER, job_id), update_msg)
                if bio:
                    result["biomecanica"] = bio
                    downloads_extra["bio_video"]     = f"/download/{job_id}/bio/biomecanica.mp4"
                    downloads_extra["bio_keypoints"] = f"/download/{job_id}/bio/keypoints.csv"
            except Exception as e:
                logging.error("Biomecânica falhou no job %s: %s", job_id, e)
                result["biomecanica_erro"] = str(e)

        # 4) Análise textual (depois da biomecânica, para incluir passada e câmera lenta)
        result["ai_analysis"] = generate_ai_analysis(result)

        # 5) Marca como completo para o script.js ler
        JOBS_STATUS[job_id] = {
            "status": "completed",
            "message": "IA: Análise concluída! Relatório pronto.",
            "mode": mode,
            "result": result,
            "downloads": {
                "video":       f"/download/{job_id}/resultado.mp4",
                "report_pdf":  f"/download/{job_id}/performance_report.pdf",
                "graph_png":   f"/download/{job_id}/performance_report.png",
                "metrics_csv": f"/download/{job_id}/metrics.csv",
                "summary_csv": f"/download/{job_id}/summary.csv",
                **downloads_extra,
            }
        }
        logging.info("Job %s finalizado com sucesso.", job_id)

    except Exception as e:
        logging.error("Falha no Job %s: %s", job_id, e, exc_info=True)
        JOBS_STATUS[job_id] = {
            "status": "error", 
            "message": f"Erro na análise: {str(e)}"
        }

# ============================================================
# 🚀 API REST (CONEXÃO COM O FRONTEND)
# ============================================================
@app.route("/health", methods=["GET"])
def health_check():
    bio_on = bool(BIO_PYTHON) and os.path.exists(BIO_PYTHON)
    return jsonify({"status": "ok", "biomecanica": bio_on}), 200

@app.route("/upload", methods=["POST"])
def upload_video():
    mode = request.form.get('mode', 'performance')

    if "video" not in request.files:
        return jsonify({"error": "Campo 'video' não encontrado."}), 400

    file = request.files["video"]
    if file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Formato não suportado."}), 400

    job_id = str(uuid.uuid4())
    safe_filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{safe_filename}")
    
    file.save(save_path)

    thread = threading.Thread(target=run_ai_pipeline, args=(job_id, save_path, mode))
    thread.start()

    return jsonify({
        "job_id": job_id,
        "mode": mode,
        "status_url": f"/status/{job_id}"
    }), 202

@app.route("/status/<job_id>", methods=["GET"])
def check_status(job_id):
    job_info = JOBS_STATUS.get(job_id)
    if not job_info:
        return jsonify({"error": "Job não encontrado."}), 404
    return jsonify(job_info)

@app.route("/var", methods=["GET"])
def var_page():
    var_html = os.path.join(PROJECT_ROOT, "var.html")
    return send_file(var_html)

@app.route("/live/<job_id>", methods=["GET"])
def live_frame(job_id):
    """Último frame processado pela pose, com o esqueleto (prévia ao vivo)."""
    if job_id not in JOBS_STATUS:
        return jsonify({"error": "Job não encontrado."}), 404
    path = os.path.join(OUTPUT_FOLDER, job_id, "bio", "live.jpg")
    try:
        # lê tudo de uma vez para não segurar o arquivo aberto (no Windows isso travaria a troca do frame)
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ("", 204)
    return app.response_class(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.route("/download/<job_id>/<path:filename>", methods=["GET"])
def download_file(job_id, filename):
    job_dir   = os.path.abspath(os.path.join(OUTPUT_FOLDER, job_id))
    file_path = os.path.abspath(os.path.join(job_dir, filename))
    if not file_path.startswith(job_dir + os.sep) or not os.path.exists(file_path):
        return jsonify({"error": "Arquivo não encontrado"}), 404
    return send_file(file_path, as_attachment=True)

# ============================================================
# DEMO — Acesso por Token Temporário (7 dias)
# ============================================================
@app.route("/demo/<token>")
def serve_demo(token):
    if not _token_valido(token):
        return redirect('/')
    return send_from_directory(DIST_FOLDER, "analisar.html")

@app.route("/admin")
def serve_admin():
    return send_from_directory(PROJECT_ROOT, "admin.html")

@app.route("/admin/generate-token", methods=["POST"])
def generate_token():
    data = request.get_json(silent=True) or {}
    if not ADMIN_KEY or data.get('admin_key') != ADMIN_KEY:
        return jsonify({"error": "Não autorizado"}), 403

    email = str(data.get('email', '')).strip()
    if not email:
        return jsonify({"error": "Email obrigatório"}), 400

    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    resp = _supa('POST', 'access_tokens', data={'lead_email': email, 'expires_at': expires_at})
    if resp.status_code not in (200, 201):
        return jsonify({"error": "Erro Supabase", "detail": resp.text}), 500

    row = resp.json()
    token_val = (row[0] if isinstance(row, list) else row).get('token')
    link = f"{request.host_url.rstrip('/')}/demo/{token_val}"
    logging.info("Token gerado para %s — expira em %s", email, expires_at)
    return jsonify({"link": link, "email": email, "expires_at": expires_at}), 201


# ============================================================
# LEADS — Acesso Antecipado
# ============================================================
@app.route("/leads", methods=["POST"])
def save_lead():
    import json as _json
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Dados inválidos"}), 400

    required = ['nome', 'email', 'whatsapp', 'instagram']
    for field in required:
        if not str(data.get(field, '')).strip():
            return jsonify({"error": f"Campo '{field}' obrigatório"}), 400

    lead = {
        "nome":          str(data.get("nome", "")).strip(),
        "email":         str(data.get("email", "")).strip(),
        "whatsapp":      str(data.get("whatsapp", "")).strip(),
        "instagram":     str(data.get("instagram", "")).strip(),
        "data_cadastro": str(data.get("data_cadastro", ""))
    }

    leads_file = os.path.join(PROJECT_ROOT, "leads.json")
    leads = []
    if os.path.exists(leads_file):
        try:
            with open(leads_file, 'r', encoding='utf-8') as f:
                leads = _json.load(f)
        except Exception:
            leads = []

    leads.append(lead)
    with open(leads_file, 'w', encoding='utf-8') as f:
        _json.dump(leads, f, ensure_ascii=False, indent=2)

    logging.info("Novo lead registrado: %s <%s>", lead["nome"], lead["email"])
    return jsonify({"status": "ok"}), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)