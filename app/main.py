"""
Motor de performance: tracking do cavalo + cinemática.

Passada 1 (análise): YOLO + tracking, movimento da câmera e cortes de cena por frame.
Cinemática offline (kinematics.py): velocidade/aceleração sem atraso, régua robusta, fases.
Passada 2 (vídeo): desenha a caixa e o HUD já com os valores finais.
"""
import os
import csv

import cv2
import numpy as np
from ultralytics import YOLO

from hud import draw_corner_box, draw_hud
from camera_motion import CameraMotion, apply as cam_apply, IDENTITY
from kinematics import solve, summarize
from config import (
    MODEL_PATH, DETECT_CONF, DETECT_IMGSZ, DETECT_IMGSZ_LARGE, DETECT_LARGE_MIN_W, MIN_BOX_AREA,
    REACQUIRE_MAX_DIST_PX, REACQUIRE_BOX_FRAC,
    LOCK_ID, UNLOCK_AFTER_LOST_SECONDS, START_OK_HOLD_FRAMES, LOST_END_SECONDS,
    SCENE_CUT_THRESHOLD, HUD_BOX_EMA_ALPHA, HORSE_LENGTH_METERS,
)

# O YOLOv8n às vezes rotula cavalo como cachorro/ovelha/zebra entre um frame e outro.
# Aceitamos essas classes como "cavalo possível" (com preferência por horse no travamento).
# "cow" fica de fora de propósito: na vaquejada é o boi.
HORSE_LIKE = ("horse", "dog", "sheep", "zebra")
# Boi e vaqueiros correm junto com o cavalo: não são candidatos, mas precisam sair do cálculo
# do movimento da câmera (senão "puxam" a estimativa para câmera parada).
MOVING_OTHERS = ("cow", "person")


def euclid(p1, p2):
    return float(np.hypot(p1[0] - p2[0], p1[1] - p2[1]))


def _class_ids(model):
    names = {str(v).lower(): int(k) for k, v in model.names.items()}
    horse_like = {names[c] for c in HORSE_LIKE if c in names}
    others = {names[c] for c in MOVING_OTHERS if c in names}
    return horse_like, sorted(horse_like | others), names.get("horse", 17)


_MODEL = YOLO(MODEL_PATH)
_HORSE_LIKE_IDS, _CLASSES, _HORSE_CLS = _class_ids(_MODEL)


def _ema(prev, new, alpha: float):
    return new if prev is None else (1.0 - alpha) * prev + alpha * new


class SceneCutDetector:
    """Corte de câmera = queda brusca de correlação entre histogramas HSV de frames seguidos."""

    def __init__(self):
        self.prev = None

    def update(self, frame) -> bool:
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        hist = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        prev, self.prev = self.prev, hist
        return prev is not None and cv2.compareHist(prev, hist, cv2.HISTCMP_CORREL) < SCENE_CUT_THRESHOLD


def _phase_at(phases, t):
    for ph in phases:
        if ph["inicio_s"] <= t <= ph["inicio_s"] + ph["duracao_s"]:
            return ph["fase"]
    return ""


