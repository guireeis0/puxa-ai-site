import os
import sys
import uuid
import threading
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from analytics import generate_report
from report import generate_pdf_report
from var import var_bp

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

UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, "uploads")
OUTPUT_FOLDER = os.path.join(PROJECT_ROOT, "output")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv'}
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024 

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

    speed     = result.get("avg_speed_kmh") or result.get("velocidade_media")
    max_speed = result.get("max_speed_kmh")  or result.get("velocidade_maxima")
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
            print(f"[{job_id}] {msg}")

    JOBS_STATUS[job_id] = {
        "status": "processing", 
        "message": "Extraindo dados biomecânicos...", 
        "mode": mode
    }
    
    try:
        from main import process_video as process_performance
        
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
            "result": result,           # ← métricas + ai_analysis enviados ao frontend
            "downloads": {
                "video":       f"/download/{job_id}/resultado.mp4",
                "report_pdf":  f"/download/{job_id}/performance_report.pdf",
                "graph_png":   f"/download/{job_id}/performance_report.png",
                "metrics_csv": f"/download/{job_id}/metrics.csv",
                "summary_csv": f"/download/{job_id}/summary.csv"
            }
        }
        print(f"Job {job_id} finalizado com sucesso!")

    except Exception as e:
        print(f"❌ [ERRO] Falha no Job {job_id}: {str(e)}")
        JOBS_STATUS[job_id] = {
            "status": "error", 
            "message": f"Erro na análise: {str(e)}"
        }

# ============================================================
# 🚀 API REST (CONEXÃO COM O FRONTEND)
# ============================================================
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)