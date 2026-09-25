"""
Biomecânica a partir de pontos do corpo (pose) — Puxa.ai

Entrada : pontos do corpo de um cavalo por frame (DeepLabCut SuperAnimal-Quadruped, 39 pontos)
          + opcionalmente o metrics.csv do pipeline de performance (tracking YOLO + velocidade)
Saída   : bio.json, keypoints.csv e biomecanica.mp4 (esqueleto em câmera lenta)

Métricas:
  - frequência e duração da passada (picos de protração de cada pata)
  - comprimento de passada estimado (velocidade do tracking × duração da passada)
  - mão de galope por passada (ordem de protração dos anteriores) e trocas de mão
  - galope unido/desunido (mão dos anteriores × mão dos posteriores)
  - ângulos aproximados de carpo e jarrete (2D, lado voltado para a câmera)
  - inclinação do tronco e confiança da detecção
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np
import pandas as pd
from scipy.signal import find_peaks, savgol_filter

# ── Parâmetros ────────────────────────────────────────────────────────────────
MIN_LIKELIHOOD   = 0.5    # pontos abaixo disso são descartados
MAX_GAP_FRAMES   = 6      # buracos até esse tamanho são interpolados
SAVGOL_WINDOW_S  = 0.12   # janela do filtro Savitzky-Golay (segundos)
STRIDE_MIN_S     = 0.25   # passada mais curta aceita (4 Hz)
STRIDE_MAX_S     = 0.80   # passada mais longa aceita (1,25 Hz)
PEAK_PROMINENCE  = 0.12   # proeminência mínima do pico de protração (× comprimento do corpo)
PROFILE_MIN_HORIZ = 0.85  # |dx| / comprimento da linha pescoço→cauda para considerar perfil
PROFILE_MIN_LEN   = 0.6   # comprimento mínimo do corpo (× percentil 90 do clipe)
MIN_STRIDES       = 6     # mínimo de passadas para reportar a mão de galope
CYCLE_MIN_AUTOCORR = 0.2  # autocorrelação mínima para aceitar o ciclo de uma pata
SLOWMO_MAX_HZ     = 1.4   # ciclo abaixo disso não é galope em tempo real → provável câmera lenta
LEAD_MIN_CONSISTENCY = 0.7  # abaixo disso a mão de galope é "inconclusiva"

# Faixa publicada para PSI a galope, 9–17 m/s (Witte, Hirst & Wilson, J Exp Biol 2006)
REF_STRIDE_HZ    = (2.02, 2.41)

LIMBS = {
    "anterior_esquerdo":  ("front_left_thai",  "front_left_knee",  "front_left_paw"),
    "anterior_direito":   ("front_right_thai", "front_right_knee", "front_right_paw"),
    "posterior_esquerdo": ("back_left_thai",   "back_left_knee",   "back_left_paw"),
    "posterior_direito":  ("back_right_thai",  "back_right_knee",  "back_right_paw"),
}

SKELETON = [
    ("nose", "neck_end"), ("neck_end", "neck_base"), ("neck_base", "back_base"),
    ("back_base", "back_middle"), ("back_middle", "back_end"), ("back_end", "tail_base"),
    ("tail_base", "tail_end"),
    ("neck_base", "front_left_thai"),  ("front_left_thai", "front_left_knee"),   ("front_left_knee", "front_left_paw"),
    ("neck_base", "front_right_thai"), ("front_right_thai", "front_right_knee"), ("front_right_knee", "front_right_paw"),
    ("back_end", "back_left_thai"),    ("back_left_thai", "back_left_knee"),     ("back_left_knee", "back_left_paw"),
    ("back_end", "back_right_thai"),   ("back_right_thai", "back_right_knee"),   ("back_right_knee", "back_right_paw"),
]

# Cores BGR por membro (laranja/azul Puxa para os anteriores)
LIMB_COLORS = {                     # BGR · esquerdo = verdes, direito = neutros (paleta do site)
    "front_left":  (142, 207, 62),   # #3ECF8E
    "front_right": (237, 237, 237),  # #EDEDED
    "back_left":   (183, 231, 110),  # #6EE7B7
    "back_right":  (143, 143, 143),  # #8F8F8F
}
AXIS_COLOR = (208, 208, 208)         # #D0D0D0
BRAND_BGR = (142, 207, 62)           # #3ECF8E
PANEL_BGR = (18, 18, 18)             # #121212


# ── Limpeza do sinal ──────────────────────────────────────────────────────────
def clean_keypoints(kp: np.ndarray, fps: float) -> np.ndarray:
    """Descarta pontos de baixa confiança, interpola buracos curtos e suaviza (Savitzky-Golay)."""
    T, K, _ = kp.shape
    xy = kp[:, :, :2].copy()
    xy[kp[:, :, 2] < MIN_LIKELIHOOD] = np.nan

    win = max(5, int(round(SAVGOL_WINDOW_S * fps)) | 1)
    for k in range(K):
        for c in range(2):
            s = pd.Series(xy[:, k, c]).interpolate(limit=MAX_GAP_FRAMES, limit_area="inside")
            v = s.to_numpy(copy=True)
            ok = ~np.isnan(v)
            # suaviza cada trecho contínuo separadamente
            idx = np.flatnonzero(ok)
            if idx.size == 0:
                xy[:, k, c] = v
                continue
            splits = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
            for seg in splits:
                if seg.size >= win:
                    v[seg] = savgol_filter(v[seg], win, 2)
            xy[:, k, c] = v
    return xy


# ── Geometria ─────────────────────────────────────────────────────────────────
def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Ângulo ABC em graus, frame a frame."""
    ba, bc = a - b, c - b
    cos = np.sum(ba * bc, axis=1) / (np.linalg.norm(ba, axis=1) * np.linalg.norm(bc, axis=1))
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def _stats(v: np.ndarray, decimals: int = 1) -> dict | None:
    v = v[~np.isnan(v)]
    if v.size < 10:
        return None
    return {
        "media": round(float(np.mean(v)), decimals),
        "min_p5": round(float(np.percentile(v, 5)), decimals),
        "max_p95": round(float(np.percentile(v, 95)), decimals),
        "amplitude": round(float(np.percentile(v, 95) - np.percentile(v, 5)), decimals),
    }


