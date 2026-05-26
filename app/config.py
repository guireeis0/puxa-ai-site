import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Modelo ──────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "models", "yolov8n.pt"))

# ── Velocidade e suavização ──────────────────────────────────────────────────
MAX_REAL_SPEED_KMH   = 58.0   # velocidade máxima realista (km/h)
SMOOTHING            = 0.96   # fator EMA global do SpeedTracker

# ── Detecção e tracking ──────────────────────────────────────────────────────
REACQUIRE_MAX_DIST_PX = 140.0  # distância máxima (px) para reidentificar o cavalo
MIN_BOX_AREA          = 800    # área mínima (px²) para considerar uma detecção válida
HORSE_LENGTH_METERS   = 1.9    # comprimento médio do cavalo (m) — base da régua de escala

# ── Escala pixel → metro ─────────────────────────────────────────────────────
SCALE_EMA_ALPHA      = 0.10   # suavização da régua de escala
SCALE_MIN            = 0.001  # escala mínima permitida
SCALE_MAX            = 0.020  # escala máxima permitida
SCALE_JUMP_MAX_RATIO = 1.25   # variação máxima entre frames (trava anti-salto)

# ── Início / fim da prova ────────────────────────────────────────────────────
START_OK_HOLD_FRAMES   = 5    # frames consecutivos com detecção para confirmar início
LOST_END_SECONDS       = 3.0  # segundos sem detecção para encerrar a prova
MIN_RUN_SECONDS        = 3.0  # duração mínima válida de corrida
MIN_RUN_DISTANCE_M     = 15.0 # distância mínima válida de corrida (m)
MOVEMENT_MIN_SPEED_KMH = 8.0  # velocidade mínima para confirmar movimento real
MOVEMENT_HOLD_FRAMES   = 10   # frames confirmando movimento antes de acumular distância
PISTA_LIMIT_M          = 120.0 # distância máxima da pista (m)

# ── Lock em um único animal ──────────────────────────────────────────────────
LOCK_ID                    = True  # trava o tracking no primeiro animal detectado
UNLOCK_AFTER_LOST_SECONDS  = 2.0   # segundos sem o animal para liberar o lock

# ── Estabilização do HUD ─────────────────────────────────────────────────────
HUD_BOX_EMA_ALPHA      = 0.25  # suavização da caixa no vídeo
HUD_VALUE_EMA_ALPHA    = 0.25  # suavização dos valores exibidos
HUD_UPDATE_EVERY_N_FRAMES = 2  # atualiza o HUD a cada N frames

# ── Upload ───────────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS    = {"mp4", "mov", "avi", "mkv"}
MAX_UPLOAD_BYTES      = 100 * 1024 * 1024  # 100 MB
