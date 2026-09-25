"""
Estimativa do movimento da câmera entre frames consecutivos.

Transmissões e filmagens amadoras acompanham o cavalo (panorâmica/zoom). Sem compensar isso,
o cavalo parece parado na imagem e a velocidade medida cai para perto de zero.

Método: pontos de textura do fundo (fora das caixas dos cavalos) são seguidos por fluxo óptico
Lucas-Kanade e um modelo de semelhança (translação + escala + rotação) é ajustado com RANSAC.
Prioriza o chão perto das patas, que está na mesma profundidade do cavalo — em câmera que se
desloca junto (travelling), árvores ao fundo se movem menos que o chão e subestimariam o pan.
"""
from __future__ import annotations

import cv2
import numpy as np

WORK_WIDTH      = 640    # resolução de trabalho do fluxo óptico
BORDER_MARGIN   = 0.08   # ignora bordas (logos e tarjas de transmissão ficam ali)
BOX_PAD         = 0.15   # folga em volta das caixas dos objetos em movimento (cavalos, boi, vaqueiros)
MAIN_PAD_X      = 0.6    # zona excluída em volta do cavalo seguido (fração da largura da caixa)
MAIN_PAD_Y      = 0.25
MIN_POINTS      = 25     # abaixo disso a estimativa não é confiável
GROUND_MIN_PTS  = 40     # pontos mínimos no chão antes de recorrer ao quadro inteiro
STATIC_SAMPLES  = 40     # frames amostrados para achar sobreposições fixas (tarja, logo)
STATIC_DIFF     = 4      # diferença máxima (níveis de cinza) entre frames seguidos para "não mudou"
STATIC_PAIR_FRAC = 0.85  # fração dos pares em que o pixel não mudou para ser sobreposição fixa
FIXED_CAMERA_FRAC = 0.6  # fração do quadro parada acima da qual a câmera é considerada fixa
HOLD_FRAMES     = 6      # frames seguidos em que repetimos o último movimento quando o fluxo falha

IDENTITY = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


