import os
import sys
import uuid
import logging
import threading
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
from config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES
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

    speed     = result.get("avg_speed") or result.get("velocidade_media")
    max_speed = result.get("max_speed") or result.get("velocidade_maxima")
    sym       = result.get("simetria")        or result.get("symmetry_score")
    cadence   = result.get("cadencia")        or result.get("cadence")
    stride    = result.get("comprimento_passo") or result.get("stride_length")

    if speed is not None:
        parts.append(f"A velocidade média registrada foi de <strong>{float(speed):.1f} km/h</strong>")
        if max_speed:
            parts[-1] += f", com pico de <strong>{float(max_speed):.1f} km/h</strong>"
        parts[-1] += "."

    if cadence is not None:
        parts.append(f"A cadência de passada ficou em <strong>{int(cadence)} passos/min</strong>"
                     + (f", com comprimento médio de <strong>{float(stride):.2f} m</strong>." if stride else "."))

    if sym is not None:
        sym_val = float(sym)
        if sym_val >= 90:
            avaliacao = "excelente simetria bilateral"
        elif sym_val >= 75:
            avaliacao = "boa simetria, com leve compensação"
        elif sym_val >= 60:
            avaliacao = "simetria moderada — recomenda-se acompanhamento"
        else:
            avaliacao = "assimetria relevante detectada — avaliação veterinária indicada"
        parts.append(f"O índice de simetria foi de <strong>{sym_val:.1f}%</strong>, indicando <strong>{avaliacao}</strong>.")

    if not parts:
        parts.append("Análise biomecânica concluída. Verifique os arquivos de métricas para detalhes completos.")

    return " ".join(parts)


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
        # 1) IA processa o vídeo (YOLO + SpeedTracker)
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

        # 3) Adiciona análise textual da IA ao resultado
        result["ai_analysis"] = generate_ai_analysis(result)

        # 4) Marca como completo para o script.js ler
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
                "summary_csv": f"/download/{job_id}/summary.csv"
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
    return jsonify({"status": "ok"}), 200

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

@app.route("/download/<job_id>/<filename>", methods=["GET"])
def download_file(job_id, filename):
    file_path = os.path.abspath(os.path.join(OUTPUT_FOLDER, job_id, filename))
    if not os.path.exists(file_path):
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