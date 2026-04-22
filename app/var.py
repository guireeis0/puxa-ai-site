import os
import sys
import uuid
import json
import threading
import cv2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

var_bp = Blueprint("var", __name__)

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv"}

# In-memory job tracker (process-scoped; fine for single-worker dev server)
JOBS = {}

COW_LABELS   = {"cow", "cattle"}
HORSE_LABELS = {"horse"}

FALL_THRESHOLD    = 30   # px drop in cy (video coords) to detect fall
RISING_THRESHOLD  = 20   # px rise after fall to detect recovery
FALL_COOLDOWN     = 60   # frames between consecutive fall events (~2 s at 30 fps)


# ── helpers ──────────────────────────────────────────────────

def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _job_dir(output_root, job_id):
    path = os.path.join(output_root, job_id)
    os.makedirs(path, exist_ok=True)
    return path


def _output_root(req):
    return req.environ.get(
        "VAR_OUTPUT_ROOT",
        os.path.abspath(os.path.join(BASE_DIR, "..", "output"))
    )


# ── fall detection ────────────────────────────────────────────

def _detect_falls(frame_data):
    """
    Scan frame_data dict for sudden drops in cow center_y.
    Returns list of {"frame": int, "type": "fell"|"rising", "cy": float}.
    """
    events = []
    sorted_frames = sorted(frame_data.items(), key=lambda x: int(x[0]))

    cy_history = []      # [(frame_num, cy), ...]
    window     = 5
    in_fall    = False
    fall_cy    = None
    last_event = -FALL_COOLDOWN

    for frame_str, fdata in sorted_frames:
        frame_num = int(frame_str)
        cow = fdata.get("cow")
        if not cow:
            continue

        cy = cow["cy"]
        cy_history.append((frame_num, cy))

        if len(cy_history) < window + 1:
            continue

        prev_cys = [c for _, c in cy_history[-(window + 1):-1]]
        avg_prev = sum(prev_cys) / len(prev_cys)

        cooldown_ok = (frame_num - last_event) >= FALL_COOLDOWN

        if not in_fall and cooldown_ok:
            if cy - avg_prev > FALL_THRESHOLD:
                events.append({"frame": frame_num, "type": "fell", "cy": cy})
                in_fall   = True
                fall_cy   = cy
                last_event = frame_num

        elif in_fall and fall_cy is not None:
            if fall_cy - cy > RISING_THRESHOLD:
                events.append({"frame": frame_num, "type": "rising", "cy": cy})
                in_fall    = False
                fall_cy    = None
                last_event = frame_num

    return events


# ── YOLO background worker ────────────────────────────────────

def _process_video_yolo(job_id, video_path, output_root, model_path):
    try:
        JOBS[job_id] = {"status": "processing", "progress_pct": 0, "message": "Carregando modelo YOLO..."}

        from ultralytics import YOLO
        model = YOLO(model_path)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError("Não foi possível abrir o vídeo.")

        fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        JOBS[job_id]["message"] = f"Processando {total_frames} frames com YOLO..."

        frame_data = {}
        frame_num  = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = model(frame, verbose=False)[0]
            names   = results.names

            cow_box     = None
            horse_boxes = []

            for box in results.boxes:
                cls_id        = int(box.cls[0])
                label         = names[cls_id].lower()
                x1, y1, x2, y2 = map(float, box.xyxy[0])
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                entry = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": cx, "cy": cy}

                if label in COW_LABELS:
                    area = (x2 - x1) * (y2 - y1)
                    if cow_box is None or area > (cow_box["x2"] - cow_box["x1"]) * (cow_box["y2"] - cow_box["y1"]):
                        cow_box = entry
                elif label in HORSE_LABELS:
                    horse_boxes.append(entry)

            if cow_box is not None or horse_boxes:
                frame_data[str(frame_num)] = {"cow": cow_box, "horses": horse_boxes}

            frame_num += 1
            if frame_num % 30 == 0 or frame_num == total_frames:
                pct = int((frame_num / max(total_frames, 1)) * 100)
                JOBS[job_id].update({"progress_pct": pct, "message": f"Frame {frame_num}/{total_frames}..."})

        cap.release()

        JOBS[job_id]["message"] = "Detectando quedas..."
        fall_events = _detect_falls(frame_data)

        detections = {
            "fps":          fps,
            "total_frames": total_frames,
            "video_w":      video_w,
            "video_h":      video_h,
            "frames":       frame_data,
            "fall_events":  fall_events,
        }

        out_dir = _job_dir(output_root, job_id)
        with open(os.path.join(out_dir, "detections.json"), "w", encoding="utf-8") as f:
            json.dump(detections, f, ensure_ascii=False)

        JOBS[job_id] = {
            "status":       "completed",
            "progress_pct": 100,
            "message":      "Análise concluída!",
            "fps":          fps,
            "total_frames": total_frames,
            "video_w":      video_w,
            "video_h":      video_h,
            "fall_count":   len([e for e in fall_events if e["type"] == "fell"]),
        }

    except Exception as e:
        JOBS[job_id] = {"status": "error", "progress_pct": 0, "message": str(e)}


# ── POST /var/upload ─────────────────────────────────────────

