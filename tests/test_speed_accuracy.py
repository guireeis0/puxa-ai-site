"""
Precisão ponta a ponta (YOLO + câmera + cinemática) contra vídeos sintéticos com gabarito.

Lento (~5 min em CPU). Rode com:  python -m pytest tests/test_speed_accuracy.py -m lento
Os vídeos são gerados por tests/synthetic.py a partir do clipe 3D do Pixabay (212734);
sem o clipe, o teste é pulado. Pasta dos vídeos: variável PUXA_SYNTH_DIR.
"""
import json
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eval_speed  # noqa: E402
import synthetic   # noqa: E402

SYNTH_DIR = os.environ.get("PUXA_SYNTH_DIR", r"C:\Users\User\puxa-bio-work\synth")

# limites por cenário: (MAE km/h, |erro da máxima| %, |erro da distância| %)
LIMITS = {
    "fixa_60fps":    (3.0, 8.0, 10.0),   # cavalo pequeno (~110 px): folga da caixa do YOLO pesa mais
    "pan_60fps":     (1.5, 4.0, 5.0),
    "pan_30fps":     (1.5, 4.0, 5.0),
    "tv_zoom_tarja": (1.5, 4.0, 5.0),
    "tv_corte":      (2.5, 5.0, 10.0),
    "tv_dupla_boi":  (2.5, 12.0, 8.0),   # adversarial: animal colado o tempo todo, tracking alterna entre os dois
}

pytestmark = pytest.mark.lento


@pytest.fixture(scope="module")
def synth_dir():
    if not all(os.path.exists(os.path.join(SYNTH_DIR, f"{n}.json")) for n in LIMITS):
        if not os.path.exists(synthetic.SRC_DEFAULT):
            pytest.skip("clipe 3D de origem não encontrado para gerar os vídeos sintéticos")
        synthetic.generate(SYNTH_DIR)
    return SYNTH_DIR


@pytest.fixture(scope="module")
def engine():
    return eval_speed.load_engine(os.path.join(os.path.dirname(HERE), "app"))


@pytest.mark.parametrize("scenario", list(LIMITS))
def test_precisao(scenario, synth_dir, engine):
    truth = json.load(open(os.path.join(synth_dir, f"{scenario}.json"), encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        r = eval_speed.evaluate(engine, os.path.join(synth_dir, f"{scenario}.mp4"), truth, tmp)
    mae, max_pct, dist_pct = LIMITS[scenario]
    assert r["MAE_kmh"] is not None and r["MAE_kmh"] <= mae, r
    assert abs(r["max_erro_%"]) <= max_pct, r
    assert abs(r["dist_erro_%"]) <= dist_pct, r
