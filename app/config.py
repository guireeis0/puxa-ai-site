import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Modelo ──────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "models", "yolov8n.pt"))

# ── Detecção e tracking ──────────────────────────────────────────────────────
DETECT_CONF           = 0.35   # confiança mínima da detecção do cavalo
# Resolução de entrada do YOLO. Em vídeo grande (≥ 1280 px) com o cavalo pequeno no quadro,
# 640 perde o animal em ~40% dos frames; 960 recupera quase todos (≈1,75× mais lento).
DETECT_IMGSZ          = 640
DETECT_IMGSZ_LARGE    = 960
DETECT_LARGE_MIN_W    = 1280
REACQUIRE_MAX_DIST_PX = 140.0  # raio mínimo (px) para reidentificar o cavalo; cresce com o tamanho da caixa
REACQUIRE_BOX_FRAC    = 0.6    # raio de reaquisição = max(REACQUIRE_MAX_DIST_PX, fração × largura da caixa)
MIN_BOX_AREA          = 800    # área mínima (px²) para considerar uma detecção válida
LOCK_ID                    = True  # trava o tracking no primeiro animal detectado
UNLOCK_AFTER_LOST_SECONDS  = 2.0   # segundos sem o animal para liberar o lock
START_OK_HOLD_FRAMES   = 5     # frames consecutivos com detecção para confirmar início
LOST_END_SECONDS       = 3.0   # segundos sem detecção (depois de correr) para encerrar a prova
SCENE_CUT_THRESHOLD    = 0.55  # correlação de histograma abaixo disso = corte de câmera

# ── Régua metro/pixel ────────────────────────────────────────────────────────
# Largura da caixa do cavalo de perfil a galope (nariz→cauda). Sem calibração pela pista,
# é a maior fonte de incerteza das medidas absolutas (±15–20%).
HORSE_LENGTH_METERS   = 2.4
# Proporção largura/altura do cavalo a galope de perfil medida pela pose em vídeos reais
# (mediana 1,56–1,78) → altura da caixa (topo da cabeça → cascos) ≈ 2,4 / 1,6 = 1,5 m.
PROFILE_BOX_ASPECT    = 1.6
HORSE_HEIGHT_METERS   = HORSE_LENGTH_METERS / PROFILE_BOX_ASPECT
PROFILE_MIN_ASPECT    = 1.15   # largura/altura mínima da caixa para usá-la como régua (de perfil)
# Caixa mais "esticada" que isso = cavalo junto com boi/outro cavalo (o YOLO funde as caixas):
# a largura deixa de valer e a régua usa só a altura, que muda pouco com animais lado a lado.
MERGED_MIN_ASPECT     = 2.0
# Caixa bem mais "estreita" que o perfil típico = animal parcialmente escondido atrás de outro:
# a largura encolhe e a altura continua valendo
OCCLUDED_MAX_ASPECT   = PROFILE_BOX_ASPECT * 0.85
EDGE_MARGIN_PX        = 3      # caixa encostada na borda está cortada → não serve de régua
SCALE_WINDOW_S        = 1.5    # janela da mediana móvel da régua

# ── Filtragem (offline, fase zero) ───────────────────────────────────────────
# Corte abaixo da frequência de passada (~2 Hz a galope): velocidade média por passada,
# como os sistemas de GPS de corrida reportam.
SPEED_CUTOFF_HZ       = 1.0
ACCEL_CUTOFF_HZ       = 0.8
MAX_GAP_S             = 0.5    # buracos maiores no tracking quebram a trajetória
# Mudança de largura da caixa entre frames acima disso = fusão/separação com boi ou outro cavalo;
# o deslocamento passa a ser medido pela borda que continua no cavalo, não pelo centro
SHAPE_CHANGE_FRAC     = 0.15
# Salto de posição = deslocamento no frame > FATOR × mediana local + MARGEM (m/s): descartado
JUMP_WINDOW_S         = 0.5
JUMP_FACTOR           = 1.6
JUMP_MARGIN_MS        = 2.0
PLAUSIBLE_MAX_KMH     = 75.0   # acima disso é falha de medida (não corta: descarta o ponto)

# ── Janela e fases da corrida ────────────────────────────────────────────────
MOVE_START_FRAC       = 0.15   # início do movimento: velocidade ≥ 15% do pico
MAX_SPEED_WINDOW_S    = 0.5    # velocidade máxima = maior média sustentada nessa janela
PHASE_HIGH_FRAC       = 0.80   # corrida = trecho em que a velocidade fica ≥ 80% do pico

# ── Pista (Regulamento Geral ABVAQ 2017/2018 e 2024) ─────────────────────────
# O regulamento define a faixa de pontuação como linhas paralelas a 9 m uma da outra;
# o comprimento da pista não é fixado (varia por parque), por isso as fases da corrida
# são detectadas pela curva de velocidade e não por distâncias fixas.
FAIXA_PONTUACAO_M     = 9.0
AREIA_PROFUNDIDADE_M  = 0.40
# Usados pelo módulo VAR (estimativa grosseira da posição da queda): pista típica de 160 m
# com a faixa começando aos 100 m. Não são usados no cálculo de velocidade.
PISTA_LIMIT_M         = 160.0
DERRUBADA_START_M     = 100.0
DERRUBADA_END_M       = DERRUBADA_START_M + FAIXA_PONTUACAO_M

# ── Estabilização do HUD ─────────────────────────────────────────────────────
HUD_BOX_EMA_ALPHA      = 0.25  # suavização da caixa desenhada no vídeo

# ── Upload ───────────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS    = {"mp4", "mov", "avi", "mkv"}
MAX_UPLOAD_BYTES      = 100 * 1024 * 1024  # 100 MB
