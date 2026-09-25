"""
Gerador de vídeos sintéticos de vaquejada com gabarito (velocidade real conhecida).

Um cavalo 3D galopando (animação em fundo verde, Pixabay 212734) é recortado por chroma key e
composto sobre uma pista procedural (areia, cerca, árvores, faixa de 9 m) vista de lado.
Tudo é definido em metros: posição do cavalo, câmera (centro e zoom em px/m) e tamanho do
cavalo. Assim cada frame tem velocidade, distância e escala exatas para comparar com o sistema.

Cenários (ver SCENARIOS): câmera fixa, panorâmica acompanhando, zoom variável com tarja de TV,
corte de cena e 30 fps. Uso:
    python tests/synthetic.py SAIDA_DIR [--src caminho_do_212734.mp4]
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

SRC_DEFAULT = r"C:\Users\User\puxa-bio-work\candidatos\212734_large.mp4"
SRC_LOOP_FRAMES = 28.6          # ciclo da animação (autossimilaridade medida)
SRC_CROP = (380, 130, 1580, 975)  # recorte fixo que contém o cavalo em todos os frames (x1, y1, x2, y2)

HORSE_EXTENT_M = 2.4            # largura real da caixa do cavalo (nariz→cauda) no gabarito
PROFILE_ASPECT = 1.6            # largura/altura de um cavalo real a galope de perfil
WORLD_PX_PER_M = 50
WORLD_LEN_M, WORLD_H_M = 260.0, 34.0
GROUND_Y_M = 19.0               # linha onde os cascos tocam
FAIXA_X_M = (150.0, 159.0)      # faixa de pontuação ABVAQ: 9 m


# ── Cavalo ───────────────────────────────────────────────────────────────────
def _alazao(img: np.ndarray) -> np.ndarray:
    """Recolore o cavalo 3D branco como alazão (pelagem comum no Quarto de Milha de vaquejada)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    base = np.array([40, 70, 130], np.float32)  # BGR
    return np.clip(base * (0.35 + 1.1 * g[..., None]), 0, 255).astype(np.uint8)


class HorseSprite:
    def __init__(self, src: str):
        cap = cv2.VideoCapture(src)
        x1, y1, x2, y2 = SRC_CROP
        self.frames, self.masks, widths, heights = [], [], [], []
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
            m = 255 - cv2.inRange(hsv, (35, 80, 60), (85, 255, 255))
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            ys, xs = np.nonzero(m)
            widths.append(xs.max() - xs.min())
            heights.append(ys.max() - ys.min())
            self.frames.append(_alazao(fr[y1:y2, x1:x2]))
            self.masks.append(cv2.GaussianBlur(m[y1:y2, x1:x2], (3, 3), 0))
        cap.release()
        # âncora: centro horizontal médio do cavalo e linha dos cascos (em coordenadas do recorte)
        self.anchor_x = 976.0 - x1
        self.anchor_y = 945.0 - y1
        self.src_px_per_m = float(np.median(widths)) / HORSE_EXTENT_M
        # a animação 3D é mais "alta" (largura/altura ≈ 1,44) que cavalos reais a galope de perfil
        # (≈ 1,6, medido pela pose em vídeos reais): achata na vertical para ter a proporção real
        self.y_squash = (float(np.median(widths)) / float(np.median(heights))) / PROFILE_ASPECT

    def get(self, phase: float):
        """phase em ciclos (float) → frame da animação."""
        n = len(self.frames)
        i = int((phase % 1.0) * SRC_LOOP_FRAMES) % n
        return self.frames[i], self.masks[i]