def _cycle_period(s: np.ndarray, fps: float) -> tuple[float | None, float]:
    """
    Período dominante (s) de um sinal com buracos, por autocorrelação média dos trechos contínuos.
    Retorna (período, autocorrelação no pico) ou (None, 0).
    """
    idx = np.flatnonzero(~np.isnan(s))
    if idx.size == 0:
        return None, 0.0
    max_lag = int(STRIDE_MAX_S * 2 * fps)
    acc, cnt = np.zeros(max_lag + 1), np.zeros(max_lag + 1)
    for seg in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
        if seg.size < int(1.2 * STRIDE_MAX_S * fps):
            continue
        x = s[seg] - np.mean(s[seg])
        ac = np.correlate(x, x, "full")[x.size - 1:]
        if ac[0] <= 0:
            continue
        ac = ac[:max_lag + 1] / ac[0]
        acc[:ac.size] += ac * seg.size
        cnt[:ac.size] += seg.size
    if not cnt[0]:
        return None, 0.0
    ac = np.divide(acc, cnt, out=np.zeros_like(acc), where=cnt > 0)
    lags = np.arange(ac.size) / fps
    # procura só até 2× a passada mais longa aceita (0,8 s em tempo real) para cobrir câmera lenta
    win = (lags >= STRIDE_MIN_S) & (lags <= 2 * STRIDE_MAX_S) & (cnt > 0)
    if not win.any():
        return None, 0.0
    pk, _ = find_peaks(np.where(win, ac, -1))
    pk = [p for p in pk if win[p]]
    if not pk:
        return None, 0.0
    best = max(pk, key=lambda p: ac[p])
    return float(lags[best]), float(ac[best])