@var_bp.route("/upload", methods=["POST"])
def var_upload():
    if "video" not in request.files:
        return jsonify({"error": "Campo 'video' não encontrado."}), 400

    file = request.files["video"]
    if not file.filename or not _allowed(file.filename):
        return jsonify({"error": "Formato não suportado."}), 400

    job_id     = str(uuid.uuid4())
    out_dir    = _job_dir(_output_root(request), job_id)
    ext        = file.filename.rsplit(".", 1)[1].lower()
    filename   = f"video.{ext}"
    video_path = os.path.join(out_dir, filename)
    file.save(video_path)

    with open(os.path.join(out_dir, "marks.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    model_path  = request.environ.get("MODEL_PATH",
                    os.path.join(BASE_DIR, "..", "models", "yolov8n.pt"))
    output_root = _output_root(request)

    JOBS[job_id] = {"status": "processing", "progress_pct": 0, "message": "Iniciando..."}
    threading.Thread(
        target=_process_video_yolo,
        args=(job_id, video_path, output_root, model_path),
        daemon=True,
    ).start()

    return jsonify({
        "job_id":     job_id,
        "video_url":  f"/var/download/{job_id}/{filename}",
        "status_url": f"/var/status/{job_id}",
    }), 201


# ── GET /var/status/<job_id> ─────────────────────────────────

@var_bp.route("/status/<job_id>", methods=["GET"])
def var_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job não encontrado."}), 404
    return jsonify(job)


# ── GET /var/download/<job_id>/<filename> ────────────────────

@var_bp.route("/download/<job_id>/<filename>", methods=["GET"])
def var_download(job_id, filename):
    out_dir   = _output_root(request)
    file_path = os.path.abspath(os.path.join(out_dir, job_id, filename))
    if not os.path.exists(file_path):
        return jsonify({"error": "Arquivo não encontrado."}), 404
    return send_file(file_path, mimetype="video/mp4", as_attachment=False)


# ── POST /var/lanes/<job_id> ─────────────────────────────────

@var_bp.route("/lanes/<job_id>", methods=["POST"])
def var_save_lanes(job_id):
    data    = request.get_json(silent=True) or {}
    y1      = data.get("y1")
    y2      = data.get("y2")
    video_h = data.get("video_h")

    if y1 is None or y2 is None:
        return jsonify({"error": "Campos obrigatórios: y1, y2"}), 400

    # Normalize so y1 is always the smaller value
    y1, y2 = (min(float(y1), float(y2)), max(float(y1), float(y2)))

    out_dir = _job_dir(_output_root(request), job_id)
    lanes   = {"y1": y1, "y2": y2, "video_h": video_h}

    with open(os.path.join(out_dir, "lanes.json"), "w", encoding="utf-8") as f:
        json.dump(lanes, f)

    return jsonify(lanes)


# ── GET /var/detections/<job_id> ─────────────────────────────

@var_bp.route("/detections/<job_id>", methods=["GET"])
def var_detections(job_id):
    out_dir  = _output_root(request)
    det_path = os.path.join(out_dir, job_id, "detections.json")

    if not os.path.exists(det_path):
        return jsonify({"error": "Detecções não encontradas."}), 404

    with open(det_path, encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


# ── POST /var/mark ───────────────────────────────────────────

@var_bp.route("/mark", methods=["POST"])
def var_mark():
    data     = request.get_json(silent=True) or {}
    job_id   = data.get("job_id")
    time_s   = data.get("time_s")
    decision = data.get("decision")

    if not job_id or time_s is None or decision not in ("VÁLIDO", "ZERO"):
        return jsonify({"error": "Campos obrigatórios: job_id, time_s, decision (VÁLIDO|ZERO)"}), 400

    out_dir    = _job_dir(_output_root(request), job_id)
    marks_path = os.path.join(out_dir, "marks.json")

    marks = []
    if os.path.exists(marks_path):
        with open(marks_path, encoding="utf-8") as f:
            marks = json.load(f)

    mark = {
        "id":       str(uuid.uuid4())[:8],
        "time_s":   round(float(time_s), 3),
        "decision": decision,
        "note":     data.get("note", ""),
    }
    marks.append(mark)
    marks.sort(key=lambda m: m["time_s"])

    with open(marks_path, "w", encoding="utf-8") as f:
        json.dump(marks, f, ensure_ascii=False, indent=2)

    return jsonify(mark), 201


# ── DELETE /var/mark/<job_id>/<mark_id> ──────────────────────

@var_bp.route("/mark/<job_id>/<mark_id>", methods=["DELETE"])
def var_delete_mark(job_id, mark_id):
    out_dir    = _job_dir(_output_root(request), job_id)
    marks_path = os.path.join(out_dir, "marks.json")

    if not os.path.exists(marks_path):
        return jsonify({"error": "Job não encontrado."}), 404

    with open(marks_path, encoding="utf-8") as f:
        marks = json.load(f)

    marks = [m for m in marks if m["id"] != mark_id]

    with open(marks_path, "w", encoding="utf-8") as f:
        json.dump(marks, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True})


# ── GET /var/marks/<job_id> ──────────────────────────────────

@var_bp.route("/marks/<job_id>", methods=["GET"])
def var_marks(job_id):
    out_dir    = _output_root(request)
    marks_path = os.path.join(out_dir, job_id, "marks.json")

    if not os.path.exists(marks_path):
        return jsonify({"error": "Job não encontrado."}), 404

    with open(marks_path, encoding="utf-8") as f:
        marks = json.load(f)

    return jsonify(marks)