# ── Pista ────────────────────────────────────────────────────────────────────
def make_world(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    W, H = int(WORLD_LEN_M * WORLD_PX_PER_M), int(WORLD_H_M * WORLD_PX_PER_M)
    img = np.zeros((H, W, 3), np.float32)

    def noise(scale, amp):
        small = rng.standard_normal((max(2, H // scale), max(2, W // scale))).astype(np.float32)
        return cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC) * amp

    y = np.arange(H)[:, None] / WORLD_PX_PER_M
    sky, trees, ground = y < 9, (y >= 9) & (y < 16), y >= 16
    # céu
    img[:] = np.array([235, 215, 190], np.float32)
    img += noise(40, 6)[..., None]
    # árvores (manchas verdes com textura)
    tex = noise(12, 30) + noise(4, 18)
    t3 = np.stack([60 + tex, 95 + tex, 70 + tex * 0.6], -1)
    img = np.where(trees[..., None], t3, img)
    # areia
    sand = noise(30, 10) + noise(6, 9) + noise(2, 7)
    s3 = np.stack([120 + sand, 160 + sand, 190 + sand], -1)
    img = np.where(ground[..., None], s3, img)
    img = np.clip(img, 0, 255).astype(np.uint8)
    # marcas/pegadas na areia (pontos de textura para o fluxo óptico)
    for _ in range(int(WORLD_LEN_M * 12)):
        cx = int(rng.uniform(0, W)); cy = int(rng.uniform(16.2, WORLD_H_M) * WORLD_PX_PER_M)
        cv2.ellipse(img, (cx, cy), (int(rng.uniform(4, 12)), int(rng.uniform(2, 5))), 0, 0, 360,
                    (95, 125, 150), -1, cv2.LINE_AA)
    # cerca: mourões a cada 2,5 m + 2 réguas
    top, bot = int(13.8 * WORLD_PX_PER_M), int(16.2 * WORLD_PX_PER_M)
    for xm in np.arange(0, WORLD_LEN_M, 2.5):
        x = int(xm * WORLD_PX_PER_M)
        cv2.rectangle(img, (x, top), (x + 8, bot), (225, 230, 235), -1)
    for yr in (14.3, 15.3):
        yy = int(yr * WORLD_PX_PER_M)
        cv2.rectangle(img, (0, yy), (W, yy + 7), (215, 220, 225), -1)
    # faixa de pontuação (cal)
    for xm in FAIXA_X_M:
        x = int(xm * WORLD_PX_PER_M)
        cv2.rectangle(img, (x - 6, int(16.3 * WORLD_PX_PER_M)), (x + 6, H), (245, 245, 245), -1)
    return img


# ── Cenários ─────────────────────────────────────────────────────────────────
def speed_profile(t: np.ndarray, vmax: float = 13.0) -> np.ndarray:
    """Largada parada → aceleração → corrida → frenagem (derrubada) → trote de saída. m/s."""
    def smooth(a, b, x):
        u = np.clip((x - a) / (b - a), 0, 1)
        return u * u * (3 - 2 * u)
    v = vmax * smooth(0.6, 4.0, t)
    v -= (vmax - 5.0) * smooth(7.0, 9.0, t)
    # oscilação dentro da passada (~±2%), como nos dados de GPS de galope
    v *= 1 + 0.02 * np.sin(2 * np.pi * 2.2 * t)
    return np.maximum(v, 0)


def stride_freq(v: np.ndarray) -> np.ndarray:
    # PSI: 2,02 Hz a 9 m/s e 2,41 Hz a 17 m/s (Witte et al. 2006), extrapolado de forma linear
    return np.where(v < 0.5, 0.0, np.clip(2.02 + (v - 9.0) * 0.049, 1.6, 2.6))


@dataclass
class Scenario:
    name: str
    fps: float = 60.0
    size: tuple = (1280, 720)
    duration: float = 10.0
    zoom: float = 110.0                 # px por metro
    zoom_wobble: float = 0.0            # amplitude relativa do zoom (senoide)
    follow: bool = True                 # câmera acompanha o cavalo
    fixed_center_m: float = 60.0
    overlay: bool = False               # tarja + logo de transmissão
    cut_at: float | None = None         # corte de cena (novo enquadramento)
    vmax: float = 13.0
    start_x: float = 30.0
    notes: str = ""
    extra: dict = field(default_factory=dict)


SCENARIOS = [
    Scenario("fixa_60fps", size=(1920, 1080), duration=6.0, zoom=45.0, follow=False, fixed_center_m=52.5,
             vmax=12.0, start_x=31.5, notes="câmera fixa, cavalo cruza o quadro"),
    Scenario("pan_60fps", notes="panorâmica acompanhando o cavalo"),
    Scenario("pan_30fps", fps=30.0, notes="panorâmica, 30 fps"),
    Scenario("tv_zoom_tarja", zoom_wobble=0.25, overlay=True, notes="panorâmica + zoom variável + tarja/logo de TV"),
    Scenario("tv_corte", zoom_wobble=0.2, overlay=True, cut_at=5.0, notes="como a TV, com corte de câmera aos 5 s"),
    Scenario("tv_dupla_boi", zoom_wobble=0.15, overlay=True,
             notes="vaquejada: animal escuro (boi/esteireiro) correndo colado, caixas se sobrepõem",
             extra={"companions": [(1.3, -0.35, "escuro")]}),
]


def _paste(frame, spr, msk, sprite, z, rel_x_m, rel_y_m, W, H):
    """Cola um sprite com âncora (cascos) na posição relativa à câmera, em metros."""
    s = z / sprite.src_px_per_m
    sw, sh = max(2, int(spr.shape[1] * s)), max(2, int(spr.shape[0] * s * sprite.y_squash))
    spr_s = cv2.resize(spr, (sw, sh), interpolation=cv2.INTER_AREA)
    a = cv2.resize(msk, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32)[..., None] / 255
    xa = int(round(rel_x_m * z + W / 2 - sprite.anchor_x * s))
    ya = int(round(rel_y_m * z + H / 2 - sprite.anchor_y * s * sprite.y_squash))
    xs0, ys0 = max(0, -xa), max(0, -ya)
    xs1, ys1 = min(sw, W - xa), min(sh, H - ya)
    if xs1 > xs0 and ys1 > ys0:
        roi = frame[ya + ys0:ya + ys1, xa + xs0:xa + xs1].astype(np.float32)
        aa = a[ys0:ys1, xs0:xs1]
        frame[ya + ys0:ya + ys1, xa + xs0:xa + xs1] = (roi * (1 - aa) + spr_s[ys0:ys1, xs0:xs1] * aa).astype(np.uint8)


def draw_overlay(frame):
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (int(w * .08), int(h * .86)), (int(w * .62), int(h * .96)), (20, 60, 90), -1)
    cv2.putText(frame, "BOLAO DE VAQUEJADA - DISPUTA PROFISSIONAL", (int(w * .1), int(h * .925)),
                cv2.FONT_HERSHEY_SIMPLEX, h / 900, (230, 240, 250), 2, cv2.LINE_AA)
    cv2.circle(frame, (int(w * .93), int(h * .1)), int(h * .07), (40, 40, 160), -1)
    cv2.putText(frame, "TV", (int(w * .905), int(h * .115)), cv2.FONT_HERSHEY_SIMPLEX, h / 700, (255, 255, 255), 2)


def render(sc: Scenario, sprite: HorseSprite, world: np.ndarray, out_dir: str) -> dict:
    W, H = sc.size
    n = int(round(sc.duration * sc.fps))
    t = np.arange(n) / sc.fps
    v = speed_profile(t, sc.vmax)
    x = sc.start_x + np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2 / sc.fps)])
    phase = np.concatenate([[0], np.cumsum(stride_freq(v)[1:] / sc.fps)])

    # câmera
    if sc.follow:
        cx = np.empty(n); cx[0] = x[0] + 1.5
        a = 1 - np.exp(-1 / (0.35 * sc.fps))          # atraso de ~0,35 s, como um operador
        for i in range(1, n):
            cx[i] = cx[i - 1] + a * (x[i] + 1.5 - cx[i - 1])
    else:
        cx = np.full(n, sc.fixed_center_m)
    zoom = sc.zoom * (1 + sc.zoom_wobble * np.sin(2 * np.pi * t / 6.0))
    cy = np.full(n, GROUND_Y_M - 1.6)
    if sc.cut_at is not None:
        after = t >= sc.cut_at
        zoom[after] *= 0.65
        cx[after] += 3.0
        cy[after] -= 0.8

    path = os.path.join(out_dir, f"{sc.name}.mp4")
    wr = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), sc.fps, (W, H))
    for i in range(n):
        z = zoom[i]
        # recorte do mundo visível
        half_w, half_h = W / 2 / z, H / 2 / z
        x0, y0 = (cx[i] - half_w) * WORLD_PX_PER_M, (cy[i] - half_h) * WORLD_PX_PER_M
        k = z / WORLD_PX_PER_M
        M = np.array([[k, 0, -x0 * k], [0, k, -y0 * k]], np.float32)
        frame = cv2.warpAffine(world, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        # companheiros (atrás do cavalo analisado): mesma velocidade, deslocados em x e na profundidade
        for dx_m, dy_m, coat in sc.extra.get("companions", []):
            spr_c, msk_c = sprite.get(phase[i] + 0.37)
            if coat == "escuro":
                spr_c = (spr_c.astype(np.float32) * 0.35).astype(np.uint8)
            _paste(frame, spr_c, msk_c, sprite, z, x[i] + dx_m - cx[i], GROUND_Y_M + dy_m - cy[i], W, H)
        # cavalo
        spr, msk = sprite.get(phase[i])
        s = z / sprite.src_px_per_m
        sw, sh = max(2, int(spr.shape[1] * s)), max(2, int(spr.shape[0] * s * sprite.y_squash))
        spr_s = cv2.resize(spr, (sw, sh), interpolation=cv2.INTER_AREA)
        msk_s = cv2.resize(msk, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32)[..., None] / 255
        px = (x[i] - cx[i]) * z + W / 2 - sprite.anchor_x * s
        py = (GROUND_Y_M - cy[i]) * z + H / 2 - sprite.anchor_y * s * sprite.y_squash
        xa, ya = int(round(px)), int(round(py))
        xs0, ys0 = max(0, -xa), max(0, -ya)
        xs1, ys1 = min(sw, W - xa), min(sh, H - ya)
        if xs1 > xs0 and ys1 > ys0:
            roi = frame[ya + ys0:ya + ys1, xa + xs0:xa + xs1].astype(np.float32)
            a_ = msk_s[ys0:ys1, xs0:xs1]
            frame[ya + ys0:ya + ys1, xa + xs0:xa + xs1] = (roi * (1 - a_) + spr_s[ys0:ys1, xs0:xs1] * a_).astype(np.uint8)
        # leve ruído de sensor
        frame = cv2.add(frame, np.random.default_rng(i).integers(0, 4, frame.shape, dtype=np.uint8))
        if sc.overlay:
            draw_overlay(frame)
        wr.write(frame)
    wr.release()

    truth = {
        "scenario": sc.name, "notes": sc.notes, "fps": sc.fps, "size": list(sc.size),
        "horse_extent_m": HORSE_EXTENT_M,
        "t": t.round(4).tolist(), "speed_ms": v.round(4).tolist(), "x_m": (x - x[0]).round(4).tolist(),
        "stride_hz": stride_freq(v).round(3).tolist(),
        "max_speed_kmh": round(float(v.max() * 3.6), 2),
        "distance_m": round(float(x[-1] - x[0]), 2),
    }
    with open(os.path.join(out_dir, f"{sc.name}.json"), "w", encoding="utf-8") as f:
        json.dump(truth, f)
    return truth


def generate(out_dir: str, src: str = SRC_DEFAULT, only: list[str] | None = None) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    sprite = HorseSprite(src)
    world = make_world()
    res = []
    for sc in SCENARIOS:
        if only and sc.name not in only:
            continue
        res.append(render(sc, sprite, world, out_dir))
        print(f"[synth] {sc.name}: {res[-1]['max_speed_kmh']} km/h máx · {res[-1]['distance_m']} m", flush=True)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--src", default=SRC_DEFAULT)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    generate(a.out_dir, a.src, a.only)