# ── Análise ───────────────────────────────────────────────────────────────────
def analyze(xy: np.ndarray, raw: np.ndarray, bodyparts: list[str], fps: float,
            speed_csv: str | None = None) -> dict:
    P = {bp: i for i, bp in enumerate(bodyparts)}
    T = xy.shape[0]
    t = np.arange(T) / fps
    detected = ~np.isnan(np.nanmean(xy[:, :, 0], axis=1)) if T else np.array([], bool)

    # Só frames de perfil entram nas métricas: de frente/de costas a geometria 2D não vale.
    # Perfil = linha pescoço→cauda quase horizontal e com comprimento perto do máximo do clipe.
    body_vec = xy[:, P["neck_base"], :] - xy[:, P["tail_base"], :]
    body_len = np.hypot(body_vec[:, 0], body_vec[:, 1])
    with np.errstate(invalid="ignore", divide="ignore"):
        horiz = np.abs(body_vec[:, 0]) / body_len
        long_enough = body_len >= PROFILE_MIN_LEN * np.nanpercentile(body_len, 90)
    profile = (horiz >= PROFILE_MIN_HORIZ) & long_enough
    profile = np.nan_to_num(profile, nan=0).astype(bool)

    xy = xy.copy()
    xy[~profile] = np.nan
    g = lambda bp: xy[:, P[bp], :]

    # Referências do corpo (só perfil)
    body_pts = [bp for bp in ("back_base", "back_middle", "back_end", "belly_bottom") if bp in P]
    center = np.nanmean(np.stack([g(bp) for bp in body_pts]), axis=0)
    body_len_med = float(np.nanmedian(body_len[profile])) if profile.any() else float("nan")
    # sentido por frame (a transmissão corta entre câmeras): +1 = cavalo virado para a direita da imagem
    facing = np.sign(body_vec[:, 0])
    facing[~profile] = np.nan
    right_share = float(np.nanmean(facing > 0)) if profile.any() else 0.5
    near_side = "direito" if right_share >= 0.5 else "esquerdo"   # virado p/ direita mostra o lado direito

    conf = raw[:, :, 2]
    mean_like = float(np.nanmean(np.where(conf >= 0, conf, np.nan)))

    # Protração de cada pata: posição horizontal relativa ao tronco, no sentido do movimento
    protraction = {}
    for limb, (_, _, paw) in LIMBS.items():
        protraction[limb] = facing * (g(paw)[:, 0] - center[:, 0]) / body_len_med

    # Ciclo da passada por autocorrelação da protração (robusto a picos duplos dentro do ciclo)
    cycles = {limb: _cycle_period(s, fps) for limb, s in protraction.items()}
    good = [(p, r) for p, r in cycles.values() if p and r >= CYCLE_MIN_AUTOCORR]
    cycle_s = float(np.average([p for p, _ in good], weights=[r for _, r in good])) if good else None

    # Picos de protração (um por ciclo) para listar passadas e ler a mão de galope
    peaks_t, peaks_idx = {}, {}
    min_dist = int((0.7 * cycle_s if cycle_s else STRIDE_MIN_S) * fps)
    for limb, s in protraction.items():
        med = np.nanmedian(s) if np.isfinite(s).any() else 0.0
        pk, _ = find_peaks(np.nan_to_num(s, nan=med), distance=max(1, min_dist), prominence=PEAK_PROMINENCE)
        pk = np.array([p for p in pk if not np.isnan(s[p])], dtype=int)
        peaks_idx[limb] = pk
        peaks_t[limb] = t[pk]

    # Passadas: intervalos entre picos consecutivos da mesma pata, sem buraco no meio
    strides = []
    lo_s, hi_s = (0.6 * cycle_s, 1.5 * cycle_s) if cycle_s else (STRIDE_MIN_S, STRIDE_MAX_S)
    for limb, pk in peaks_idx.items():
        s = protraction[limb]
        for a, b in zip(pk[:-1], pk[1:]):
            d = t[b] - t[a]
            if lo_s <= d <= hi_s and not np.isnan(s[a:b + 1]).any():
                strides.append({"membro": limb, "inicio_s": round(float(t[a]), 3), "duracao_s": round(float(d), 3)})
    durations = np.array([s["duracao_s"] for s in strides])

    # Comprimento estimado = velocidade do tracking × duração
    speed_at = None
    if speed_csv and os.path.exists(speed_csv):
        m = pd.read_csv(speed_csv)
        m = m[m["status"].isin(["ok", "ended_lost"])].dropna(subset=["speed_kmh"])
        if len(m) > 5:
            speed_at = lambda tt: float(np.interp(tt, m["tempo_s"], m["speed_kmh"])) / 3.6
    if speed_at:
        for s in strides:
            mid = s["inicio_s"] + s["duracao_s"] / 2
            s["comprimento_m"] = round(speed_at(mid) * s["duracao_s"], 2)

    passada = None
    if cycle_s:
        freq = 1.0 / cycle_s
        lengths = np.array([s["comprimento_m"] for s in strides if "comprimento_m" in s])
        passada = {
            "frequencia_hz": round(float(freq), 2),
            "duracao_media_s": round(float(cycle_s), 3),
            "duracao_dp_s": round(float(np.std(durations)), 3) if durations.size else None,
            "n_passadas": int(durations.size),
            "regularidade_ciclo": round(float(np.mean([r for _, r in good])), 2),
            # comprimento = velocidade × duração: não depende de o vídeo estar em câmera lenta
            "comprimento_m": round(float(np.median(lengths)), 2) if lengths.size else None,
            "referencia_hz": {"faixa": list(REF_STRIDE_HZ),
                              "fonte": "Witte, Hirst & Wilson (2006) J Exp Biol 209:4389 — PSI a 9–17 m/s"},
        }
        if freq < SLOWMO_MAX_HZ:
            fator = REF_STRIDE_HZ[0] / freq
            passada["fator_camera_lenta"] = round(fator, 1)
            passada["alerta"] = (f"ciclo de {freq:.2f} Hz é lento demais para galope em tempo real — "
                                 f"o vídeo provavelmente está em câmera lenta (~{fator:.1f}×). "
                                 f"Frequência e velocidade ficam divididas por esse fator; comprimento e ângulos não mudam.")

    # Mão de galope: o anterior que atinge a protração máxima por último toca o solo por último = mão
    def lead_series(left: str, right: str):
        L, R = peaks_t[left], peaks_t[right]
        out = []
        if passada is None:
            return out
        half = passada["duracao_media_s"] / 2
        for tl in L:
            if R.size == 0:
                break
            j = int(np.argmin(np.abs(R - tl)))
            lag = float(R[j] - tl)
            if abs(lag) < 0.02 or abs(lag) > half:
                continue
            out.append({"t_s": round(float((tl + R[j]) / 2), 3),
                        "mao": "direita" if lag > 0 else "esquerda",
                        "defasagem_s": round(abs(lag), 3)})
        return out

    lead_front = lead_series("anterior_esquerdo", "anterior_direito")
    lead_hind  = lead_series("posterior_esquerdo", "posterior_direito")

    def summarize(series):
        if not series:
            return None
        hands = [x["mao"] for x in series]
        main = max(set(hands), key=hands.count)
        # troca de mão = duas passadas seguidas na mão oposta
        changes = []
        for i in range(1, len(hands) - 1):
            if hands[i] != hands[i - 1] and hands[i + 1] == hands[i]:
                changes.append(series[i]["t_s"])
        consist = hands.count(main) / len(hands)
        conclusive = consist >= LEAD_MIN_CONSISTENCY and len(hands) >= MIN_STRIDES
        return {"predominante": main if conclusive else "inconclusiva",
                "consistencia": round(consist, 2),
                "trocas_s": changes if conclusive else [], "n": len(hands)}

    mao = {
        "anteriores": summarize(lead_front),
        "posteriores": summarize(lead_hind),
        "passadas": lead_front,
    }
    conclusive = lambda s: s and s["predominante"] != "inconclusiva"
    if conclusive(mao["anteriores"]) and conclusive(mao["posteriores"]):
        mao["galope"] = "unido" if mao["anteriores"]["predominante"] == mao["posteriores"]["predominante"] else "desunido"

    # Ângulos (lado voltado para a câmera é mais confiável)
    angulos, angle_series = {}, {}
    for limb, (a, b, c) in LIMBS.items():
        ang = _angle(g(a), g(b), g(c))
        joint = "carpo" if limb.startswith("anterior") else "jarrete"
        key = f"{joint}_{limb.split('_')[1]}"
        st = _stats(ang)
        if st:
            st["lado_da_camera"] = limb.endswith(near_side)
            angulos[key] = st
        angle_series[key] = ang

    # Tronco: inclinação da linha cernelha→garupa (positivo = anterior mais alto)
    v = g("back_base") - g("back_end")
    trunk = np.degrees(np.arctan2(-v[:, 1], facing * v[:, 0]))
    # Cabeça/pescoço: ângulo do pescoço em relação à horizontal
    n = g("nose") - g("neck_base")
    neck = np.degrees(np.arctan2(-n[:, 1], facing * n[:, 0]))

    # Séries reamostradas a 20 Hz para o front
    step = max(1, int(round(fps / 20)))
    idx = np.arange(0, T, step)
    rnd = lambda arr: [None if np.isnan(x) else round(float(x), 1) for x in arr[idx]]
    near_limbs = [k for k in angle_series if k.endswith(near_side)]

    return {
        "modelo": "SuperAnimal-Quadruped (DeepLabCut 3, hrnet_w32) — uso de pesquisa, não comercial",
        "fps": round(fps, 2),
        "frames": int(T),
        "qualidade": {
            "frames_com_cavalo_pct": round(100 * float(detected.mean()), 1),
            "frames_de_perfil_pct": round(100 * float(profile.mean()), 1),
            "confianca_media": round(mean_like, 2),
            "lado_da_camera": near_side,
            "comprimento_corpo_px": round(body_len_med, 1),
        },
        "passada": passada,
        "mao_de_galope": mao,
        "angulos_graus": angulos,
        "tronco_graus": _stats(trunk),
        "pescoco_graus": _stats(neck),
        "passadas": strides,
        "series": {
            "t_s": [round(float(x), 3) for x in t[idx]],
            **{f"angulo_{k}": rnd(angle_series[k]) for k in near_limbs},
            **{f"protracao_{k}": rnd(protraction[k]) for k in LIMBS},
        },
    }


