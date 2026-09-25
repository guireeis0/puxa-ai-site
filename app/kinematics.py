"""
Cinemática offline do cavalo a partir do tracking por frame.

A análise acontece depois do vídeo inteiro ser lido, então usamos filtros de fase zero (sem
atraso) em vez de médias móveis causais. Etapas:

1. Deslocamento na imagem descontado o movimento da câmera (matrizes 2x3 por frame).
2. Régua metro/pixel pela largura da caixa do cavalo, só em frames confiáveis (perfil, caixa
   inteira dentro do quadro), com mediana móvel e acompanhando o zoom estimado da câmera.
3. Trajetória em metros → filtro Butterworth passa-baixa ida-e-volta (média por passada,
   como os sistemas de GPS de corrida) → velocidade e aceleração por diferenças centrais.
4. Janela da corrida (início do movimento → último frame rastreado), máximos, média, distância
   e fases pela própria curva de velocidade (arrancada, corrida, frenagem/derrubada).
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt

from config import (
    HORSE_LENGTH_METERS, HORSE_HEIGHT_METERS, MERGED_MIN_ASPECT, SPEED_CUTOFF_HZ, ACCEL_CUTOFF_HZ, SCALE_WINDOW_S, MAX_GAP_S,
    JUMP_WINDOW_S, JUMP_FACTOR, JUMP_MARGIN_MS, SHAPE_CHANGE_FRAC,
    PROFILE_MIN_ASPECT, EDGE_MARGIN_PX, MOVE_START_FRAC, PLAUSIBLE_MAX_KMH, PHASE_HIGH_FRAC,
    MAX_SPEED_WINDOW_S, OCCLUDED_MAX_ASPECT,
)


def _compose(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """A∘B para matrizes 2x3 (aplica B e depois A)."""
    A3 = np.vstack([A, [0, 0, 1]]); B3 = np.vstack([B, [0, 0, 1]])
    return (A3 @ B3)[:2]


def _apply(A: np.ndarray, p) -> np.ndarray:
    return A[:, :2] @ np.asarray(p, float) + A[:, 2]


def _apply_scale(A: np.ndarray) -> float:
    """Fator de zoom de uma matriz 2x3 de semelhança."""
    return float(np.sqrt(abs(np.linalg.det(A[:, :2]))))


def _lowpass(x: np.ndarray, fps: float, fc: float) -> np.ndarray:
    """Butterworth 2ª ordem ida-e-volta (4ª ordem efetiva, fase zero); trechos curtos só são alisados."""
    nyq = fps / 2.0
    if fc >= nyq * 0.95:
        return x
    b, a = butter(2, fc / nyq)
    if x.size <= 3 * max(len(a), len(b)) * 3:
        k = max(1, min(x.size // 3, int(fps / fc / 4)))
        return np.convolve(np.pad(x, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), "valid")
    return filtfilt(b, a, x, padtype="odd", padlen=min(x.size - 1, int(3 * fps / fc)))


def _segments(mask: np.ndarray):
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    return np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)


def solve(t: np.ndarray, pos: np.ndarray, boxes: np.ndarray, cams: list, cut: np.ndarray,
          frame_w: int, frame_h: int) -> dict:
    """
    t      [N] tempo de cada frame (s)
    pos    [N,2] centro do cavalo na imagem (NaN quando não rastreado)
    boxes  [N,4] caixa x1,y1,x2,y2 (NaN quando não rastreado)
    cams   [N] matrizes 2x3 do frame anterior → atual (identidade no 1º frame e em cortes;
           None quando o movimento da câmera é desconhecido naquele frame)
    cut    [N] True no primeiro frame de cada cena nova
    """
    N = len(t)
    fps = float(1.0 / np.median(np.diff(t))) if N > 2 else 30.0
    ok = ~np.isnan(pos[:, 0])

    # ── 1. deslocamentos em px (coordenadas do frame atual) entre observações válidas ──
    dpx = np.full((N, 2), np.nan)
    zoom = np.ones(N)                       # fator de zoom da câmera entre frames
    for i in range(1, N):
        if not cut[i] and cams[i] is not None:
            zoom[i] = float(np.sqrt(abs(np.linalg.det(cams[i][:, :2]))))
    last_i, carry = None, None              # último frame válido e transformação acumulada desde ele
    prev_dx = None                          # último deslocamento horizontal aceito (px/frame)
    for i in range(N):
        if cut[i] or cams[i] is None:
            # corte de cena ou câmera desconhecida: não dá para ligar este frame ao anterior
            last_i, carry, prev_dx = None, None, None
        elif carry is not None:
            carry = _compose(cams[i], carry)
        if ok[i]:
            if last_i is not None and (t[i] - t[last_i]) <= MAX_GAP_S:
                span = i - last_i
                b0, b1 = boxes[last_i], boxes[i]
                ym = 0.5 * (b0[1] + b0[3])
                # bordas e centro do frame anterior levados para o frame atual (desconta a câmera)
                l0, r0, c0 = (_apply(carry, (b0[0], ym))[0], _apply(carry, (b0[2], ym))[0],
                              _apply(carry, pos[last_i])[0])
                g0 = _apply(carry, (0.5 * (b0[0] + b0[2]), b0[3]))[1]      # linha dos cascos
                w0, w1 = b0[2] - b0[0], b1[2] - b1[0]
                dx_c, dx_l, dx_r = pos[i][0] - c0, b1[0] - l0, b1[2] - r0
                if abs(w1 - w0 * _apply_scale(carry)) > SHAPE_CHANGE_FRAC * max(w1, 1e-6):
                    # caixa mudou de forma (fundiu/separou do boi ou do outro cavalo): um lado pulou,
                    # o outro continua no cavalo → usa a borda coerente com o movimento anterior
                    if prev_dx is not None:
                        dx = dx_l if abs(dx_l / span - prev_dx) <= abs(dx_r / span - prev_dx) else dx_r
                    else:
                        dx = dx_l if abs(dx_l) <= abs(dx_r) else dx_r
                else:
                    dx = dx_c
                dy = b1[3] - g0
                d = np.array([dx, dy])
                # espalha o deslocamento pelos frames do buraco (velocidade constante no intervalo)
                dpx[last_i + 1:i + 1] = d / span
                prev_dx = dx / span
            last_i, carry = i, np.array([[1.0, 0, 0], [0, 1.0, 0]])

    # ── 2. régua metro/pixel ──
    w = boxes[:, 2] - boxes[:, 0]
    h = boxes[:, 3] - boxes[:, 1]
    inside = (boxes[:, 0] > EDGE_MARGIN_PX) & (boxes[:, 2] < frame_w - EDGE_MARGIN_PX) & \
             (boxes[:, 1] > EDGE_MARGIN_PX) & (boxes[:, 3] < frame_h - EDGE_MARGIN_PX)
    with np.errstate(invalid="ignore", divide="ignore"):
        aspect = w / h
        lateral = aspect >= PROFILE_MIN_ASPECT
        # largura não confiável: caixa esticada (fundida com boi/outro cavalo) ou encolhida
        # (animal parcialmente escondido atrás de outro) → só a altura serve de régua
        width_bad = (aspect > MERGED_MIN_ASPECT) | (aspect < OCCLUDED_MAX_ASPECT)
        per_px = np.where(width_bad, HORSE_HEIGHT_METERS / h,
                          0.5 * (HORSE_LENGTH_METERS / w + HORSE_HEIGHT_METERS / h))
    good_scale = ok & inside & lateral
    # zoom acumulado por cena: r = (m/px)·Z deve ser ~constante se só o zoom muda
    Z = np.ones(N)
    for i in range(1, N):
        Z[i] = 1.0 if cut[i] else Z[i - 1] * zoom[i]
    r = np.where(good_scale, per_px * Z, np.nan)
    k = np.full(N, np.nan)
    half = int(SCALE_WINDOW_S * fps / 2)
    scene_id = np.cumsum(cut)
    for sid in np.unique(scene_id):
        idx = np.flatnonzero(scene_id == sid)
        rs = r[idx]
        if np.isfinite(rs).sum() == 0:
            continue
        for j, i in enumerate(idx):
            win = rs[max(0, j - half): j + half + 1]
            win = win[np.isfinite(win)]
            if win.size >= 3:
                k[i] = np.median(win)
        # frames da cena sem janela válida usam a mediana da cena
        k[idx] = np.where(np.isfinite(k[idx]), k[idx], np.nanmedian(rs))
    m_per_px = k / Z

    # ── 3. trajetória em metros, filtrada ──
    dm = dpx * m_per_px[:, None]

    # saltos de posição (tracking pulando para o boi/outro cavalo por um instante, caixa fundindo):
    # a velocidade de um cavalo não muda de um frame para outro, então deslocamentos muito acima da
    # mediana local são descartados antes do filtro — senão viram picos falsos de velocidade máxima
    # Filtro de Hampel por componente: valor fora de mediana ± k·MAD (ou da margem física mínima)
    # é trocado pela mediana local — remove o pico sem abrir buraco na trajetória.
    half_j = max(2, int(JUMP_WINDOW_S * fps / 2))
    jumps_removed = 0
    for c in range(2):
        x = dm[:, c] * fps                                  # m/s
        fixed = x.copy()
        for i in np.flatnonzero(np.isfinite(x)):
            win = x[max(0, i - half_j): i + half_j + 1]
            win = win[np.isfinite(win)]
            if win.size < 5:
                continue
            med = np.median(win)
            mad = 1.4826 * np.median(np.abs(win - med))
            if abs(x[i] - med) > max(JUMP_FACTOR * 3 * mad, JUMP_MARGIN_MS):
                fixed[i] = med
                jumps_removed += 1
        dm[:, c] = fixed / fps
    speed = np.full(N, np.nan)
    accel = np.full(N, np.nan)
    measured = np.isfinite(dm[:, 0])
    X = np.full((N, 2), np.nan)
    for seg in _segments(measured):
        if seg.size < max(5, int(0.25 * fps)):
            continue
        xy = np.cumsum(dm[seg], axis=0)
        xs = _lowpass(xy[:, 0], fps, SPEED_CUTOFF_HZ)
        ys = _lowpass(xy[:, 1], fps, SPEED_CUTOFF_HZ)
        X[seg] = np.stack([xs, ys], 1)
        ts = t[seg]
        v = np.hypot(np.gradient(xs, ts), np.gradient(ys, ts))
        speed[seg] = v
        accel[seg] = np.gradient(_lowpass(v, fps, ACCEL_CUTOFF_HZ), ts)

    plausible = speed * 3.6 <= PLAUSIBLE_MAX_KMH
    glitch_pct = float(np.mean(~plausible[np.isfinite(speed)])) * 100 if np.isfinite(speed).any() else 0.0
    speed = np.where(plausible, speed, np.nan)
    accel = np.where(plausible, accel, np.nan)

    return {"fps": fps, "speed": speed, "accel": accel, "m_per_px": m_per_px,
            "scale_frames": int(good_scale.sum()), "glitch_pct": round(glitch_pct, 1),
            "jumps_removed": jumps_removed,
            "measured": np.isfinite(speed)}


def summarize(t: np.ndarray, speed: np.ndarray, accel: np.ndarray, tracked: np.ndarray) -> dict:
    """Janela da corrida, máximos, média, distância e fases pela curva de velocidade."""
    valid = np.isfinite(speed)
    if valid.sum() < 5:
        return {"ok": False}
    vmax_all = float(np.nanmax(speed))
    moving = valid & (speed >= MOVE_START_FRAC * vmax_all)
    start_i = int(np.flatnonzero(moving)[0])
    end_i = int(np.flatnonzero(tracked)[-1])
    win = np.arange(start_i, end_i + 1)
    vw = np.where(np.isfinite(speed[win]), speed[win], np.nan)
    # preenche buracos curtos por interpolação para integrar a distância
    fill = np.interp(t[win], t[win][np.isfinite(vw)], vw[np.isfinite(vw)])
    distance = float(np.trapezoid(fill, t[win])) if hasattr(np, "trapezoid") else float(np.trapz(fill, t[win]))
    duration = float(t[end_i] - t[start_i]) or 1e-3
    # velocidade máxima = maior média sustentada em MAX_SPEED_WINDOW_S (resíduo de ruído de um
    # frame não conta como pico — um cavalo não "sustenta" 0,1 s de pico)
    fps = float(1.0 / np.median(np.diff(t)))
    k_w = max(1, int(round(MAX_SPEED_WINDOW_S * fps)))
    sustained = np.convolve(fill, np.ones(k_w) / k_w, mode="same") if fill.size >= k_w else fill
    j_max = int(np.argmax(sustained))
    i_max = int(win[j_max])
    vmax = float(sustained[j_max])

    a_w = accel[win]
    a_valid = np.isfinite(a_w)
    max_accel = float(np.nanmax(a_w)) if a_valid.any() else 0.0
    max_decel = float(-np.nanmin(a_w)) if a_valid.any() else 0.0
    pos_acc = a_w[a_valid & (a_w > 0.5)]
    impulse = float(np.percentile(pos_acc, 90)) if pos_acc.size else 0.0

    # Fases: arrancada até atingir PHASE_HIGH_FRAC do pico; corrida enquanto fica acima;
    # frenagem/derrubada depois da última vez acima desse patamar.
    high = np.flatnonzero(sustained >= PHASE_HIGH_FRAC * vmax)
    a_end = int(win[high[0]]) if high.size else i_max
    c_end = int(win[high[-1]]) if high.size else i_max
    def phase(name, i0, i1):
        if i1 <= i0:
            return {"fase": name, "inicio_s": round(float(t[i0]), 2), "duracao_s": 0.0,
                    "distancia_m": 0.0, "vel_media_kmh": None}
        sl = slice(i0 - start_i, i1 - start_i + 1)
        d = float(np.trapezoid(fill[sl], t[i0:i1 + 1])) if hasattr(np, "trapezoid") else float(np.trapz(fill[sl], t[i0:i1 + 1]))
        dur = float(t[i1] - t[i0])
        return {"fase": name, "inicio_s": round(float(t[i0]), 2), "duracao_s": round(dur, 2),
                "distancia_m": round(d, 1), "vel_media_kmh": round(d / dur * 3.6, 1) if dur > 0 else None}
    phases = [phase("arrancada", start_i, a_end), phase("corrida", a_end, c_end), phase("frenagem", c_end, end_i)]

    return {
        "ok": True,
        "start_i": start_i, "end_i": end_i, "i_max": i_max,
        "max_speed_kmh": vmax * 3.6,
        "avg_speed_kmh": distance / duration * 3.6,
        "distance_m": distance,
        "run_time_s": duration,
        "time_to_max_speed_s": float(t[i_max] - t[start_i]),
        "max_accel_m_s2": max_accel,
        "max_decel_m_s2": max_decel,
        "impulse_m_s2": impulse,
        "phases": phases,
        "measured_pct": float(np.mean(np.isfinite(speed[win]))) * 100,
    }
