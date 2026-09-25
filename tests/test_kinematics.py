"""Testes unitários da cinemática offline (sem vídeo): trajetórias sintéticas com resposta exata."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from kinematics import solve, summarize  # noqa: E402

FPS, W, H = 60.0, 1280, 720
L_M = 2.4          # régua do motor (largura da caixa = 2,4 m)
PX_PER_M = 100.0   # escala do "mundo" nos testes → caixa de 240 px


def make(v_ms, pan_px_per_frame=0.0, zoom_per_frame=1.0, cut_at=None, gap=None, n=None):
    """Cavalo andando a v_ms (array ou constante) com câmera opcional; devolve entradas do solve()."""
    n = n or int(8 * FPS)
    t = np.arange(n) / FPS
    v = np.full(n, v_ms) if np.isscalar(v_ms) else np.asarray(v_ms)
    x_world = np.concatenate([[0], np.cumsum((v[1:] + v[:-1]) / 2 / FPS)])   # metros
    cams, pos, boxes, cut = [], [], [], np.zeros(n, bool)
    cam_x, z = 0.0, 1.0        # posição da câmera (px do mundo) e zoom acumulado
    for i in range(n):
        A = np.array([[1.0, 0, 0], [0, 1.0, 0]])
        if i > 0:
            if cut_at is not None and i == int(cut_at * FPS):
                cut[i] = True
                z *= 0.7
            else:
                # câmera: panorâmica em torno do centro + zoom em torno do centro da imagem
                s = zoom_per_frame
                A = np.array([[s, 0, (1 - s) * W / 2 - pan_px_per_frame * s],
                              [0, s, (1 - s) * H / 2]])
                cam_x += pan_px_per_frame / z
                z *= s
        cams.append(A)
        # posição do cavalo na imagem: (mundo - câmera) * zoom, em torno do centro
        xi = W / 2 + (x_world[i] * PX_PER_M - cam_x - 300) * z
        yi = H / 2
        bw, bh = L_M * PX_PER_M * z, L_M / 1.6 * PX_PER_M * z   # proporção de perfil real (config)
        pos.append((xi, yi))
        boxes.append((xi - bw / 2, yi - bh / 2, xi + bw / 2, yi + bh / 2))
    pos, boxes = np.array(pos), np.array(boxes)
    if gap is not None:
        a, b = int(gap[0] * FPS), int(gap[1] * FPS)
        pos[a:b] = np.nan
        boxes[a:b] = np.nan
    return t, pos, boxes, cams, cut, v


def run(t, pos, boxes, cams, cut):
    return solve(t, pos, boxes, cams, cut, 10_000, 10_000)   # quadro "infinito": nenhuma caixa encosta na borda


def core(x, t, a=1.5, b=1.5):
    """Trecho central (sem as bordas do filtro)."""
    return x[(t > a) & (t < t[-1] - b)]


def test_velocidade_constante_camera_parada():
    t, pos, boxes, cams, cut, v = make(12.0)
    k = run(t, pos, boxes, cams, cut)
    assert np.allclose(core(k["speed"], t), 12.0, rtol=0.01)


def test_panoramica_acompanhando():
    # câmera anda 10 px/frame para a direita: sem compensação a velocidade medida cairia pela metade
    t, pos, boxes, cams, cut, v = make(12.0, pan_px_per_frame=10.0)
    k = run(t, pos, boxes, cams, cut)
    assert np.allclose(core(k["speed"], t), 12.0, rtol=0.01)


def test_zoom_continuo():
    t, pos, boxes, cams, cut, v = make(12.0, pan_px_per_frame=6.0, zoom_per_frame=1.0015)
    k = run(t, pos, boxes, cams, cut)
    assert np.allclose(core(k["speed"], t), 12.0, rtol=0.02)


def test_corte_de_cena_nao_gera_salto():
    t, pos, boxes, cams, cut, v = make(12.0, pan_px_per_frame=8.0, cut_at=4.0)
    k = run(t, pos, boxes, cams, cut)
    s = k["speed"]
    assert np.nanmax(s) < 12.0 * 1.05
    assert np.allclose(core(s, t, 1.5, 1.5)[np.isfinite(core(s, t, 1.5, 1.5))], 12.0, rtol=0.03)


def test_buraco_curto_no_tracking():
    t, pos, boxes, cams, cut, v = make(12.0, pan_px_per_frame=8.0, gap=(3.0, 3.3))
    k = run(t, pos, boxes, cams, cut)
    assert np.allclose(core(k["speed"], t), 12.0, rtol=0.02)


def test_aceleracao_e_resumo():
    n = int(10 * FPS)
    tt = np.arange(n) / FPS
    v = np.clip(tt - 1.0, 0, None) * 4.0          # 4 m/s² a partir de 1 s
    v = np.minimum(v, 14.0)                        # até 14 m/s (50,4 km/h)
    t, pos, boxes, cams, cut, v = make(v, pan_px_per_frame=5.0, n=n)
    k = run(t, pos, boxes, cams, cut)
    s = summarize(t, k["speed"], k["accel"], np.isfinite(pos[:, 0]))
    assert s["ok"]
    assert abs(s["max_speed_kmh"] - 50.4) / 50.4 < 0.03
    assert 3.0 < s["max_accel_m_s2"] < 4.6
    names = [p["fase"] for p in s["phases"]]
    assert names == ["arrancada", "corrida", "frenagem"]


def test_caixa_fundida_com_boi_usa_altura():
    # em 2 s a caixa "engole" o boi ao lado: largura dobra, altura igual → régua não pode mudar
    t, pos, boxes, cams, cut, v = make(12.0, pan_px_per_frame=8.0)
    boxes = boxes.copy()
    a, b = int(3 * FPS), int(5 * FPS)
    boxes[a:b, 2] += boxes[a:b, 2] - boxes[a:b, 0]
    k = run(t, pos, boxes, cams, cut)
    assert np.allclose(core(k["speed"], t), 12.0, rtol=0.02)


def test_tracking_pula_para_animal_ao_lado():
    # por 2 s o tracking segue o boi, 1,3 m à frente, e depois volta: a máxima não pode inflar
    t, pos, boxes, cams, cut, v = make(12.0, pan_px_per_frame=8.0)
    pos, boxes = pos.copy(), boxes.copy()
    a, b = int(3 * FPS), int(5 * FPS)
    shift = 1.3 * PX_PER_M
    pos[a:b, 0] += shift
    boxes[a:b, [0, 2]] += shift
    k = run(t, pos, boxes, cams, cut)
    s = summarize(t, k["speed"], k["accel"], np.isfinite(pos[:, 0]))
    assert abs(s["max_speed_kmh"] - 43.2) / 43.2 < 0.04
    assert k["jumps_removed"] >= 2


def test_ponto_implausivel_e_descartado():
    t, pos, boxes, cams, cut, v = make(12.0)
    pos = pos.copy()
    pos[200:203, 0] += 4000       # salto absurdo de posição (falha de detecção)
    k = run(t, pos, boxes, cams, cut)
    assert np.nanmax(k["speed"]) * 3.6 <= 75.0
