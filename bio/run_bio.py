"""
Roda a biomecânica completa num vídeo, frame a frame, com prévia ao vivo.

Pose: DeepLabCut SuperAnimal-Quadruped (hrnet_w32, top-down). A caixa do cavalo vem do
tracking YOLO do pipeline de performance (metrics.csv, colunas bx1..by2), então o modelo de
pose roda só no cavalo travado. Frames sem caixa usam o detector do DeepLabCut como reserva.

Precisa do ambiente separado com DeepLabCut (Python 3.10–3.12), não do venv do site:
    C:\\Users\\User\\puxa-bio-env\\Scripts\\python.exe bio\\run_bio.py VIDEO SAIDA --track metrics.csv

Durante a execução:
  - SAIDA/live.jpg        último frame processado com o esqueleto (prévia ao vivo)
  - stdout "[bio] frame i/N ..." a cada poucos frames (o api.py repassa como status)
"""
import argparse
import os
import sys
import time

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from biomech import BRAND_BGR, PANEL_BGR, draw_skeleton, run_analysis  # noqa: E402

SUPERANIMAL = "superanimal_quadruped"
POSE_MODEL  = "hrnet_w32"
DETECTOR    = "fasterrcnn_resnet50_fpn_v2"
BOX_PAD     = 0.12   # folga em volta da caixa do YOLO (patas e cabeça costumam escapar)
LIVE_EVERY  = 2      # grava a prévia a cada N frames
MAX_BOX_GAP = 10     # interpola a caixa em buracos de até N frames


def load_runners(device: str):
    from deeplabcut.pose_estimation_pytorch.apis.utils import get_inference_runners, get_pose_inference_runner
    from deeplabcut.pose_estimation_pytorch.modelzoo.utils import (
        get_super_animal_snapshot_path, load_super_animal_config, update_config,
    )
    cfg = load_super_animal_config(super_animal=SUPERANIMAL, model_name=POSE_MODEL, detector_name=DETECTOR)
    cfg = update_config(cfg, max_individuals=1, device=device)
    pose_path = get_super_animal_snapshot_path(dataset=SUPERANIMAL, model_name=POSE_MODEL)
    det_path  = get_super_animal_snapshot_path(dataset=SUPERANIMAL, model_name=DETECTOR)
    pose = get_pose_inference_runner(cfg, snapshot_path=pose_path, batch_size=1, max_individuals=1)

    detector = {}
    def get_detector():
        # carregado só se algum frame ficar sem caixa do YOLO
        if "r" not in detector:
            _, detector["r"] = get_inference_runners(
                model_config=cfg, snapshot_path=pose_path, max_individuals=1,
                num_bodyparts=len(cfg["metadata"]["bodyparts"]), num_unique_bodyparts=0,
                batch_size=1, detector_batch_size=1, detector_path=det_path,
            )
        return detector["r"]
    return pose, get_detector, list(cfg["metadata"]["bodyparts"])


def track_boxes(track_csv: str | None, fps: float, n_frames: int, w: int, h: int) -> np.ndarray:
    """Caixa (x, y, larg, alt) por frame a partir do metrics.csv; NaN onde não há."""
    boxes = np.full((n_frames, 4), np.nan)
    if not track_csv or not os.path.exists(track_csv):
        return boxes
    m = pd.read_csv(track_csv)
    if "bx1" not in m.columns:
        return boxes
    m = m.dropna(subset=["bx1", "by1", "bx2", "by2"])
    for t, x1, y1, x2, y2 in zip(m["tempo_s"], m["bx1"], m["by1"], m["bx2"], m["by2"]):
        f = int(round(float(t) * fps))
        if 0 <= f < n_frames:
            bw, bh = x2 - x1, y2 - y1
            x1 = max(0.0, x1 - bw * BOX_PAD); y1 = max(0.0, y1 - bh * BOX_PAD)
            x2 = min(w - 1.0, x2 + bw * BOX_PAD); y2 = min(h - 1.0, y2 + bh * BOX_PAD)
            boxes[f] = (x1, y1, x2 - x1, y2 - y1)
    for c in range(4):
        boxes[:, c] = pd.Series(boxes[:, c]).interpolate(limit=MAX_BOX_GAP, limit_area="inside").to_numpy()
    return boxes


def write_live(frame_bgr, kp, bodyparts, out_dir, i, n, proc_fps):
    img = frame_bgr.copy()
    draw_skeleton(img, kp[:, :2] if kp is not None else None, bodyparts, conf=kp[:, 2] if kp is not None else None)
    cv2.rectangle(img, (0, 0), (img.shape[1], 26), PANEL_BGR, -1)
    cv2.putText(img, f"POSE AO VIVO  frame {i + 1}/{n}  {proc_fps:.1f} fps", (8, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, BRAND_BGR, 1, cv2.LINE_AA)
    tmp = os.path.join(out_dir, "live.tmp.jpg")
    cv2.imwrite(tmp, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    try:
        os.replace(tmp, os.path.join(out_dir, "live.jpg"))
    except PermissionError:
        pass  # Windows: o servidor está lendo o frame anterior; a prévia só pula este frame


def pose_video(video: str, out_dir: str, track_csv: str | None, device: str):
    pose, get_detector, bodyparts = load_runners(device)

    cap = cv2.VideoCapture(video)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    boxes = track_boxes(track_csv, fps, n, w, h)
    has_track = bool(np.isfinite(boxes[:, 0]).any())

    K = len(bodyparts)
    kp_all = np.full((n, K, 3), np.nan)
    t0 = time.time()
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok or i >= n:
            break
        rgb = np.ascontiguousarray(frame[..., ::-1])
        box = boxes[i]
        kp = None
        if np.isfinite(box).all():
            pred = pose.inference([(rgb, {"bboxes": box[None, :].astype(np.float32)})])[0]
            kp = pred["bodyparts"][0]
        elif not has_track:
            det = get_detector().inference([rgb])[0]
            if len(det.get("bboxes", [])):
                pred = pose.inference([(rgb, {"bboxes": det["bboxes"][:1]})])[0]
                kp = pred["bodyparts"][0]
        if kp is not None:
            kp_all[i] = kp

        elapsed = time.time() - t0
        proc_fps = (i + 1) / max(elapsed, 1e-6)
        if i % LIVE_EVERY == 0:
            write_live(frame, kp, bodyparts, out_dir, i, n, proc_fps)
        if i % 10 == 0 or i == n - 1:
            print(f"[bio] frame {i + 1}/{n} ({int(100 * (i + 1) / max(n, 1))}%) {proc_fps:.1f} fps", flush=True)
        i += 1
    cap.release()
    np.save(os.path.join(out_dir, "pose_raw.npy"), kp_all)
    return kp_all, bodyparts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--track", default=None)
    ap.add_argument("--device", default="cuda")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    t0 = time.time()
    raw_path = os.path.join(a.out_dir, "pose_raw.npy")
    kp, bodyparts = pose_video(a.video, a.out_dir, a.track, a.device)
    print(f"[bio] pose ok em {time.time() - t0:.0f}s", flush=True)

    res = run_analysis(a.video, kp, bodyparts, a.out_dir, a.track)
    p = res.get("passada") or {}
    m = (res.get("mao_de_galope") or {}).get("anteriores") or {}
    print(f"[bio] passada {p.get('frequencia_hz')} Hz · mão {m.get('predominante')} · total {time.time() - t0:.0f}s", flush=True)
