import cv2
import numpy as np

# =========================
# CONFIG ESTILO F1
# =========================
FONT_MAIN = cv2.FONT_HERSHEY_SIMPLEX
FONT_SMALL = cv2.FONT_HERSHEY_SIMPLEX

COLOR_WHITE = (255, 255, 255)
COLOR_GRAY  = (170, 170, 170)
COLOR_GREEN = (0, 220, 130)
COLOR_RED   = (0, 60, 255)
COLOR_BLACK = (0, 0, 0)

# =========================
# FUNÇÃO AUXILIAR: TEXTO COM BORDA
# =========================
def _draw_text_with_outline(frame, text, pos, font, scale, color, thickness):
    """Desenha texto com borda preta para garantir leitura em fundos claros (areia/céu)."""
    # Desenha a sombra/borda preta primeiro (mais grossa)
    cv2.putText(frame, text, pos, font, scale, COLOR_BLACK, thickness + 2, cv2.LINE_AA)
    # Desenha o texto principal por cima
    cv2.putText(frame, text, pos, font, scale, color, thickness, cv2.LINE_AA)

# =========================
# BOX COM CANTOS (estilo tracker)
# =========================
def draw_corner_box(frame, x1, y1, x2, y2, style="modern"):
    """
    Desenha box ao redor do animal com diferentes estilos.
    style: "modern" (futurista), "simple" (simples), "filled" (com fundo)
    """
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

    if style == "modern":
        c = 25
        t = 2
        color = (0, 220, 130)

        # Top-Left
        cv2.line(frame, (x1, y1), (x1 + c, y1), color, t)
        cv2.line(frame, (x1, y1), (x1, y1 + c), color, t)

        # Top-Right
        cv2.line(frame, (x2, y1), (x2 - c, y1), color, t)
        cv2.line(frame, (x2, y1), (x2, y1 + c), color, t)

        # Bottom-Left
        cv2.line(frame, (x1, y2), (x1 + c, y2), color, t)
        cv2.line(frame, (x1, y2), (x1, y2 - c), color, t)

        # Bottom-Right
        cv2.line(frame, (x2, y2), (x2 - c, y2), color, t)
        cv2.line(frame, (x2, y2), (x2, y2 - c), color, t)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 180, 100), 1)

    elif style == "simple":
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 130), 2)

    elif style == "filled":
        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 220, 130), -1)
        cv2.addWeighted(overlay, 0.1, frame, 0.9, 0, frame)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 130), 2)

# =========================
# BARRA VERTICAL PONTILHADA (canto direito)
# =========================
def draw_accel_bar_vertical_dotted(
    frame,
    accel: float,
    max_accel: float = 20.0,
    x_offset: int = 28,
    y_top: int = 30,
    height: int = 200,
    bar_w: int = 12,
    dash: int = 9,
    gap: int = 6,
):
    h, w, _ = frame.shape
    x = w - x_offset
    y_bottom = y_top + height

    # Prevenção contra saída de tela
    if x < 0 or y_bottom > h:
        return

    # Normaliza 0..1 (usa magnitude)
    t = 0.0 if max_accel <= 0 else min(abs(accel) / max_accel, 1.0)

    fill_h = int(height * t)
    fill_top = y_bottom - fill_h

    # ✅ OTIMIZAÇÃO: ROI (Region of Interest) Blending
    # Aplica transparência APENAS na área da barra, poupando processamento de milhões de pixels
    roi = frame[y_top:y_bottom, x:x+bar_w]
    if roi.size > 0:
        black_rect = np.zeros_like(roi)
        cv2.addWeighted(black_rect, 0.5, roi, 0.5, 0, roi)
    
    cv2.rectangle(frame, (x, y_top), (x + bar_w, y_bottom), (110, 110, 110), 1)

    # Cor conforme sinal da aceleração
    base_color = COLOR_GREEN if accel >= 0 else COLOR_RED

    # Dashes de baixo pra cima
    yy = y_bottom - dash
    while yy + dash > fill_top:
        y1 = max(fill_top, yy)
        y2 = min(y_bottom, yy + dash)

        cv2.rectangle(frame, (x + 1, int(y1)), (x + bar_w - 1, int(y2)), base_color, -1)
        yy -= (dash + gap)

# =========================
# HUD PRINCIPAL
# =========================
_smooth_speed = 0.0
_smooth_accel = 0.0

def draw_hud(
    frame,
    x: float,
    y: float,
    speed_kmh: float,
    accel_m_s2: float,
    max_speed: float = None,
    max_accel_for_bar: float = 20.0
):
    global _smooth_speed, _smooth_accel

    x, y = int(x), int(y)

    # Suavização EMA (0.92 = filtra tremidas, mas responde rápido)
    alpha = 0.92
    _smooth_speed = (alpha * _smooth_speed) + ((1 - alpha) * speed_kmh)
    _smooth_accel = (alpha * _smooth_accel) + ((1 - alpha) * accel_m_s2)

    # Texto Velocidade com Borda
    _draw_text_with_outline(frame, f"{_smooth_speed:.1f}", (x + 10, y - 65), FONT_MAIN, 1.5, COLOR_WHITE, 3)
    _draw_text_with_outline(frame, "km/h", (x + 110, y - 50), FONT_SMALL, 0.6, COLOR_GRAY, 1)

    # Texto Aceleração com Borda
    _draw_text_with_outline(frame, f"{_smooth_accel:.2f}", (x + 10, y - 35), FONT_MAIN, 0.9, COLOR_WHITE, 2)
    _draw_text_with_outline(frame, "m/s2", (x + 100, y - 20), FONT_SMALL, 0.5, COLOR_GRAY, 1)

    # Renderiza a barra lateral otimizada
    draw_accel_bar_vertical_dotted(frame, accel=_smooth_accel, max_accel=max_accel_for_bar)