class CameraMotion:
    def __init__(self, frame_w: int, frame_h: int, video_path: str | None = None):
        self.s = min(1.0, WORK_WIDTH / float(frame_w))
        self.w, self.h = int(round(frame_w * self.s)), int(round(frame_h * self.s))
        self.prev = None
        self.last_A, self.hold = None, 0
        self.fixed = False
        self.static = self._static_regions(video_path) if video_path else None

    def _static_regions(self, video_path: str) -> np.ndarray | None:
        """
        Regiões que quase não mudam ao longo do vídeo inteiro (tarjas, placar, logos da transmissão).
        Se ficassem no cálculo, "puxariam" a estimativa para câmera parada mesmo com panorâmica.
        Em câmera realmente fixa o fundo inteiro cai aqui — e a estimativa vira identidade, que é o certo.
        """
        # Pares de frames consecutivos espalhados pelo vídeo: um pixel é "fixo na tela" quando quase
        # não muda na maioria dos pares. Pega logos que trocam de patrocinador de vez em quando
        # (parados em quase todos os pares), o que a variação no vídeo inteiro não pegava.
        cap = cv2.VideoCapture(video_path)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if n < 10:
            cap.release()
            return None
        gray = lambda fr: cv2.cvtColor(cv2.resize(fr, (self.w, self.h), interpolation=cv2.INTER_AREA),
                                       cv2.COLOR_BGR2GRAY).astype(np.int16)
        still, pairs = np.zeros((self.h, self.w), np.float32), 0
        for f in np.linspace(0, n - 2, min(STATIC_SAMPLES, n - 1)).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
            ok1, a = cap.read()
            ok2, b = cap.read()
            if ok1 and ok2:
                still += (np.abs(gray(a) - gray(b)) <= STATIC_DIFF).astype(np.float32)
                pairs += 1
        cap.release()
        if pairs < 5:
            return None
        static = (still / pairs >= STATIC_PAIR_FRAC).astype(np.uint8)
        static = cv2.dilate(static, np.ones((9, 9), np.uint8)).astype(bool)
        # quase o quadro todo parado = câmera fixa de verdade (o cavalo é que se move)
        self.fixed = bool(static.mean() >= FIXED_CAMERA_FRAC)
        return static

    def _mask(self, boxes, ground_top: float | None, main_box=None, main_pad_x: float = MAIN_PAD_X) -> np.ndarray:
        m = np.zeros((self.h, self.w), np.uint8)
        mx, my = int(self.w * BORDER_MARGIN), int(self.h * BORDER_MARGIN)
        top = my if ground_top is None else max(my, int(ground_top * self.s))
        m[top:self.h - my, mx:self.w - mx] = 255
        if self.static is not None:
            m[self.static] = 0
        padded = [(b, BOX_PAD, BOX_PAD) for b in boxes]
        if main_box is not None:
            # boi e cavalo do esteireiro correm colados ao cavalo seguido e nem sempre são detectados:
            # a zona ao redor dele sai inteira do cálculo
            padded.append((main_box, main_pad_x, MAIN_PAD_Y))
        for (x1, y1, x2, y2), px, py in padded:
            bw, bh = (x2 - x1) * px, (y2 - y1) * py
            m[max(0, int((y1 - bh) * self.s)):max(0, int((y2 + bh) * self.s)),
              max(0, int((x1 - bw) * self.s)):max(0, int((x2 + bw) * self.s))] = 0
        return m

    def update(self, frame_bgr, horse_boxes, main_box=None) -> tuple[np.ndarray, int]:
        """
        Retorna (A, n_inliers): A é a matriz 2x3 que leva coordenadas do frame anterior para o
        atual (em pixels do vídeo original). Quando o fluxo óptico falha (poeira, borrão), repete o
        movimento do frame anterior por até HOLD_FRAMES frames — a panorâmica de um operador é
        suave, e assumir "câmera parada" derrubaria a velocidade do cavalo naquele frame.
        """
        if self.fixed:
            return IDENTITY.copy(), 0
        A, n = self._estimate(frame_bgr, horse_boxes, main_box)
        if A is not None:
            self.last_A, self.hold = A, 0
            return A, n
        if self.last_A is not None and self.hold < HOLD_FRAMES:
            self.hold += 1
            return self.last_A.copy(), 0
        # sem estimativa: movimento desconhecido (None) — NÃO é "câmera parada"
        return None, 0

    def reset(self):
        """Corte de cena: o movimento anterior não vale mais."""
        self.last_A, self.hold = None, 0

    def _estimate(self, frame_bgr, horse_boxes, main_box):
        gray = cv2.cvtColor(cv2.resize(frame_bgr, (self.w, self.h), interpolation=cv2.INTER_AREA),
                            cv2.COLOR_BGR2GRAY)
        prev, self.prev = self.prev, gray
        if prev is None:
            return IDENTITY.copy(), 0  # primeiro frame: sem movimento a estimar

        # Tenta primeiro o chão na altura das patas, com a zona larga em volta do cavalo excluída;
        # se sobrarem poucos pontos (grupo cavalo+boi+cavalo ocupando o quadro), vai estreitando
        # a zona e depois libera o quadro inteiro.
        pts = None
        ground_top = None if main_box is None else main_box[3] - 0.15 * (main_box[3] - main_box[1])
        for pad_x in (MAIN_PAD_X, 0.25, 0.1):
            for top in ((ground_top, None) if ground_top is not None else (None,)):
                pts = cv2.goodFeaturesToTrack(prev, 400, 0.01, 6,
                                              mask=self._mask(horse_boxes, top, main_box, pad_x))
                if pts is not None and len(pts) >= GROUND_MIN_PTS:
                    break
            if pts is not None and len(pts) >= GROUND_MIN_PTS:
                break
        if pts is None or len(pts) < MIN_POINTS:
            return None, 0

        nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, gray, pts, None, winSize=(21, 21), maxLevel=3)
        ok = st.ravel() == 1
        if ok.sum() < MIN_POINTS:
            return None, 0

        A, inl = cv2.estimateAffinePartial2D(pts[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=1.5)
        n_in = int(inl.sum()) if inl is not None else 0
        if A is None or n_in < MIN_POINTS:
            return None, n_in

        # volta para a escala do vídeo original (só a translação muda de escala)
        A = A.astype(np.float64)
        A[:, 2] /= self.s
        return A, n_in


def apply(A: np.ndarray, p) -> tuple[float, float]:
    """Aplica a transformação 2x3 a um ponto (x, y)."""
    x, y = float(p[0]), float(p[1])
    return (A[0, 0] * x + A[0, 1] * y + A[0, 2], A[1, 0] * x + A[1, 1] * y + A[1, 2])
