import os
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch

def generate_pdf_report(job_id: str, base_output: str = "output") -> str:
    # Agora usamos o caminho absoluto passado pelo api.py
    out_dir = os.path.abspath(os.path.join(base_output, str(job_id)))
    
    summary_path = os.path.join(out_dir, "summary.csv")
    image_path = os.path.join(out_dir, "performance_report.png")
    pdf_path = os.path.join(out_dir, "performance_report.pdf")

    # O restante do código de verificação e geração do PDF permanece igual...
    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"summary.csv não encontrado em: {summary_path}")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"performance_report.png não encontrado em: {image_path}")

    summary = pd.read_csv(summary_path)

    # Coleta de métricas
    max_speed = float(summary["max_speed_kmh"].iloc[0])
    avg_speed = float(summary["avg_speed_kmh"].iloc[0])
    max_accel = float(summary["max_accel_m_s2"].iloc[0])
    time_to_max = float(summary["time_to_max_speed_s"].iloc[0])
    distance = float(summary["total_distance_m"].iloc[0])
    efficiency = float(summary["efficiency_percent"].iloc[0])
    impulse = float(summary["impulse_m_s2"].iloc[0]) if "impulse_m_s2" in summary.columns else max_accel
    
    doc = SimpleDocTemplate(pdf_path)
    elements = []
    styles = getSampleStyleSheet()

    # Título do Relatório
    elements.append(Paragraph("Relatório de Performance - Análise Equina", styles["Heading1"]))
    elements.append(Spacer(1, 0.2 * inch))

    # -------------------------
    # TABELA DE MÉTRICAS
    # -------------------------
    data = [
        ["Velocidade Máxima (km/h)", f"{round(max_speed, 2)}"],
        ["Velocidade Média (km/h)", f"{round(avg_speed, 2)}"],
        ["Aceleração Máxima (m/s²)", f"{round(max_accel, 2)}"],
        ["Impulsão (m/s²)", f"{round(impulse, 2)}"],
        ["Tempo até Vel. Máx (s)", f"{round(time_to_max, 2)}"],
        ["Distância Percorrida (m)", f"{round(distance, 2)}"],
        ["Eficiência (%)", f"{round(efficiency, 2)}"],
    ]

    table = Table(data, colWidths=[3.2 * inch, 1.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    elements.append(table)
    
    # Espaçamento maior antes do gráfico para preencher a página
    elements.append(Spacer(1, 0.5 * inch))

    # -------------------------
    # GRÁFICO DE PERFORMANCE
    # -------------------------
    img = Image(image_path, width=6.2 * inch, height=3.5 * inch)
    elements.append(img)

    doc.build(elements)
    return pdf_path