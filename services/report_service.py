"""
services/report_service.py
--------------------------
PDF report compilation service using ReportLab, Lora fonts, and Matplotlib.
"""
import os
import logging
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import current_app

from utils.session_manager import save_session

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    reportlab_installed = True
except ImportError:
    reportlab_installed = False


def build_pdf_report(session_data: dict, app_config: dict) -> tuple:
    """
    Builds the PDF report from session data and cleaned dataset.
    Returns (result_dict, None) or (None, (error_msg, status_code)).
    """
    if not reportlab_installed:
        return None, ("ReportLab library is not properly installed or imported.", 500)

    if not session_data.get("cleaned_filename"):
        return None, ("No cleaned file exists for this session. Please apply cleaning rules and process the dataset first.", 400)

    session_id = session_data["session_id"]
    output_folder = app_config['OUTPUT_FOLDER']
    cleaned_path = os.path.join(output_folder, session_data["cleaned_filename"])
    if not os.path.exists(cleaned_path):
        return None, ("Cleaned data file not found", 404)

    try:
        df = pd.read_excel(cleaned_path)

        from powerbi_visuals.trend_charts import PLOT_LOCK

        chart_images = []
        target_charts = session_data.get("pinned_charts") if session_data.get("pinned_charts") else session_data.get("charts", [])
        for idx, chart in enumerate(target_charts):
            chart_type = chart.get("chart_type") or chart.get("type", "bar")
            title = chart.get("title") or f"{chart.get('y_axis', '')} by {chart.get('x_axis', '')}"
            x = chart.get("x_axis") or chart.get("x_col")
            y = chart.get("y_axis") or chart.get("y_col")

            if x not in df.columns:
                continue

            with PLOT_LOCK:
                try:
                    plt.figure(figsize=(6, 3.5))
                    active_font = 'Lora' if 'Lora' in pdfmetrics.getRegisteredFontNames() else 'DejaVu Sans'
                    plt.title(title, fontname=active_font, fontsize=12, fontweight='bold', pad=10)

                    if chart_type == 'histogram':
                        df[x].dropna().value_counts().head(10).plot(kind='bar', color='#6366f1')
                        plt.ylabel('Frequency')
                    elif chart_type == 'pie':
                        df[x].dropna().value_counts().head(6).plot(kind='pie', autopct='%1.1f%%', colors=['#6366f1', '#a855f7', '#10b981', '#f59e0b', '#3b82f6'])
                        plt.ylabel('')
                    elif chart_type == 'scatter' and y in df.columns:
                        df.dropna(subset=[x, y]).plot(kind='scatter', x=x, y=y, color='#a855f7')
                    elif chart_type == 'line' and y in df.columns:
                        df.dropna(subset=[x, y]).sort_values(by=x).plot(kind='line', x=x, y=y, color='#6366f1')
                    elif chart_type == 'bar' and y in df.columns:
                        df.groupby(x)[y].mean().head(12).plot(kind='bar', color='#10b981')
                        plt.ylabel(f'Avg {y}')
                    else:
                        df[x].dropna().value_counts().head(10).plot(kind='bar', color='#6366f1')

                    plt.xticks(rotation=45, ha='right', fontsize=8)
                    plt.tight_layout()

                    img_filename = f"{session_id}_chart_{idx}.png"
                    img_path = os.path.join(output_folder, img_filename)
                    plt.savefig(img_path, dpi=200, bbox_inches='tight')
                    chart_images.append((img_path, chart.get("description", "")))
                except Exception as plot_ex:
                    logging.warning("Failed to generate plot for PDF %s: %s", title, str(plot_ex))
                finally:
                    plt.close()

        pdf_filename = f"report_{session_id}.pdf"
        pdf_path = os.path.join(output_folder, pdf_filename)

        font_regular = 'Lora' if 'Lora' in pdfmetrics.getRegisteredFontNames() else 'Helvetica'
        font_bold = 'Lora-Bold' if 'Lora-Bold' in pdfmetrics.getRegisteredFontNames() else 'Helvetica-Bold'

        doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'DocTitle', parent=styles['Normal'],
            fontName=font_bold, fontSize=22, leading=26,
            textColor=colors.HexColor('#0f172a'), spaceAfter=6
        )
        subtitle_style = ParagraphStyle(
            'DocSubtitle', parent=styles['Normal'],
            fontName=font_regular, fontSize=11, leading=15,
            textColor=colors.HexColor('#64748b'), spaceAfter=20
        )
        h1_style = ParagraphStyle(
            'SectionH1', parent=styles['Normal'],
            fontName=font_bold, fontSize=14, leading=18,
            textColor=colors.HexColor('#4f46e5'), spaceBefore=12, spaceAfter=8,
            keepWithNext=True
        )
        body_style = ParagraphStyle(
            'DocBody', parent=styles['Normal'],
            fontName=font_regular, fontSize=9.5, leading=13.5,
            textColor=colors.HexColor('#334155'), spaceAfter=6
        )
        table_header_style = ParagraphStyle(
            'TableHeader', parent=styles['Normal'],
            fontName=font_bold, fontSize=8.5, leading=10.5,
            textColor=colors.HexColor('#ffffff')
        )
        table_cell_style = ParagraphStyle(
            'TableCell', parent=styles['Normal'],
            fontName=font_regular, fontSize=8.5, leading=10.5,
            textColor=colors.HexColor('#334155')
        )

        story = []
        story.append(Paragraph("AI-Powered Data Cleansing & Diagnostics Report", title_style))
        story.append(Paragraph(f"Goal: {session_data.get('goal', '')}", subtitle_style))
        story.append(Spacer(1, 10))

        story.append(Paragraph("1. Executive Summary", h1_style))
        audit_log = session_data.get("audit_log", [])
        quality_metrics = session_data.get("quality_metrics", {})

        nulls_resolved = quality_metrics.get("nulls_resolved", 0)
        dups_removed = quality_metrics.get("duplicate_rows_removed", 0)
        cols_dropped = len(quality_metrics.get("columns_dropped", []))
        ops_count = len(audit_log)

        summary_text = (
            f"This diagnostics report details the cleaning operations executed on dataset "
            f"<b>{session_data.get('original_filename', '')}</b> to achieve goal: <i>\"{session_data.get('goal', 'Data Cleaning')}\"</i>. "
            f"A total of <b>{ops_count}</b> structured cleaning operations were executed. "
            f"Key quality outcomes: <b>{nulls_resolved}</b> missing values resolved, "
            f"<b>{dups_removed}</b> duplicate rows eliminated, and <b>{cols_dropped}</b> redundant columns dropped."
        )
        story.append(Paragraph(summary_text, body_style))
        story.append(Spacer(1, 8))

        initial_rows = quality_metrics.get("initial_rows", session_data.get("row_count", len(df)))
        final_rows = quality_metrics.get("final_rows", len(df))
        initial_cols = quality_metrics.get("initial_cols", len(session_data.get("columns", [])))
        final_cols = quality_metrics.get("final_cols", len(df.columns))
        null_before = quality_metrics.get("null_before", sum(df.isnull().sum()))
        null_after = quality_metrics.get("null_after", sum(df.isnull().sum()))
        dup_before = quality_metrics.get("duplicate_rows_before", 0)
        dup_after = quality_metrics.get("duplicate_rows_after", int(df.duplicated().sum()))

        metric_data = [
            [Paragraph("Quality Dimension", table_header_style), Paragraph("Initial Raw Dataset", table_header_style), Paragraph("Cleaned Final Dataset", table_header_style), Paragraph("Impact / Delta", table_header_style)],
            [Paragraph("Total Rows", table_cell_style), Paragraph(str(initial_rows), table_cell_style), Paragraph(str(final_rows), table_cell_style), Paragraph(f"{final_rows - initial_rows:+d} rows", table_cell_style)],
            [Paragraph("Total Features / Columns", table_cell_style), Paragraph(str(initial_cols), table_cell_style), Paragraph(str(final_cols), table_cell_style), Paragraph(f"{final_cols - initial_cols:+d} cols", table_cell_style)],
            [Paragraph("Missing / Null Values", table_cell_style), Paragraph(str(null_before), table_cell_style), Paragraph(str(null_after), table_cell_style), Paragraph(f"-{nulls_resolved} nulls", table_cell_style)],
            [Paragraph("Duplicate Rows", table_cell_style), Paragraph(str(dup_before), table_cell_style), Paragraph(str(dup_after), table_cell_style), Paragraph(f"-{dups_removed} dups", table_cell_style)],
        ]
        metric_table = Table(metric_data, colWidths=[150, 125, 125, 120])
        metric_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4f46e5')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(metric_table)
        story.append(Spacer(1, 12))

        dtype_changes = quality_metrics.get("dtype_changes", {})
        if dtype_changes:
            story.append(Paragraph("<b>Datatype Conversions:</b>", body_style))
            dt_data = [
                [Paragraph("Column", table_header_style), Paragraph("Original Dtype", table_header_style), Paragraph("Cleaned Dtype", table_header_style)]
            ]
            for c_name, dt_info in dtype_changes.items():
                dt_data.append([
                    Paragraph(str(c_name), table_cell_style),
                    Paragraph(str(dt_info.get("before")), table_cell_style),
                    Paragraph(str(dt_info.get("after")), table_cell_style)
                ])
            dt_table = Table(dt_data, colWidths=[180, 170, 170])
            dt_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('PADDING', (0,0), (-1,-1), 4),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ]))
            story.append(dt_table)
            story.append(Spacer(1, 10))

        story.append(Paragraph("2. Applied Operations Audit Log", h1_style))
        if audit_log:
            schema_data = [
                [Paragraph("Target Column", table_header_style), Paragraph("Operation", table_header_style), Paragraph("Status", table_header_style), Paragraph("Audit Record / Impact", table_header_style)]
            ]
            for entry in audit_log:
                col_name = entry.get("column") or "Dataset-Wide"
                op_name = str(entry.get("operation", "keep_column")).replace("_", " ").title()
                status_lbl = str(entry.get("status", "success")).upper()
                msg = entry.get("message") or entry.get("error") or ""
                schema_data.append([
                    Paragraph(str(col_name), table_cell_style),
                    Paragraph(op_name, table_cell_style),
                    Paragraph(status_lbl, table_cell_style),
                    Paragraph(str(msg), table_cell_style)
                ])
            schema_table = Table(schema_data, colWidths=[110, 110, 60, 240])
        else:
            schema_data = [
                [Paragraph("Column", table_header_style), Paragraph("Action", table_header_style), Paragraph("Explanation & Custom Rules", table_header_style)]
            ]
            for col, act in session_data.get("column_actions", {}).items():
                action_lbl = act.get("action", "keep").upper()
                reason_txt = act.get("reason", "")
                trans_txt = act.get("transformation")
                if trans_txt:
                    reason_txt += f" (Transformation: {trans_txt})"
                schema_data.append([
                    Paragraph(col, table_cell_style),
                    Paragraph(action_lbl, table_cell_style),
                    Paragraph(reason_txt, table_cell_style)
                ])
            schema_table = Table(schema_data, colWidths=[120, 80, 320])

        schema_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(schema_table)
        story.append(PageBreak())

        story.append(Paragraph("3. Cleaned Dataset Descriptive Statistics", h1_style))
        desc_df = df.describe().round(2).reset_index()
        desc_cols = list(desc_df.columns)
        if len(desc_cols) > 6:
            desc_df = desc_df.iloc[:, :6]
            desc_cols = list(desc_df.columns)

        desc_header = [Paragraph(c, table_header_style) for c in desc_cols]
        desc_table_data = [desc_header]
        for _, row in desc_df.iterrows():
            row_cells = []
            for c in desc_cols:
                row_cells.append(Paragraph(str(row[c]), table_cell_style))
            desc_table_data.append(row_cells)

        col_w = 520 / len(desc_cols)
        desc_table = Table(desc_table_data, colWidths=[col_w] * len(desc_cols))
        desc_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#475569')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(desc_table)
        story.append(Spacer(1, 15))

        story.append(Paragraph("4. Diagnostic Visualizations", h1_style))
        for img_path, desc in chart_images:
            story.append(Paragraph(desc, body_style))
            story.append(Spacer(1, 4))
            story.append(Image(img_path, width=380, height=220))
            story.append(Spacer(1, 12))

        doc.build(story)

        session_data["pdf_filename"] = pdf_filename
        pdf_chat_msg = (
            f"I've compiled a professional PDF data diagnostics report using the **Lora** font. "
            f"You can download it directly here: <br><a href='/api/sessions/{session_id}/download_pdf' "
            f"class='btn btn-emerald' style='margin-top:0.5rem; padding: 0.4rem 1rem; font-size: 0.8rem;'>"
            f"<i class='fa-solid fa-file-pdf'></i> Download PDF Report</a>"
        )
        session_data["chat_history"].append({"role": "assistant", "content": pdf_chat_msg})
        save_session(session_data)

        return {
            "success": True,
            "pdf_url": f"/api/sessions/{session_id}/download_pdf",
            "chat_history": session_data["chat_history"]
        }, None

    except Exception as e:
        logging.error("Error compiling PDF: %s", str(e))
        return None, (f"Failed to generate PDF: {str(e)}", 500)
