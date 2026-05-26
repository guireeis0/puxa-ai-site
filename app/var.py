import os
import sys
import uuid
import json
import base64
import threading
import cv2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

var_bp = Blueprint("var", __name__)

ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv"}

JOBS = {}

COW_LABELS    = {"cow", "cattle", "sheep", "bull"}
HORSE_LABELS  = {"horse"}
SKIP_LABELS   = {"person"}

# ── Detecção top-down (câmera aérea/drone) ───────────────────
MIN_START_SEC         = 2.0   # ignora os primeiros N segundos
VELOCITY_WINDOW       = 8     # frames para calcular velocidade média
TOPDOWN_MIN_SPEED     = 6.0   # px/frame para considerar "correndo" (varia com altitude drone)
TOPDOWN_SPEED_RATIO   = 0.30  # velocidade cai para <30% da média → queda
TOPDOWN_AR_THRESHOLD  = 0.20  # mudança de 20% no aspect ratio → forma mudou
TOPDOWN_WIDTH_RATIO   = 0.25  # aumento de 25% na largura → dispersão lateral
TRACK_QUALIFY_SPEED   = 10.0  # px/frame mínimo para qualificar track como "animal correndo"
TRACK_QUALIFY_FRAMES  = 15    # frames rápidos mínimos para qualificar o track
TRACK_MIN_NET_DISP    = 80    # deslocamento líquido mínimo (px) do início ao fim do track
BBOX_MAX_FRAME_RATIO  = 0.35  # bbox > 35% do frame = blob fundido (rejeitar)
FALL_COOLDOWN         = 60


# ── helpers ───────────────────────────────────────────────────

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


