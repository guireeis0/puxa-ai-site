import os
import csv
import cv2
from ultralytics import YOLO

from hud import draw_corner_box, draw_hud
from speed import SpeedTracker
from config import (
    MODEL_PATH,
    MAX_REAL_SPEED_KMH, SMOOTHING,
    REACQUIRE_MAX_DIST_PX, MIN_BOX_AREA, HORSE_LENGTH_METERS,
    SCALE_EMA_ALPHA, SCALE_MIN, SCALE_MAX, SCALE_JUMP_MAX_RATIO,
    START_OK_HOLD_FRAMES, LOST_END_SECONDS, MIN_RUN_SECONDS,
    MIN_RUN_DISTANCE_M, MOVEMENT_MIN_SPEED_KMH, MOVEMENT_HOLD_FRAMES,
    PISTA_LIMIT_M, LOCK_ID, UNLOCK_AFTER_LOST_SECONDS,
    HUD_BOX_EMA_ALPHA, HUD_VALUE_EMA_ALPHA, HUD_UPDATE_EVERY_N_FRAMES,
)


def euclid(p1, p2):
    dx = float(p1[0] - p2[0])
    dy = float(p1[1] - p2[1])
    return (dx * dx + dy * dy) ** 0.5


def find_horse_class_id(model):
    for k, v in model.names.items():
        if str(v).lower() == "horse":
            return int(k)
    return 17


# Carrega o modelo uma única vez no startup
_MODEL = YOLO(MODEL_PATH)
_HORSE_CLS = find_horse_class_id(_MODEL)