def process_video(video_path: str, job_id: str, base_output: str = "output", status_callback=None):
    out_dir = os.path.abspath(os.path.join(base_output, str(job_id)))
    os.makedirs(out_dir, exist_ok=True)
    output_video = os.path.join(out_dir, "resultado.mp4")
    output_csv = os.path.join(out_dir, "metrics.csv")
    output_summary = os.path.join(out_dir, "summary.csv")

    if status_callback:
        status_callback("IA: Preparando ambiente...")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Erro ao abrir vídeo: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    if fps <= 1 or fps > 240:
        fps = 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    imgsz = DETECT_IMGSZ_LARGE if width >= DETECT_LARGE_MIN_W else DETECT_IMGSZ
    cam = CameraMotion(width, height, video_path)
    cuts = SceneCutDetector()

    # ── Passada 1: tracking ──────────────────────────────────────────────────
    T, POS, BOX, CAMS, CUT, STATUS, TID = [], [], [], [], [], [], []
    last_center, last_box = None, None
    locked_track_id, lock_lost = None, 0
    unlock_after = max(1, int(UNLOCK_AFTER_LOST_SECONDS * fps))
    started, start_hold, lost_run = False, 0, 0
    lost_end_frames = max(1, int(LOST_END_SECONDS * fps))
    frame_id = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if status_callback and frame_id % 20 == 0:
            pct = int(frame_id / total_frames * 100) if total_frames > 0 else 0
            status_callback(f"IA: Analisando frame {frame_id}/{total_frames} ({pct}%)")
        t = frame_id / fps

        results = _MODEL.track(frame, persist=True, classes=_CLASSES, conf=DETECT_CONF, iou=0.5,
                               imgsz=imgsz, verbose=False)
        candidates, moving_boxes = [], []
        if results and results[0].boxes is not None and len(results[0].boxes) > 0:
            b = results[0].boxes
            xyxy = b.xyxy.cpu().numpy()
            cls = b.cls.cpu().numpy().astype(int)
            # int() nativo: o ID vai para o JSON da API (int64 do NumPy não serializa)
            ids = [int(v) for v in b.id.cpu().numpy()] if getattr(b, "id", None) is not None else [None] * len(xyxy)
            for (x1, y1, x2, y2), c, tid in zip(xyxy, cls, ids):
                box = (float(x1), float(y1), float(x2), float(y2))
                moving_boxes.append(box)
                area = float((x2 - x1) * (y2 - y1))
                if c in _HORSE_LIKE_IDS and area >= MIN_BOX_AREA:
                    candidates.append((box, ((x1 + x2) / 2.0, (y1 + y2) / 2.0), area, tid, c == _HORSE_CLS))

        # câmera e corte de cena
        is_cut = cuts.update(frame) and frame_id > 0
        if is_cut:
            cam.reset()
            cam.update(frame, moving_boxes, None)   # reinicia a referência do fluxo óptico
            A = IDENTITY.copy()
            last_center = None                      # posição antiga não vale na cena nova
        else:
            A = cam.update(frame, moving_boxes, last_box)[0]
        # A = None: movimento da câmera desconhecido neste frame (fluxo óptico sem pontos suficientes)
        if not is_cut and A is not None and last_center is not None:
            last_center = tuple(cam_apply(A, last_center))

        # escolha do cavalo (lock por ID do tracker, depois proximidade)
        chosen = None
        if candidates:
            if LOCK_ID and locked_track_id is not None:
                same = [c for c in candidates if c[3] == locked_track_id]
                if same:
                    chosen, lock_lost = max(same, key=lambda c: c[2]), 0
                else:
                    lock_lost += 1
                    if lock_lost >= unlock_after:
                        locked_track_id = None
            if chosen is None:
                if last_center is None:
                    # primeiro travamento: prefere caixas rotuladas como cavalo, depois a maior
                    chosen = max(candidates, key=lambda c: (c[4], c[2]))
                else:
                    radius = REACQUIRE_MAX_DIST_PX
                    if last_box is not None:
                        radius = max(radius, REACQUIRE_BOX_FRAC * (last_box[2] - last_box[0]))
                    near = min(candidates, key=lambda c: (euclid(c[1], last_center), -c[2]))
                    if euclid(near[1], last_center) <= radius:
                        chosen = near
            if chosen is not None and LOCK_ID and locked_track_id is None and chosen[3] is not None:
                locked_track_id = chosen[3]

        status = "ok" if chosen is not None else "lost"
        if chosen is not None:
            last_center, last_box = chosen[1], chosen[0]

        # início: detecção estável; fim: cavalo sumido por LOST_END_SECONDS depois de começar
        if not started:
            start_hold = start_hold + 1 if status == "ok" else 0
            started = start_hold >= START_OK_HOLD_FRAMES
        lost_run = 0 if status == "ok" else lost_run + 1

        T.append(t)
        POS.append(chosen[1] if chosen else (np.nan, np.nan))
        BOX.append(chosen[0] if chosen else (np.nan,) * 4)
        CAMS.append(A)
        CUT.append(is_cut)
        STATUS.append(status)
        TID.append(chosen[3] if chosen else None)
        frame_id += 1
        if started and lost_run >= lost_end_frames:
            break
    cap.release()

    t_arr = np.array(T, float)
    pos = np.array(POS, float).reshape(-1, 2)
    boxes = np.array(BOX, float).reshape(-1, 4)
    tracked = np.array([s == "ok" for s in STATUS])

    # ── Cinemática ───────────────────────────────────────────────────────────
    if status_callback:
        status_callback("IA: Calculando velocidade (compensação de câmera + filtro sem atraso)...")
    kin = solve(t_arr, pos, boxes, CAMS, np.array(CUT), width, height)
    speed, accel = kin["speed"], kin["accel"]
    summ = summarize(t_arr, speed, accel, tracked) if len(t_arr) else {"ok": False}

    phases = summ.get("phases", []) if summ.get("ok") else []
    start_i = summ.get("start_i", 0)
    dist_cum = np.zeros(len(t_arr))
    if summ.get("ok"):
        v_fill = np.where(np.isfinite(speed), speed, 0.0)
        seg = np.zeros(len(t_arr)); seg[1:] = (v_fill[1:] + v_fill[:-1]) / 2 * np.diff(t_arr)
        seg[:start_i + 1] = 0
        dist_cum = np.cumsum(seg)

    # ── metrics.csv (um registro por frame lido) ─────────────────────────────
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "tempo_s", "speed_kmh", "accel_m_s2", "time_to_max_speed_s", "status", "track_id",
                    "cx", "cy", "fase", "distancia_m", "bx1", "by1", "bx2", "by2", "cam_dx", "cam_dy", "m_por_px"])
        ttm = summ.get("time_to_max_speed_s", 0.0) if summ.get("ok") else 0.0
        for i in range(len(t_arr)):
            fin = np.isfinite(speed[i])
            w.writerow([
                i, f"{t_arr[i]:.3f}",
                f"{speed[i] * 3.6:.3f}" if fin else "",
                f"{accel[i]:.3f}" if np.isfinite(accel[i]) else "",
                f"{ttm:.3f}", STATUS[i], "" if TID[i] is None else TID[i],
                f"{pos[i, 0]:.1f}" if tracked[i] else "", f"{pos[i, 1]:.1f}" if tracked[i] else "",
                _phase_at(phases, t_arr[i]), f"{dist_cum[i]:.2f}",
                *([f"{v:.1f}" for v in boxes[i]] if tracked[i] else ["", "", "", ""]),
                *((f"{CAMS[i][0, 2]:.2f}", f"{CAMS[i][1, 2]:.2f}") if CAMS[i] is not None else ("", "")),
                f"{kin['m_per_px'][i]:.5f}" if np.isfinite(kin["m_per_px"][i]) else "",
            ])

    # ── Resumo ───────────────────────────────────────────────────────────────
    g = (lambda k, d=0.0: float(summ.get(k, d))) if summ.get("ok") else (lambda k, d=0.0: d)
    max_speed, avg_speed = g("max_speed_kmh"), g("avg_speed_kmh")
    efficiency = (avg_speed / max_speed * 100.0) if max_speed > 0 else 0.0
    start_s = float(t_arr[summ["start_i"]]) if summ.get("ok") else 0.0
    end_s = float(t_arr[summ["end_i"]]) if summ.get("ok") else 0.0
    with open(output_summary, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["max_speed_kmh", "avg_speed_kmh", "max_accel_m_s2", "impulse_m_s2", "time_to_max_speed_s",
                    "total_distance_m", "efficiency_percent", "start_time_s", "end_time_s", "run_time_s",
                    "locked_track_id", "max_decel_m_s2"])
        w.writerow([round(max_speed, 3), round(avg_speed, 3), round(g("max_accel_m_s2"), 3), round(g("impulse_m_s2"), 3),
                    round(g("time_to_max_speed_s"), 3), round(g("distance_m"), 3), round(efficiency, 3),
                    round(start_s, 3), round(end_s, 3), round(g("run_time_s"), 3),
                    locked_track_id if locked_track_id is not None else "", round(g("max_decel_m_s2"), 3)])

    # ── Passada 2: vídeo com HUD usando os valores finais ────────────────────
    if status_callback:
        status_callback("IA: Gerando vídeo com HUD...")
    cap = cv2.VideoCapture(video_path)
    writer = cv2.VideoWriter(output_video, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    sm_box, vmax_so_far = None, 0.0
    for i in range(len(t_arr)):
        ok, frame = cap.read()
        if not ok:
            break
        if tracked[i]:
            b = boxes[i]
            sm_box = b if sm_box is None else _ema(sm_box, b, HUD_BOX_EMA_ALPHA)
            if np.isfinite(speed[i]):
                vmax_so_far = max(vmax_so_far, speed[i] * 3.6)
                draw_corner_box(frame, *sm_box, style="simple")
                draw_hud(frame, sm_box[0], sm_box[1], speed[i] * 3.6,
                         float(accel[i]) if np.isfinite(accel[i]) else 0.0, vmax_so_far, smooth=False)
        writer.write(frame)
    cap.release()
    writer.release()

    return {
        "video_width": width,
        "video_height": height,
        "max_speed": round(max_speed, 2),
        "max_accel": round(g("max_accel_m_s2"), 2),
        "max_decel": round(g("max_decel_m_s2"), 2),
        "impulse_m_s2": round(g("impulse_m_s2"), 2),
        "avg_speed": round(avg_speed, 2),
        "distance": round(g("distance_m"), 2),
        "efficiency_percent": round(min(efficiency, 100.0), 1),
        "time_to_max_speed": round(g("time_to_max_speed_s"), 2),
        "start_time_s": round(start_s, 3),
        "end_time_s": round(end_s, 3),
        "run_time_s": round(g("run_time_s"), 3),
        "locked_track_id": locked_track_id,
        "output_dir": out_dir,
        "fases": phases,
        "qualidade": {
            "frames_rastreados_pct": round(100 * float(tracked.mean()), 1) if len(tracked) else 0.0,
            "velocidade_medida_pct": round(g("measured_pct"), 1),
            "cortes_de_cena": int(np.sum(CUT)),
            "frames_com_regua": kin["scale_frames"],
            "pontos_descartados_pct": kin["glitch_pct"],
            "regua": f"largura do cavalo de perfil = {HORSE_LENGTH_METERS} m (sem calibração pela pista, ±15–20%)",
        },
    }