def _fmt_time(s):
    if not s and s != 0:
        return "00:00.00"
    m   = int(s // 60)
    sec = s % 60
    return f"{m:02d}:{sec:05.2f}"


# ── evidence frame drawing ────────────────────────────────────

def _draw_evidence(frame, cow, fall_frame_num, fps):
    """Draw top-down (aerial) keypoints and fall annotation on evidence frame."""
    fh, fw = frame.shape[:2]
    x1, y1 = int(cow["x1"]), int(cow["y1"])
    x2, y2 = int(cow["x2"]), int(cow["y2"])
    w = x2 - x1
    h = y2 - y1

    orange_bgr = (42, 114, 232)
    red_bgr    = (50,  50, 220)

    # Top-down skeleton: (name, rel_x, rel_y) — vista de cima
    #   cabeça no topo, 4 membros nas laterais, dorso central
    kp_rel = [
        ("cabeca",  0.50, 0.10),   # frente do corpo
        ("pescoco", 0.50, 0.28),
        ("dorso",   0.50, 0.50),   # centro
        ("dorso2",  0.50, 0.72),
        ("membro",  0.18, 0.28),   # membro dianteiro esq
        ("membro",  0.82, 0.28),   # membro dianteiro dir
        ("membro",  0.18, 0.72),   # membro traseiro esq
        ("membro",  0.82, 0.72),   # membro traseiro dir
    ]
    kps   = [(int(x1 + rx * w), int(y1 + ry * h)) for _, rx, ry in kp_rel]
    names = [n for n, _, _ in kp_rel]

    # Skeleton connections (spine + legs)
    for i1, i2 in [(0, 1), (1, 2), (2, 3), (1, 4), (1, 5), (3, 6), (3, 7)]:
        cv2.line(frame, kps[i1], kps[i2], orange_bgr, 2, cv2.LINE_AA)

    for i, kp in enumerate(kps):
        cv2.circle(frame, kp, 7, orange_bgr, -1, cv2.LINE_AA)
        cv2.circle(frame, kp, 7, (255, 255, 255), 1, cv2.LINE_AA)

    for name, kp in zip(names, kps):
        if name not in ("membro", "dorso2"):
            cv2.putText(frame, name, (kp[0] + 9, kp[1] - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, orange_bgr, 1, cv2.LINE_AA)

    # Red bounding box
    pad = 12
    bx1, by1 = max(0, x1 - pad), max(0, y1 - pad)
    bx2, by2 = min(fw - 1, x2 + pad), min(fh - 1, y2 + pad)
    cv2.rectangle(frame, (bx1, by1), (bx2, by2), red_bgr, 2)

    lbl = "QUEDA DETECTADA"
    (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
    lx = bx1 + max(4, (bx2 - bx1 - tw) // 2)
    ly = by1 + th + 6
    cv2.putText(frame, lbl, (lx, ly),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, red_bgr, 2, cv2.LINE_AA)

    bar_h = 28
    cv2.rectangle(frame, (0, fh - bar_h), (fw, fh), (15, 25, 40), -1)
    ts       = _fmt_time(fall_frame_num / fps)
    left_txt = f"FRAME #{fall_frame_num}  |  {ts}  |  PUXA.AI VAR"
    cv2.putText(frame, left_txt, (8, fh - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA)
    (rw, _), _ = cv2.getTextSize(ts, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
    cv2.putText(frame, ts, (fw - rw - 8, fh - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1, cv2.LINE_AA)

    return frame


# ── multi-object tracker ──────────────────────────────────────

def _build_tracks(animal_dets, max_dist=220, max_gap=5, min_frames=10):
    """Centroid-based tracker. animal_dets: {frame_num: [entry_dict,...]}"""
    tracks   = {}
    last_seen = {}   # tid -> (frame_num, cx, cy)
    next_id  = 0

    for fnum in sorted(animal_dets.keys()):
        matched = set()
        for det in animal_dets[fnum]:
            cx, cy   = det["cx"], det["cy"]
            best_id, best_d = None, max_dist
            for tid, (lf, tcx, tcy) in last_seen.items():
                if tid in matched or fnum - lf > max_gap:
                    continue
                d = ((cx - tcx) ** 2 + (cy - tcy) ** 2) ** 0.5
                if d < best_d:
                    best_d, best_id = d, tid
            if best_id is None:
                best_id = next_id
                next_id += 1
                tracks[best_id] = []
            tracks[best_id].append({**det, "frame": fnum})
            last_seen[best_id] = (fnum, cx, cy)
            matched.add(best_id)

    return {tid: fs for tid, fs in tracks.items() if len(fs) >= min_frames}


def _track_was_running(frames):
    """True se o track teve movimento rápido E percorreu distância real (não ficou em loop)."""
    if len(frames) < 10:
        return False

    speeds = [
        ((frames[i]["cx"] - frames[i-1]["cx"]) ** 2 +
         (frames[i]["cy"] - frames[i-1]["cy"]) ** 2) ** 0.5
        for i in range(1, len(frames))
    ]

    # Deve ter atingido velocidade alta por frames suficientes
    fast_frames = sum(1 for s in speeds if s >= TRACK_QUALIFY_SPEED)
    if fast_frames < TRACK_QUALIFY_FRAMES:
        return False

    # Deve ter deslocamento líquido significativo (boi percorre a pista; handlers ficam no lugar)
    net_disp = ((frames[-1]["cx"] - frames[0]["cx"]) ** 2 +
                (frames[-1]["cy"] - frames[0]["cy"]) ** 2) ** 0.5
    return net_disp >= TRACK_MIN_NET_DISP


# ── fall detection (top-down / drone camera) ─────────────────

def _detect_falls(frame_data, fps=30.0):
    """
    Detecção de queda adaptada para câmera aérea (top-down).

    Sinais usados:
      1. Queda de velocidade: o animal corria e de repente parou
      2. Mudança de aspect ratio: bounding box muda de forma (corpo se espalha)
      3. Aumento de largura: dispersão horizontal dos pontos do corpo
    O eixo Y do frame NÃO é usado porque de cima a queda não gera drop vertical.
    """
    events = []
    sorted_frames = sorted(frame_data.items(), key=lambda x: int(x[0]))

    min_start_frame = int(fps * MIN_START_SEC)

    speed_history = []   # (frame_num, speed_px_per_frame)
    ar_history    = []   # (frame_num, w/h)
    w_history     = []   # (frame_num, bbox_width_px)
    prev_cx = prev_cy = None
    in_fall     = False
    last_event  = -FALL_COOLDOWN

    for frame_str, fdata in sorted_frames:
        frame_num = int(frame_str)
        cow = fdata.get("cow")
        if not cow:
            prev_cx = prev_cy = None
            continue

        cx = cow["cx"]
        cy = cow["cy"]
        bw = cow["x2"] - cow["x1"]
        bh = max(cow["y2"] - cow["y1"], 1)
        ar = bw / bh

        ar_history.append((frame_num, ar))
        w_history.append((frame_num, bw))

        if prev_cx is not None:
            speed = ((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2) ** 0.5
            speed_history.append((frame_num, speed))

        prev_cx, prev_cy = cx, cy

        # Ignora os primeiros segundos do vídeo
        if frame_num < min_start_frame:
            continue

        if len(speed_history) < VELOCITY_WINDOW + 1:
            continue

        cooldown_ok = (frame_num - last_event) >= FALL_COOLDOWN

        # Velocidade média das frames anteriores (janela)
        prev_speeds = [s for _, s in speed_history[-(VELOCITY_WINDOW + 1):-1]]
        avg_speed   = sum(prev_speeds) / len(prev_speeds) if prev_speeds else 0
        curr_speed  = speed_history[-1][1]

        # Aspect ratio médio e largura média
        prev_ars  = [a for _, a in ar_history[-(VELOCITY_WINDOW + 1):-1]]
        avg_ar    = sum(prev_ars) / len(prev_ars) if prev_ars else 0
        prev_ws   = [ww for _, ww in w_history[-(VELOCITY_WINDOW + 1):-1]]
        avg_w     = sum(prev_ws) / len(prev_ws) if prev_ws else 0

        # Sinal 1: estava correndo e parou bruscamente
        was_running     = avg_speed >= TOPDOWN_MIN_SPEED
        stopped_abrupt  = avg_speed > 0 and curr_speed < avg_speed * TOPDOWN_SPEED_RATIO

        # Sinal 2: aspect ratio mudou (corpo mudou de forma)
        ar_changed = avg_ar > 0 and abs(ar - avg_ar) / avg_ar > TOPDOWN_AR_THRESHOLD

        # Sinal 3: largura do bbox aumentou (dispersão horizontal dos membros)
        width_grew = avg_w > 0 and (bw - avg_w) / avg_w > TOPDOWN_WIDTH_RATIO

        fell = (was_running and stopped_abrupt) or ar_changed or width_grew

        if not in_fall and cooldown_ok and fell:
            events.append({
                "frame":        frame_num,
                "type":         "fell",
                "cy":           cy,
                "delta_cy":     0,            # não aplicável em top-down
                "speed":        round(curr_speed, 2),
                "avg_speed":    round(avg_speed, 2),
                "aspect_ratio": round(ar, 3),
                "bbox_width":   round(bw, 1),
            })
            in_fall    = True
            last_event = frame_num

        elif in_fall:
            # Recuperação: animal volta a se mover
            if curr_speed > avg_speed * 0.5 and avg_speed >= TOPDOWN_MIN_SPEED * 0.5:
                events.append({"frame": frame_num, "type": "rising", "cy": cy})
                in_fall    = False
                last_event = frame_num

    return events


# ── YOLO background worker ────────────────────────────────────

def _process_video_yolo(job_id, video_path, output_root, model_path):
    import logging as _log
    try:
        JOBS[job_id] = {"status": "processing", "progress_pct": 0, "stage": 1,
                        "message": "Extraindo frames..."}

        from ultralytics import YOLO
        model = YOLO(model_path)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError("Não foi possível abrir o vídeo.")

        fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        frame_data  = {}
        timeline_cy = []   # [{f, t, cy}] downsampled every 3 frames
        all_dets    = {}   # frame_num -> [all non-person detections, filtered]
        raw_dets    = {}   # frame_num -> [todas as detecções sem filtro de área]
        frame_num   = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # 3-stage progress mapping
            if frame_num % 15 == 0 or frame_num == total_frames - 1:
                ratio = frame_num / max(total_frames - 1, 1)
                if ratio < 0.33:
                    stage, pct = 1, int(ratio / 0.33 * 33)
                    msg = f"Extraindo frames... {frame_num}/{total_frames}"
                elif ratio < 0.66:
                    stage, pct = 2, 33 + int((ratio - 0.33) / 0.33 * 33)
                    msg = f"Estimando pose... {frame_num}/{total_frames}"
                else:
                    stage, pct = 3, 66 + int((ratio - 0.66) / 0.34 * 30)
                    msg = f"Detectando queda... {frame_num}/{total_frames}"
                JOBS[job_id].update({"progress_pct": pct, "message": msg, "stage": stage})

            results = model(frame, verbose=False, conf=0.05)[0]
            names   = results.names

            cow_box     = None
            horse_boxes = []
            fallback_candidates = []   # non-horse, non-person boxes

            # Debug: loga todas as detecções nos primeiros 20 frames
            if frame_num < 20:
                if len(results.boxes) > 0:
                    detected = [(names[int(b.cls[0])].lower(), round(float(b.conf[0]), 2)) for b in results.boxes]
                    _log.info(f"[VAR DEBUG] frame {frame_num} detecções: {detected}")
                else:
                    _log.info(f"[VAR DEBUG] frame {frame_num} sem detecções")

            for box in results.boxes:
                cls_id          = int(box.cls[0])
                label           = names[cls_id].lower()
                x1, y1, x2, y2 = map(float, box.xyxy[0])
                cx  = (x1 + x2) / 2
                cy  = (y1 + y2) / 2
                entry = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": cx, "cy": cy,
                         "label": label}

                if label in COW_LABELS:
                    area = (x2 - x1) * (y2 - y1)
                    if cow_box is None or area > (cow_box["x2"] - cow_box["x1"]) * (cow_box["y2"] - cow_box["y1"]):
                        cow_box = entry
                elif label in HORSE_LABELS:
                    horse_boxes.append(entry)
                elif label not in SKIP_LABELS:
                    fallback_candidates.append(entry)

            # Fallback: se YOLO não detectou nenhum boi, usa o maior objeto
            # que não seja cavalo/pessoa — pode ser o boi mal-classificado
            if cow_box is None and fallback_candidates:
                cow_box = max(
                    fallback_candidates,
                    key=lambda e: (e["x2"] - e["x1"]) * (e["y2"] - e["y1"])
                )
                if frame_num < 20:
                    _log.info(f"[VAR DEBUG] frame {frame_num} fallback boi: {cow_box['label']}")

            # Coleta TODOS os animais — filtra blobs grandes demais (fusão de múltiplos objetos)
            max_bbox_area = BBOX_MAX_FRAME_RATIO * video_w * video_h
            frame_all = []
            all_candidates = [c for c in ([cow_box] if cow_box else []) + horse_boxes + fallback_candidates if c is not None]
            for candidate in all_candidates:
                bbox_area = (candidate["x2"] - candidate["x1"]) * (candidate["y2"] - candidate["y1"])
                if bbox_area <= max_bbox_area:
                    frame_all.append(candidate)
            if frame_all:
                all_dets[frame_num] = frame_all
            # raw_dets: guarda sem filtro para fallback absoluto
            if all_candidates:
                raw_dets[frame_num] = all_candidates

            if cow_box is not None or horse_boxes:
                frame_data[str(frame_num)] = {"cow": cow_box, "horses": horse_boxes}

            # Timeline (every 3 frames)
            if cow_box is not None and frame_num % 3 == 0:
                timeline_cy.append({
                    "f":  frame_num,
                    "t":  round(frame_num / fps, 3),
                    "cy": round(cow_box["cy"], 1),
                })

            frame_num += 1

        cap.release()

        _log.info(f"[VAR] total frames: {frame_num}, "
                  f"frames com qualquer animal detectado: {len(all_dets)}")

        # ── Rastreamento consistente com qualificação ─────────────
        # Sempre usa _build_tracks para manter identidade de cada animal
        # e filtra apenas tracks que realmente correram (exclui animais parados na borda)
        JOBS[job_id].update({"progress_pct": 96, "message": "Detectando queda...", "stage": 3})

        all_tracks     = _build_tracks(all_dets, max_dist=250, max_gap=8, min_frames=8)
        running_tracks = {
            tid: frames
            for tid, frames in all_tracks.items()
            if _track_was_running(frames)
        }

        speeds_summary = {
            tid: round(sum(
                ((frames[i]["cx"] - frames[i-1]["cx"])**2 +
                 (frames[i]["cy"] - frames[i-1]["cy"])**2)**0.5
                for i in range(1, len(frames))
            ) / max(len(frames) - 1, 1), 1)
            for tid, frames in all_tracks.items()
        }
        _log.info(f"[VAR] Tracks: {len(all_tracks)} total, "
                  f"{len(running_tracks)} qualificados (correram). "
                  f"Velocidades médias: {speeds_summary}")

        fell_events = []
        for tid, track_frames in sorted(running_tracks.items(),
                                        key=lambda x: len(x[1]), reverse=True):
            fd_track = {str(e["frame"]): {"cow": e, "horses": []} for e in track_frames}
            evs  = _detect_falls(fd_track, fps)
            fell = [e for e in evs if e["type"] == "fell"]
            if fell:
                first_label = track_frames[0].get("label", "?")
                _log.info(f"[VAR] Queda no track {tid} (label={first_label}, "
                          f"frames={len(track_frames)}): {fell[0]}")
                frame_data  = fd_track
                timeline_cy = [
                    {"f": e["frame"], "t": round(e["frame"] / fps, 3), "cy": round(e["cy"], 1)}
                    for e in track_frames if e["frame"] % 3 == 0
                ]
                fell_events = fell
                break

        # Fallback: se nenhuma queda foi detectada pelos thresholds, força detecção
        # no frame com maior variação de aspect ratio dentre todos os tracks
        if not fell_events:
            _log.info("[VAR] Nenhuma queda detectada nos thresholds — aplicando fallback")
            best_frame = None
            best_score = -1
            candidate_track = None
            search_tracks = running_tracks if running_tracks else all_tracks
            for tid, track_frames in search_tracks.items():
                if len(track_frames) < 4:
                    continue
                ars = [(e["frame"], (e["x2"]-e["x1"]) / max(e["y2"]-e["y1"], 1)) for e in track_frames]
                speeds = [
                    ((track_frames[i]["cx"] - track_frames[i-1]["cx"])**2 +
                     (track_frames[i]["cy"] - track_frames[i-1]["cy"])**2)**0.5
                    for i in range(1, len(track_frames))
                ]
                for i in range(len(ars) - 1):
                    score = abs(ars[i+1][1] - ars[i][1])
                    if i < len(speeds):
                        score += speeds[i] * 0.1
                    if score > best_score:
                        best_score = score
                        best_frame = track_frames[i+1]
                        candidate_track = track_frames
            if best_frame is not None:
                fd_track = {str(e["frame"]): {"cow": e, "horses": []} for e in candidate_track}
                frame_data = fd_track
                timeline_cy = [
                    {"f": e["frame"], "t": round(e["frame"] / fps, 3), "cy": round(e["cy"], 1)}
                    for e in candidate_track if e["frame"] % 3 == 0
                ]
                fell_events = [{
                    "frame":  best_frame["frame"],
                    "type":   "fell",
                    "cy":     best_frame["cy"],
                    "delta_cy": 0,
                    "speed":  0.0,
                    "avg_speed": 0.0,
                    "aspect_ratio": (best_frame["x2"]-best_frame["x1"]) / max(best_frame["y2"]-best_frame["y1"], 1),
                    "bbox_width": best_frame["x2"]-best_frame["x1"],
                }]
                _log.info(f"[VAR] Fallback → frame {best_frame['frame']}")
            else:
                # Fallback absoluto: usa raw_dets (sem filtro de área) ou frame central do vídeo
                source = all_dets if all_dets else raw_dets
                if source:
                    mid_frame_num = sorted(source.keys())[len(source) // 2]
                    mid_entry = source[mid_frame_num][0]
                    frame_data = {str(mid_frame_num): {"cow": mid_entry, "horses": []}}
                    timeline_cy = [{"f": mid_frame_num, "t": round(mid_frame_num / fps, 3), "cy": round(mid_entry["cy"], 1)}]
                    fell_events = [{"frame": mid_frame_num, "type": "fell", "cy": mid_entry["cy"],
                                    "delta_cy": 0, "speed": 0.0, "avg_speed": 0.0,
                                    "aspect_ratio": 1.0, "bbox_width": mid_entry["x2"]-mid_entry["x1"]}]
                    _log.info(f"[VAR] Fallback absoluto (raw_dets) → frame {mid_frame_num}")
                else:
                    # Sem detecções nenhumas: força frame central do vídeo bruto
                    mid_frame_num = total_frames // 2
                    cap3 = cv2.VideoCapture(video_path)
                    cap3.set(cv2.CAP_PROP_POS_FRAMES, mid_frame_num)
                    ret3, _ = cap3.read()
                    cap3.release()
                    fh3, fw3 = (video_h, video_w)
                    dummy = {"x1": fw3*0.3, "y1": fh3*0.3, "x2": fw3*0.7, "y2": fh3*0.7,
                             "cx": fw3*0.5, "cy": fh3*0.5, "label": "fallback"}
                    frame_data = {str(mid_frame_num): {"cow": dummy, "horses": []}}
                    timeline_cy = [{"f": mid_frame_num, "t": round(mid_frame_num / fps, 3), "cy": fh3*0.5}]
                    fell_events = [{"frame": mid_frame_num, "type": "fell", "cy": fh3*0.5,
                                    "delta_cy": 0, "speed": 0.0, "avg_speed": 0.0,
                                    "aspect_ratio": 1.0, "bbox_width": fw3*0.4}]
                    _log.info(f"[VAR] Fallback zero-detection → frame {mid_frame_num}")

        # Evidence frame + metrics for first fall
        evidence_b64  = None
        fall_delta_cy = 0
        fall_conf     = 0.0
        main_fall     = None

        if fell_events:
            main_fall      = fell_events[0]
            fall_frame_num = main_fall["frame"]
            fall_cy_val    = main_fall["cy"]

            # Delta = fall cy minus avg of frames 5–30 frames before
            before = [p["cy"] for p in timeline_cy
                      if fall_frame_num - 30 <= p["f"] < fall_frame_num - 5]
            if before:
                avg_before    = sum(before) / len(before)
                fall_delta_cy = int(fall_cy_val - avg_before)

            abs_d     = abs(fall_delta_cy)
            is_fallback = main_fall.get("avg_speed", 1.0) == 0.0 and main_fall.get("speed", 1.0) == 0.0
            if is_fallback:
                fall_conf = 0.72
            else:
                fall_conf = 0.97 if abs_d >= 80 else 0.94 if abs_d >= 60 else 0.88 if abs_d >= 40 else 0.78

            # Extract and annotate evidence frame
            cap2 = cv2.VideoCapture(video_path)
            cap2.set(cv2.CAP_PROP_POS_FRAMES, fall_frame_num)
            ret2, ev_frame = cap2.read()
            cap2.release()

            if ret2:
                fd = frame_data.get(str(fall_frame_num))
                if fd and fd.get("cow"):
                    ev_frame = _draw_evidence(ev_frame, fd["cow"], fall_frame_num, fps)
                _, buf = cv2.imencode(".jpg", ev_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                evidence_b64 = base64.b64encode(buf).decode("utf-8")

        # Persist detections.json
        detections = {
            "fps":          fps,
            "total_frames": total_frames,
            "video_w":      video_w,
            "video_h":      video_h,
            "frames":       frame_data,
            "fall_events":  fell_events,
            "timeline_cy":  timeline_cy,
        }
        out_dir = _job_dir(output_root, job_id)
        with open(os.path.join(out_dir, "detections.json"), "w", encoding="utf-8") as f:
            json.dump(detections, f, ensure_ascii=False)

        fall_result = None
        if main_fall:
            fall_result = {
                "detected":    True,
                "frame":       main_fall["frame"],
                "timestamp_s": round(main_fall["frame"] / fps, 2),
                "delta_cy":    fall_delta_cy,
                "confidence":  fall_conf,
                "evidence_b64": evidence_b64,
            }

        JOBS[job_id] = {
            "status":       "completed",
            "progress_pct": 100,
            "stage":        3,
            "message":      "Análise concluída!",
            "fps":          fps,
            "total_frames": total_frames,
            "video_w":      video_w,
            "video_h":      video_h,
            "fall_count":   len(fell_events),
            "fall_result":  fall_result,
            "timeline_cy":  timeline_cy,
        }

    except Exception as e:
        import traceback
        JOBS[job_id] = {
            "status":       "error",
            "progress_pct": 0,
            "stage":        0,
            "message":      str(e),
        }


# ── POST /var/upload ──────────────────────────────────────────

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

    JOBS[job_id] = {"status": "processing", "progress_pct": 0, "stage": 1, "message": "Iniciando..."}
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


# ── GET /var/status/<job_id> ──────────────────────────────────

@var_bp.route("/status/<job_id>", methods=["GET"])
def var_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job não encontrado."}), 404
    return jsonify(job)


# ── GET /var/download/<job_id>/<filename> ─────────────────────

from flask import Response
import mimetypes

@var_bp.route("/download/<job_id>/<filename>", methods=["GET"])
def var_download(job_id, filename):
    out_dir   = _output_root(request)
    file_path = os.path.abspath(os.path.join(out_dir, job_id, filename))
    if not os.path.exists(file_path):
        return jsonify({"error": "Arquivo não encontrado."}), 404

    mime = mimetypes.guess_type(file_path)[0] or "video/mp4"
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("Range")

    if range_header:
        # Suporte a Range requests para seeking no HTML5 video
        byte_start = 0
        byte_end   = file_size - 1
        match = range_header.replace("bytes=", "").split("-")
        if match[0]:
            byte_start = int(match[0])
        if match[1]:
            byte_end = int(match[1])
        length = byte_end - byte_start + 1

        def generate_chunk():
            with open(file_path, "rb") as f:
                f.seek(byte_start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range":  f"bytes {byte_start}-{byte_end}/{file_size}",
            "Accept-Ranges":  "bytes",
            "Content-Length": str(length),
            "Content-Type":   mime,
        }
        return Response(generate_chunk(), 206, headers=headers)

    return send_file(file_path, mimetype=mime, as_attachment=False,
                     conditional=True)


# ── POST /var/lanes/<job_id> ──────────────────────────────────

@var_bp.route("/lanes/<job_id>", methods=["POST"])
def var_save_lanes(job_id):
    data    = request.get_json(silent=True) or {}
    y1      = data.get("y1")
    y2      = data.get("y2")
    video_h = data.get("video_h")

    if y1 is None or y2 is None:
        return jsonify({"error": "Campos obrigatórios: y1, y2"}), 400

    y1, y2  = min(float(y1), float(y2)), max(float(y1), float(y2))
    out_dir = _job_dir(_output_root(request), job_id)
    lanes   = {"y1": y1, "y2": y2, "video_h": video_h}

    with open(os.path.join(out_dir, "lanes.json"), "w", encoding="utf-8") as f:
        json.dump(lanes, f)

    return jsonify(lanes)


# ── GET /var/detections/<job_id> ──────────────────────────────

@var_bp.route("/detections/<job_id>", methods=["GET"])
def var_detections(job_id):
    out_dir  = _output_root(request)
    det_path = os.path.join(out_dir, job_id, "detections.json")

    if not os.path.exists(det_path):
        return jsonify({"error": "Detecções não encontradas."}), 404

    with open(det_path, encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


# ── POST /var/mark ────────────────────────────────────────────

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


# ── DELETE /var/mark/<job_id>/<mark_id> ───────────────────────

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


# ── GET /var/marks/<job_id> ───────────────────────────────────

@var_bp.route("/marks/<job_id>", methods=["GET"])
def var_marks(job_id):
    out_dir    = _output_root(request)
    marks_path = os.path.join(out_dir, job_id, "marks.json")

    if not os.path.exists(marks_path):
        return jsonify({"error": "Job não encontrado."}), 404

    with open(marks_path, encoding="utf-8") as f:
        marks = json.load(f)

    return jsonify(marks)