def _ema(prev, new, alpha: float):
    if prev is None:
        return new
    return (1.0 - alpha) * prev + alpha * new


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def process_video(video_path: str, job_id: str, base_output: str = "output", status_callback=None):
    # Agora usamos o base_output vindo do api.py para evitar conflito de pastas
    out_dir = os.path.abspath(os.path.join(base_output, str(job_id)))
    os.makedirs(out_dir, exist_ok=True)

    output_video = os.path.join(out_dir, "resultado.mp4")
    output_csv = os.path.join(out_dir, "metrics.csv")
    output_summary = os.path.join(out_dir, "summary.csv")
    
    if status_callback: status_callback("IA: Preparando ambiente...")
    model = _MODEL
    horse_cls = _HORSE_CLS

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Erro ao abrir vídeo: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1 or fps > 240:
        fps = 30.0
    fps = float(fps)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    writer = cv2.VideoWriter(
        output_video,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    csv_file = open(output_csv, "w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["frame", "tempo_s", "speed_kmh", "accel_m_s2", "time_to_max_speed_s", "status", "track_id", "cx", "cy"])

    last_center = None
    pixel_to_meter = None
    spd = SpeedTracker(MAX_REAL_SPEED_KMH, SMOOTHING)

    frame_id = 0
    started = False
    start_ok_hold = 0
    start_time_s = None
    end_time_s = None
    lost_counter = 0
    movement_confirmed = False
    movement_hold = 0
    lost_end_frames = max(1, int(LOST_END_SECONDS * fps))

    locked_track_id = None
    unlock_after_lost_frames = max(1, int(UNLOCK_AFTER_LOST_SECONDS * fps))
    lock_lost_counter = 0

    sm_box = None
    hud_speed = None
    hud_accel = None
    hud_max_speed = None
    tempo = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if status_callback and frame_id % 20 == 0:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            pct = int((frame_id / total_frames) * 100) if total_frames > 0 else 0
            status_callback(f"IA: Analisando frame {frame_id}/{total_frames} ({pct}%)")

        tempo = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0

        results = model.track(
            frame,
            persist=True,
            classes=[horse_cls],
            conf=0.35,
            iou=0.5,
            verbose=False,
        )

        box_to_draw = None
        cur_pos = None
        status = "lost"
        candidates = []
        cur_track_id = None

        if results and len(results) > 0:
            boxes = results[0].boxes
            if boxes is not None and boxes.xyxy is not None and len(boxes.xyxy) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                ids = None
                try:
                    if getattr(boxes, "id", None) is not None:
                        ids = boxes.id.cpu().numpy()
                except Exception:
                    ids = None

                for i in range(len(xyxy)):
                    x1, y1, x2, y2 = xyxy[i]
                    area = float((x2 - x1) * (y2 - y1))
                    if area < MIN_BOX_AREA:
                        continue

                    cx, cy = float((x1 + x2) / 2.0), float((y1 + y2) / 2.0)
                    tid = int(ids[i]) if ids is not None and i < len(ids) else None
                    candidates.append(((float(x1), float(y1), float(x2), float(y2)), (cx, cy), area, tid))

        if candidates:
            chosen = None
            if LOCK_ID and locked_track_id is not None:
                same_id = [c for c in candidates if c[3] == locked_track_id]
                if same_id:
                    same_id.sort(key=lambda x: x[2], reverse=True)
                    chosen = same_id[0]
                    lock_lost_counter = 0
                else:
                    lock_lost_counter += 1
                    if lock_lost_counter >= unlock_after_lost_frames:
                        locked_track_id = None

            if chosen is None:
                if last_center is None:
                    candidates.sort(key=lambda x: x[2], reverse=True)
                    chosen = candidates[0]
                else:
                    candidates.sort(key=lambda x: (euclid(x[1], last_center), -x[2]))
                    cand = candidates[0]
                    if euclid(cand[1], last_center) <= REACQUIRE_MAX_DIST_PX:
                        chosen = cand

            if chosen is not None:
                box_to_draw, cur_pos, _, cur_track_id = chosen
                status = "ok"
                if LOCK_ID and locked_track_id is None and cur_track_id is not None:
                    locked_track_id = cur_track_id

        if not started:
            if status == "ok":
                start_ok_hold += 1
            else:
                start_ok_hold = 0

            if start_ok_hold >= START_OK_HOLD_FRAMES:
                started = True
                start_time_s = tempo
                spd.movement_start_time = float(start_time_s)
            else:
                continue

       # --- ESCALA DINÂMICA (Perspectiva e Profundidade) ---
        if box_to_draw is not None:
            x1, y1, x2, y2 = box_to_draw
            horse_pixels = float(x2 - x1)
            
            if horse_pixels > 5.0:
                # 1. Cálculo base (Metros por Pixel)
                raw_scale = HORSE_LENGTH_METERS / horse_pixels
                
                # 2. Compensação de Perspectiva
                # h_ref garante que não dividamos por zero. y2/height nos diz quão "fundo" o cavalo está.
                h_ref = height if height > 0 else 1080
                # O fator 0.35 (35%) ajusta a escala para que o cavalo não pareça "lento" no fundo da pista
                depth_factor = 1.0 + ((y2 / h_ref) * 0.35)
                new_scale = _clamp(raw_scale * depth_factor, SCALE_MIN, SCALE_MAX)
                
                # 3. Trava de Segurança (Evita saltos bruscos se a caixa do YOLO falhar)
                if pixel_to_meter is not None:
                    ratio = new_scale / pixel_to_meter
                    if ratio > SCALE_JUMP_MAX_RATIO or ratio < (1.0 / SCALE_JUMP_MAX_RATIO):
                        new_scale = pixel_to_meter
                
                # 4. Suavização da Régua (EMA)
                pixel_to_meter = float(_ema(pixel_to_meter, new_scale, SCALE_EMA_ALPHA))

        # --- CONTROLE DE DISTÂNCIA REAL ---
        old_dist = spd.total_distance
        speed_kmh, accel = spd.update(cur_pos, tempo, pixel_to_meter)
        
        if cur_pos is not None:
            last_center = cur_pos

        # Se não houver movimento real ou track perdido, não acumula distância
        is_moving = float(speed_kmh) >= MOVEMENT_MIN_SPEED_KMH
        if not (is_moving and status == "ok" and started):
            spd.total_distance = old_dist

        spd.total_distance = min(spd.total_distance, PISTA_LIMIT_M)

        # --- CONFIRMAÇÃO DE MOVIMENTO ---
        if not movement_confirmed:
            if (status == "ok") and (float(speed_kmh) >= MOVEMENT_MIN_SPEED_KMH):
                movement_hold += 1
            else:
                movement_hold = 0
            if movement_hold >= MOVEMENT_HOLD_FRAMES:
                movement_confirmed = True

        lost_counter = 0 if status == "ok" else lost_counter + 1
        elapsed = (tempo - start_time_s) if start_time_s is not None else 0.0
        min_ok = (elapsed >= MIN_RUN_SECONDS and float(spd.total_distance) >= MIN_RUN_DISTANCE_M and movement_confirmed)

       # --- HUD E GRAVAÇÃO (Versão Estabilizada) ---
        if box_to_draw is not None:
            # Suaviza o movimento da caixa (Bounding Box) para não tremer no vídeo
            sm_box = box_to_draw if sm_box is None else (
                _ema(sm_box[0], box_to_draw[0], HUD_BOX_EMA_ALPHA),
                _ema(sm_box[1], box_to_draw[1], HUD_BOX_EMA_ALPHA),
                _ema(sm_box[2], box_to_draw[2], HUD_BOX_EMA_ALPHA),
                _ema(sm_box[3], box_to_draw[3], HUD_BOX_EMA_ALPHA),
            )

        # Atualiza os números do HUD de forma suave (mais legível para o cliente)
        if (frame_id % max(1, HUD_UPDATE_EVERY_N_FRAMES)) == 0:
            hud_speed = float(_ema(hud_speed, float(speed_kmh), HUD_VALUE_EMA_ALPHA))
            hud_accel = float(_ema(hud_accel, float(accel), HUD_VALUE_EMA_ALPHA))
            hud_max_speed = float(_ema(hud_max_speed, float(spd.max_speed), HUD_VALUE_EMA_ALPHA))

        # Variáveis de exibição seguras (evitam valores None no vídeo)
        display_speed = hud_speed if hud_speed is not None else float(speed_kmh)
        display_accel = hud_accel if hud_accel is not None else float(accel)
        display_max = hud_max_speed if hud_max_speed is not None else float(spd.max_speed)

        # Lógica de encerramento da prova
        ending_now = (min_ok and (lost_counter >= lost_end_frames))
        
        # Gravação das métricas reais no CSV (para os gráficos do relatório)
        csv_writer.writerow([
            frame_id,
            f"{tempo:.3f}",
            f"{float(speed_kmh):.3f}",
            f"{float(accel):.3f}",
            f"{float(spd.time_to_max_speed):.3f}",
            "ended_lost" if ending_now else status,
            str(cur_track_id) or "",
            f"{cur_pos[0]:.1f}" if cur_pos else "",
            f"{cur_pos[1]:.1f}" if cur_pos else "",
        ])

        # Desenho no Frame
        if box_to_draw is not None and sm_box is not None:
            sx1, sy1, sx2, sy2 = sm_box
            draw_corner_box(frame, sx1, sy1, sx2, sy2, style="simple")
            # Agora usamos os valores estabilizados para um vídeo profissional
            draw_hud(frame, sx1, sy1, display_speed, display_accel, display_max)

        writer.write(frame)
        frame_id += 1
        
        if ending_now:
            end_time_s = tempo
            break

    # --- ENCERRAMENTO E LIMPEZA ---
    cap.release()
    writer.release()
    csv_file.close()

    # summary time
    if start_time_s is not None and end_time_s is not None:
        total_time = max(0.001, end_time_s - start_time_s)
    elif start_time_s is not None:
        total_time = max(0.001, tempo - start_time_s)
    else:
        total_time = max(0.001, tempo)

    avg_speed_kmh = (float(spd.total_distance) / float(total_time)) * 3.6
    efficiency_percent = (avg_speed_kmh / float(spd.max_speed)) * 100.0 if float(spd.max_speed) > 0 else 0.0

    # ✅ IMPULSÃO (robusta): percentil 95 das acelerações positivas (m/s²)
    impulse_m_s2 = 0.0
    try:
        impulse_m_s2 = float(spd.impulse_m_s2())
    except Exception:
        impulse_m_s2 = 0.0

    with open(output_summary, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "max_speed_kmh",
            "avg_speed_kmh",
            "max_accel_m_s2",
            "impulse_m_s2",
            "time_to_max_speed_s",
            "total_distance_m",
            "efficiency_percent",
            "start_time_s",
            "end_time_s",
            "run_time_s",
            "locked_track_id",
        ])
        w.writerow([
            round(float(spd.max_speed), 3),
            round(float(avg_speed_kmh), 3),
            round(float(spd.max_accel), 3),
            round(float(impulse_m_s2), 3),
            round(float(spd.time_to_max_speed), 3),
            round(float(spd.total_distance), 3),
            round(float(efficiency_percent), 3),
            round(float(start_time_s) if start_time_s is not None else 0.0, 3),
            round(float(end_time_s) if end_time_s is not None else 0.0, 3),
            round(float(total_time), 3),
            str(locked_track_id) if locked_track_id is not None else "",
        ])

    return {
        "video_width": width,
        "video_height": height,
        "max_speed": round(float(spd.max_speed), 2),
        "max_accel": round(float(spd.max_accel), 2),
        "impulse_m_s2": round(float(impulse_m_s2), 2),
        "avg_speed": round(float(avg_speed_kmh), 2),
        "distance": round(float(spd.total_distance), 2),
        "efficiency_percent": round(min(efficiency_percent, 100.0), 1),
        "time_to_max_speed": round(float(spd.time_to_max_speed), 2),
        "start_time_s": round(float(start_time_s) if start_time_s is not None else 0.0, 3),
        "end_time_s": round(float(end_time_s) if end_time_s is not None else 0.0, 3),
        "run_time_s": round(float(total_time), 3),
        "locked_track_id": locked_track_id,
        "output_dir": out_dir,
    }