# ── Vídeo com esqueleto ───────────────────────────────────────────────────────
def _put(frame, text, org, scale=0.55, color=(255, 255, 255), thick=1):
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _color_for(a: str, b: str):
    for prefix, col in LIMB_COLORS.items():
        if a.startswith(prefix) or b.startswith(prefix):
            return col
    return AXIS_COLOR


def draw_skeleton(frame, pts, bodyparts: list[str], conf=None) -> None:
    """Desenha o esqueleto (pts [K, 2]) no frame BGR. Pontos com conf < MIN_LIKELIHOOD são omitidos."""
    if pts is None:
        return
    P = {bp: i for i, bp in enumerate(bodyparts)}
    valid = ~np.isnan(pts).any(axis=1)
    if conf is not None:
        valid &= np.nan_to_num(conf) >= MIN_LIKELIHOOD
    segs = [(a, b) for a, b in SKELETON if a in P and b in P and valid[P[a]] and valid[P[b]]]
    ends = lambda a, b: ((int(pts[P[a]][0]), int(pts[P[a]][1])), (int(pts[P[b]][0]), int(pts[P[b]][1])))
    # contorno escuro por baixo: o esqueleto fica legível sobre cavalo claro ou escuro
    for a, b in segs:
        cv2.line(frame, *ends(a, b), (10, 10, 10), 4, cv2.LINE_AA)
    for a, b in segs:
        cv2.line(frame, *ends(a, b), _color_for(a, b), 2, cv2.LINE_AA)
    for bp, i in P.items():
        if not valid[i] or "antler" in bp or "ear" in bp or "mouth" in bp:
            continue
        c = (int(pts[i][0]), int(pts[i][1]))
        cv2.circle(frame, c, 4, (10, 10, 10), -1, cv2.LINE_AA)
        cv2.circle(frame, c, 3, (250, 250, 250), -1, cv2.LINE_AA)


