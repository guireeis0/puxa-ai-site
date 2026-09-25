"""
Gera puxa-ai-site/landing/horse-holo.json: um ciclo de galope como nuvem de pontos,
separando patas (verde no site) do resto do corpo (cinza).

Fonte: animação 3D de galope em fundo verde (Pixabay 212734, Pixabay Content License).
    python tools/build_horse_holo.py [caminho_do_video] [--preview saida.png]
"""
import argparse
import base64
import json
import os

import cv2
import numpy as np

SRC = r"C:\Users\User\puxa-bio-work\candidatos\212734_large.mp4"
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "puxa-ai-site", "landing", "horse-holo.json")
LOOP_FRAMES = 28.6        # ciclo da animação (medido por autossimilaridade)
N_OUT = 24                # quadros do ciclo guardados
GRID_W = 132              # resolução da nuvem de pontos (largura)
LEG_FROM = 0.60           # patas: abaixo desta fração da altura do corpo (tronco termina ~aí)


def masks(src):
    cap = cv2.VideoCapture(src)
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        m = 255 - cv2.inRange(cv2.cvtColor(fr, cv2.COLOR_BGR2HSV), (35, 80, 60), (85, 255, 255))
        frames.append(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)))
    return frames


def leg_mask(sil):
    """Patas = parte da silhueta abaixo da linha da barriga, excluindo cauda e cabeça."""
    h, w = sil.shape
    ys, xs = np.nonzero(sil)
    top, bot = ys.min(), ys.max()
    # linha da barriga: mais baixa linha em que o tronco ainda é largo (> 30% da largura)
    widths = (sil > 0).sum(1)
    x0, x1 = xs.min(), xs.max()
    body_w = x1 - x0
    rows = np.flatnonzero(widths > 0.30 * body_w)
    belly = rows.max() if rows.size else int(top + LEG_FROM * (bot - top))
    belly = min(belly, int(top + 0.72 * (bot - top)))
    legs = np.zeros_like(sil)
    legs[belly + 1:] = sil[belly + 1:]
    # cauda: faixa traseira (esquerda) acima de ~80% da altura não conta como pata
    tail_x = int(x0 + 0.14 * body_w)
    legs[:int(top + 0.80 * (bot - top)), :tail_x] = 0
    return legs


def pack(bits):
    return base64.b64encode(np.packbits(bits.astype(np.uint8).ravel()).tobytes()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default=SRC)
    ap.add_argument("--preview")
    a = ap.parse_args()

    ms = masks(a.src)
    # recorte comum a todo o ciclo
    stack = np.max(np.stack(ms[:int(LOOP_FRAMES) + 1]), axis=0)
    ys, xs = np.nonzero(stack)
    pad = 12
    y0, y1, x0, x1 = ys.min() - pad, ys.max() + pad, xs.min() - pad, xs.max() + pad
    gw = GRID_W
    gh = int(round(gw * (y1 - y0) / (x1 - x0)))

    frames, prev = [], []
    for k in range(N_OUT):
        i = int(round(k * LOOP_FRAMES / N_OUT)) % len(ms)
        sil = ms[i][y0:y1, x0:x1]
        legs = leg_mask(sil)
        small = cv2.resize(sil, (gw, gh), interpolation=cv2.INTER_AREA) > 110
        small_legs = cv2.resize(legs, (gw, gh), interpolation=cv2.INTER_AREA) > 90
        body = small & ~small_legs
        legs_b = small & small_legs
        frames.append({"body": pack(body), "legs": pack(legs_b)})
        prev.append((body, legs_b))

    data = {"w": gw, "h": gh, "fps": 30 * N_OUT / LOOP_FRAMES, "frames": frames,
            "source": "Pixabay 212734 (Pixabay Content License) — silhueta convertida em nuvem de pontos"}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{OUT}: {gw}x{gh}, {N_OUT} quadros, {os.path.getsize(OUT) // 1024} KB")

    if a.preview:
        tiles = []
        for body, legs in prev[::4]:
            img = np.zeros((gh, gw, 3), np.uint8)
            img[body] = (143, 143, 143)
            img[legs] = (142, 207, 62)
            tiles.append(cv2.resize(img, (gw * 3, gh * 3), interpolation=cv2.INTER_NEAREST))
        cv2.imwrite(a.preview, np.hstack(tiles))


if __name__ == "__main__":
    main()
