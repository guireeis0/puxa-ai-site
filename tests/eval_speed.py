"""
Avalia a precisão do motor de velocidade contra o gabarito dos vídeos sintéticos.

    python tests/eval_speed.py SYNTH_DIR [--app DIR_DO_APP] [--label nome] [--only cenario ...]

--app permite comparar versões (ex.: uma cópia do app/ de um commit antigo).
Métricas por cenário (frames com o cavalo rastreado):
  MAE      erro absoluto médio da velocidade instantânea (km/h)
  viés     erro médio (km/h) — negativo = subestima
  máx      erro na velocidade máxima (%)
  dist     erro na distância total (%)
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import importlib
import io
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_engine(app_dir: str):
    app_dir = os.path.abspath(app_dir)
    for mod in ("main", "speed", "config", "hud", "camera_motion", "kinematics"):
        sys.modules.pop(mod, None)
    sys.path.insert(0, app_dir)
    try:
        return importlib.import_module("main")
    finally:
        sys.path.remove(app_dir)


def evaluate(engine, video: str, truth: dict, workdir: str) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        r = engine.process_video(video, "job", base_output=workdir)
    json.dumps(r)  # o resultado vai para a API: precisa ser JSON puro (sem tipos do NumPy)
    m = pd.read_csv(os.path.join(workdir, "job", "metrics.csv"))
    m = m[m["status"] == "ok"]
    t_true = np.array(truth["t"])
    v_inst = np.array(truth["speed_ms"]) * 3.6
    # gabarito "média por passada": remove a oscilação dentro da passada (média móvel de ~1 passada),
    # que é o que sistemas de GPS e o motor reportam
    win = max(1, int(round(truth["fps"] / 2.2)))
    v_true = np.convolve(np.pad(v_inst, win, mode="edge"), np.ones(2 * win + 1) / (2 * win + 1), "valid")
    x_true = np.array(truth["x_m"])

    m = m.dropna(subset=["speed_kmh"])
    vt = np.interp(m["tempo_s"].to_numpy(dtype=float), t_true, v_true)
    vm = m["speed_kmh"].to_numpy(dtype=float)
    moving = vt > 5  # ignora o cavalo parado na largada
    err = vm[moving] - vt[moving]

    # distância real só no trecho que o motor considerou como corrida (o cavalo pode sair do quadro)
    t0, t1 = r.get("start_time_s"), r.get("end_time_s")
    if t0 is not None and t1 and t1 > t0:
        dist_true = float(np.interp(t1, t_true, x_true) - np.interp(t0, t_true, x_true))
        vmax_true = float(np.max(v_true[(t_true >= t0) & (t_true <= t1)]))
    else:
        dist_true, vmax_true = truth["distance_m"], float(v_true.max())
    return {
        "frames_ok_%": round(100 * len(m) / len(t_true), 1),
        "MAE_kmh": round(float(np.mean(np.abs(err))), 2) if err.size else None,
        "vies_kmh": round(float(np.mean(err)), 2) if err.size else None,
        "max_real": round(vmax_true, 2), "max_medido": r.get("max_speed"),
        "max_erro_%": round(100 * (r.get("max_speed", 0) - vmax_true) / vmax_true, 1),
        "dist_real": round(dist_true, 2), "dist_medida": r.get("distance"),
        "dist_erro_%": round(100 * (r.get("distance", 0) - dist_true) / dist_true, 1) if dist_true > 0 else None,
    }


def run(synth_dir: str, app_dir: str, only=None) -> pd.DataFrame:
    engine = load_engine(app_dir)
    rows = []
    for jf in sorted(glob.glob(os.path.join(synth_dir, "*.json"))):
        truth = json.load(open(jf, encoding="utf-8"))
        if only and truth["scenario"] not in only:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            res = evaluate(engine, jf[:-5] + ".mp4", truth, tmp)
        rows.append({"cenario": truth["scenario"], **res})
        print(f"  {truth['scenario']:<15} {res}", flush=True)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("synth_dir")
    ap.add_argument("--app", default=os.path.join(ROOT, "app"))
    ap.add_argument("--label", default="atual")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()
    print(f"[eval] motor: {a.label} ({a.app})")
    df = run(a.synth_dir, a.app, a.only)
    print(df.to_string(index=False))
    if a.csv:
        df.assign(versao=a.label).to_csv(a.csv, index=False)
