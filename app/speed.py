from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import numpy as np

def _euclid(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return (dx * dx + dy * dy) ** 0.5

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

@dataclass
class SpeedTracker:
    # --- PARÂMETROS BIOMECÂNICOS ---
    max_speed_kmh: float = 88.0 
    smoothing: float = 0.85
    accel_smoothing: float = 0.98
    accel_clip_m_s2: float = 12.0
    movement_threshold_kmh: float = 5.0

    # --- MEMÓRIA ---
    speed_buffer: List[float] = field(default_factory=list) # Novo: Para filtro de mediana
    accel_samples: List[float] = field(default_factory=list)
    confidence_score: float = 1.0 

    last_pos: Optional[Tuple[float, float]] = None
    last_time: Optional[float] = None
    last_speed_kmh: float = 0.0
    last_speed_ms: float = 0.0
    last_accel: float = 0.0

    max_speed: float = 0.0
    max_accel: float = 0.0
    total_distance: float = 0.0

    movement_start_time: Optional[float] = None
    time_of_max_speed: Optional[float] = None
    time_to_max_speed: float = 0.0

    def update(
        self,
        cur_pos: Optional[Tuple[float, float]],
        tempo_s: float,
        pixel_to_meter: Optional[float],
    ) -> Tuple[float, float]:

        this_speed_kmh = self.last_speed_kmh
        this_accel = self.last_accel

        if cur_pos is None or pixel_to_meter is None:
            if self.movement_start_time is not None:
                self.confidence_score = max(0.0, self.confidence_score - 0.005)
            return this_speed_kmh, this_accel

        if self.last_pos is not None and self.last_time is not None:
            dt = tempo_s - self.last_time
            
            if dt > 1e-6:
                dist_px = _euclid(cur_pos, self.last_pos)
                dist_m = dist_px * pixel_to_meter
                
                raw_speed_ms = dist_m / dt
                raw_speed_kmh = raw_speed_ms * 3.6

                # 1. FILTRO DE MEDIANA (Mata o 'Serrote')
                # Analisamos os últimos 5 frames para ignorar erros de 1 frame da IA
                self.speed_buffer.append(raw_speed_kmh)
                if len(self.speed_buffer) > 15: self.speed_buffer.pop(0)
                filtered_raw_speed = float(np.median(self.speed_buffer))

                # 2. FILTRO DE INÉRCIA (Anti-Teleporte)
                if filtered_raw_speed > (self.max_speed_kmh * 1.25):
                    self.confidence_score = max(0.0, self.confidence_score - 0.02)
                    filtered_raw_speed = self.last_speed_kmh
                else:
                    # ✅ SÓ ACUMULA DISTÂNCIA SE O MOVIMENTO COMEÇOU
                    if self.movement_start_time is not None:
                        self.total_distance += dist_m

                # 3. SUAVIZAÇÃO EXPONENCIAL (A 'Massa' do cavalo)
                this_speed_kmh = _clamp(
                    (self.smoothing * self.last_speed_kmh) + ((1.0 - self.smoothing) * filtered_raw_speed),
                    0.0,
                    self.max_speed_kmh
                )
                this_speed_ms = this_speed_kmh / 3.6

                # 4. ACELERAÇÃO REALISTA
                raw_accel = (this_speed_ms - self.last_speed_ms) / dt
                raw_accel = _clamp(raw_accel, -self.accel_clip_m_s2, self.accel_clip_m_s2)
                
                this_accel = (self.accel_smoothing * self.last_accel) + ((1.0 - self.accel_smoothing) * raw_accel)

                if this_accel > 0.5: # Consideramos apenas impulsão real
                    self.accel_samples.append(this_accel)

                # 5. ATUALIZAÇÃO DE RECORDES
                if this_speed_kmh > self.max_speed:
                    self.max_speed = this_speed_kmh
                    self.time_of_max_speed = tempo_s
                    if self.movement_start_time is not None:
                        self.time_to_max_speed = self.time_of_max_speed - self.movement_start_time

                self.max_accel = max(self.max_accel, abs(this_accel))

                # Grava o estado atual
                self.last_speed_kmh = this_speed_kmh
                self.last_speed_ms = this_speed_ms
                self.last_accel = this_accel

        # 🚀 DISPARO DO CRONÔMETRO: Só começa quando o cavalo realmente sai do lugar
        if self.movement_start_time is None and this_speed_kmh > self.movement_threshold_kmh:
            self.movement_start_time = tempo_s

        self.last_pos = cur_pos
        self.last_time = tempo_s

        return this_speed_kmh, this_accel

    def impulse_m_s2(self) -> float:
        if not self.accel_samples:
            return 0.0
        # Percentil 90 é mais estável para evitar erros de leitura pontuais
        return float(np.percentile(self.accel_samples, 90))