def render_video(video_path: str, xy: np.ndarray, bodyparts: list[str], result: dict,
                 out_path: str, slow: float = 0.5) -> None:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps * slow, (w, h))

    passada = result.get("passada") or {}
    leads = result["mao_de_galope"].get("passadas", [])
    lead_t = np.array([x["t_s"] for x in leads]) if leads else np.array([])
    near = result["qualidade"]["lado_da_camera"]
    ang_key = f"angulo_carpo_{near}"
    series_t = np.array(result["series"]["t_s"])
    series_a = result["series"].get(ang_key)

    f = 0
    while True:
        ok, frame = cap.read()
        if not ok or f >= xy.shape[0]:
            break
        draw_skeleton(frame, xy[f], bodyparts)

        # Painel
        tt = f / fps
        cv2.rectangle(frame, (8, 8), (262, 104), PANEL_BGR, -1)
        cv2.rectangle(frame, (8, 8), (262, 104), BRAND_BGR, 1)
        _put(frame, "PUXA.AI  BIOMECANICA", (16, 28), 0.45, BRAND_BGR, 1)
        if passada:
            _put(frame, f"passada   {passada['frequencia_hz']:.2f} Hz", (16, 50), 0.48)
        if lead_t.size:
            j = int(np.argmin(np.abs(lead_t - tt)))
            if abs(lead_t[j] - tt) < 0.6:
                _put(frame, f"mao       {leads[j]['mao']}", (16, 70), 0.48)
        if series_a is not None and series_t.size:
            j = int(np.argmin(np.abs(series_t - tt)))
            if series_a[j] is not None:
                _put(frame, f"carpo {near[:3]}. {series_a[j]:5.0f} graus", (16, 90), 0.48)
        _put(frame, f"{slow:.1f}x", (w - 50, 26), 0.5, (200, 200, 200))

        writer.write(frame)
        f += 1

    cap.release()
    writer.release()


# ── Execução completa ─────────────────────────────────────────────────────────
def run_analysis(video_path: str, raw: np.ndarray, bodyparts: list[str], out_dir: str,
                 track_csv: str | None = None) -> dict:
    """raw: pontos de um único cavalo, [T, K, 3] (x, y, confiança)."""
    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    cap.release()

    xy = clean_keypoints(raw, fps)
    result = analyze(xy, raw, bodyparts, fps, speed_csv=track_csv)

    # keypoints.csv (cavalo principal, suavizado)
    cols = {"frame": np.arange(xy.shape[0]), "tempo_s": np.round(np.arange(xy.shape[0]) / fps, 4)}
    for i, bp in enumerate(bodyparts):
        if "antler" in bp:
            continue
        cols[f"{bp}_x"] = np.round(xy[:, i, 0], 1)
        cols[f"{bp}_y"] = np.round(xy[:, i, 1], 1)
        cols[f"{bp}_p"] = np.round(raw[:, i, 2], 3)
    pd.DataFrame(cols).to_csv(os.path.join(out_dir, "keypoints.csv"), index=False)

    with open(os.path.join(out_dir, "bio.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    render_video(video_path, xy, bodyparts, result, os.path.join(out_dir, "biomecanica.mp4"))
    return result
