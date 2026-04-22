import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Obrigatório para servidores sem interface gráfica
import matplotlib.pyplot as plt

# ============================================================
# 📊 GERAÇÃO DE GRÁFICOS DE ALTA PERFORMANCE
# ============================================================
def generate_report(job_id: str, base_output: str = "output") -> str:
    out_dir = os.path.abspath(os.path.join(base_output, str(job_id)))
    
    csv_metrics = os.path.join(out_dir, "metrics.csv")
    csv_summary = os.path.join(out_dir, "summary.csv")
    out_path = os.path.join(out_dir, "performance_report.png")

    # Verificação de segurança de arquivos
    if not os.path.exists(csv_metrics) or not os.path.exists(csv_summary):
        raise FileNotFoundError(f"Arquivos CSV não encontrados no diretório do job: {job_id}")

    # Leitura dos dados
    df = pd.read_csv(csv_metrics)
    summary = pd.read_csv(csv_summary)

    # ✅ PREVENÇÃO DE CRASH: Verifica se os CSVs não estão vazios
    if df.empty or summary.empty:
        # Cria uma imagem em branco com aviso se não houver dados
        fig, ax = plt.subplots(figsize=(14, 10))
        ax.text(0.5, 0.5, "Dados insuficientes para gerar o gráfico.\nNenhum cavalo detectado com clareza.", 
                ha='center', va='center', fontsize=20, color='gray')
        ax.axis('off')
        plt.savefig(out_path, dpi=200, bbox_inches='tight')
        plt.close()
        return out_path

    # Limpeza e conversão segura de tipos
    df["tempo_s"] = pd.to_numeric(df.get("tempo_s"), errors="coerce")
    df["speed_kmh"] = pd.to_numeric(df.get("speed_kmh"), errors="coerce")
    df["accel_m_s2"] = pd.to_numeric(df.get("accel_m_s2"), errors="coerce")
    df = df.dropna(subset=["tempo_s", "speed_kmh"]).sort_values("tempo_s")

    if df.empty:
        raise ValueError("Dados corrompidos ou insuficientes após limpeza.")

    # Suavização (Rolling Mean)
    df["speed_smooth"] = df["speed_kmh"].rolling(window=7, min_periods=1).mean()
    df["accel_smooth"] = df["accel_m_s2"].rolling(window=7, min_periods=1).mean()

    # Extração segura de métricas (evita IndexError com .get ou fallback)
    def safe_extract(col_name, default=0.0):
        return float(summary[col_name].iloc[0]) if col_name in summary.columns and not pd.isna(summary[col_name].iloc[0]) else default

    max_speed = safe_extract("max_speed_kmh")
    avg_speed = safe_extract("avg_speed_kmh")
    max_accel = safe_extract("max_accel_m_s2")
    time_to_max = safe_extract("time_to_max_speed_s")
    distance = safe_extract("total_distance_m")
    efficiency = safe_extract("efficiency_percent")
    
    # Corrige anomalia matemática onde média fica maior que máxima
    if avg_speed > max_speed:
        avg_speed = min(df["speed_kmh"].mean(), max_speed)

    efficiency = min(efficiency, 100.0)

    # Impulsão (Lê do summary ou calcula na hora como fallback)
    impulse = safe_extract("impulse_m_s2")
    if impulse == 0.0 and len(df) > 0:
        impulse = float(df["accel_m_s2"].quantile(0.95))

    # ==========================================
    # 🎨 ESTILIZAÇÃO PREMIUM MATPLOTLIB
    # ==========================================
    plt.style.use('seaborn-v0_8-whitegrid') # Estilo mais moderno e limpo
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), facecolor='#FAFAFA')
    fig.patch.set_facecolor('#FAFAFA')

    def despine(ax):
        """Remove bordas superiores e direitas para visual mais limpo"""
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#DDDDDD')
        ax.spines['bottom'].set_color('#DDDDDD')
        ax.set_facecolor('#FAFAFA')
        ax.grid(True, linestyle='--', alpha=0.5, color='#E0E0E0')

    # --- GRÁFICO 1: VELOCIDADE ---
    ax1.plot(df["tempo_s"], df["speed_smooth"], color='#1E3A8A', linewidth=3, label='Velocidade (km/h)')
    ax1.fill_between(df["tempo_s"], df["speed_smooth"], color='#3B82F6', alpha=0.15)
    ax1.set_title("Relatório de Biomecânica — Puxa.ai", fontsize=18, fontweight='bold', color='#111827', pad=20)
    ax1.set_ylabel("Velocidade (km/h)", fontsize=12, fontweight='bold', color='#4B5563')
    
    if max_speed > 0:
        ax1.axhline(max_speed, color='#EF4444', linestyle="--", linewidth=1.5, alpha=0.8, label=f"Máx: {max_speed:.1f} km/h")
    
    ax1.legend(loc='upper right', frameon=True, facecolor='white', edgecolor='#E5E7EB')
    despine(ax1)

    # --- GRÁFICO 2: ACELERAÇÃO ---
    ax2.plot(df["tempo_s"], df["accel_smooth"], color='#059669', linewidth=2.5, label='Força G / Aceleração')
    ax2.set_xlabel("Tempo de Prova (segundos)", fontsize=12, fontweight='bold', color='#4B5563')
    ax2.set_ylabel("Aceleração (m/s²)", fontsize=12, fontweight='bold', color='#4B5563')
    ax2.axhline(0, color='#9CA3AF', linewidth=1.5, linestyle='-') # Linha do Zero
    ax2.legend(loc='upper right', frameon=True, facecolor='white', edgecolor='#E5E7EB')
    despine(ax2)

    # --- RODAPÉ DE MÉTRICAS ---
    info_text = (
        f"VEL. MÁX: {max_speed:.1f} km/h    |    "
        f"VEL. MÉDIA: {avg_speed:.1f} km/h    |    "
        f"ARRANCADA: {max_accel:.2f} m/s²    |    "
        f"IMPULSÃO: {impulse:.2f} m/s²\n"
        f"DISTÂNCIA: {distance:.1f}m    |    "
        f"TEMPO ATÉ MÁX: {time_to_max:.2f}s    |    "
        f"EFICIÊNCIA: {efficiency:.1f}%"
    )
    
    plt.figtext(0.5, 0.03, info_text, ha="center", fontsize=11, fontweight='bold', color='#374151',
                bbox={"boxstyle": "round,pad=0.8", "facecolor": "#FFFFFF", "edgecolor": "#D1D5DB", "linewidth": 1.5})

    plt.tight_layout(rect=[0, 0.08, 1, 0.96])
    
    plt.savefig(out_path, dpi=200, bbox_inches='tight', facecolor='#FAFAFA')
    plt.close()

    return out_path