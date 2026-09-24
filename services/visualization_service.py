"""
services/visualization_service.py
---------------------------------
Service handling chart rendering, filtering, pre-aggregation,
and AI-assisted visualization suggestion extraction.
"""
import os
import re
import json
import logging
import pandas as pd
from typing import Tuple, Optional
from flask import current_app

from services.ai_service import get_llm_client


def extract_viz_params_fallback(msg_text: str, columns: list) -> dict:
    """Rule-based extraction of chart type and axis columns from user prompt."""
    msg_lower = msg_text.lower()
    cat = "comparison"
    c_type = "bar"

    if any(kw in msg_lower for kw in ["pie", "donut"]):
        cat = "part_to_whole"
        c_type = "pie" if "pie" in msg_lower else "donut"
    elif any(kw in msg_lower for kw in ["line", "trend", "area"]):
        cat = "trend"
        c_type = "line" if "line" in msg_lower else "area"
    elif any(kw in msg_lower for kw in ["scatter", "relationship", "bubble"]):
        cat = "relationship"
        c_type = "scatter"
    elif any(kw in msg_lower for kw in ["histogram", "distribution", "box"]):
        cat = "distribution"
        c_type = "histogram" if "histogram" in msg_lower else "box"
    elif any(kw in msg_lower for kw in ["waterfall", "funnel"]):
        cat = "change_flow"
        c_type = "waterfall" if "waterfall" in msg_lower else "funnel"

    matched_cols = []
    for col_name in columns:
        if re.search(rf"\b{re.escape(col_name.lower())}\b", msg_lower):
            matched_cols.append(col_name)

    x_col = matched_cols[0] if len(matched_cols) > 0 else (columns[0] if columns else "Category")
    y_col = matched_cols[1] if len(matched_cols) > 1 else (columns[-1] if columns else "Value")

    return {
        "chart_category": cat,
        "chart_type": c_type,
        "x_col": x_col,
        "y_col": y_col
    }


def suggest_viz_params(
    message: str,
    columns: list,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> dict:
    """Uses LLM to extract visualization params, falling back to heuristic parsing."""
    client = get_llm_client(api_key=api_key, provider=provider, model=model, base_url=base_url)
    if not client:
        return extract_viz_params_fallback(message, columns)

    system_prompt = f"""You are an AI data visualization assistant.
The user wants to generate a chart. You must extract the parameters for the chart based on the user's request.
The available columns in the dataset are: {', '.join(columns)}

You must return a JSON object with EXACTLY these keys:
- "chart_category": one of ["trend", "comparison", "part_to_whole", "relationship", "distribution", "single_metric", "geo", "tabular", "change_flow", "scheduling", "interactivity"]
- "chart_type": a specific type for the category (e.g. "bar", "line", "pie", "scatter", "histogram", "clustered_column", "waterfall", "donut")
- "x_col": The column name for the category or X-axis (for pie/donut charts, this is the label). Must be one of the available columns.
- "y_col": The column name for the value or Y-axis (for pie/donut charts, this is the value to sum). Must be one of the available columns.
- "y_col_2": (Optional) The secondary Y axis.
- "group_col": (Optional) The column name to group/color by.

Example for 'show me a bar chart of msrp by year':
{{"chart_category": "comparison", "chart_type": "bar", "x_col": "Model_Year", "y_col": "Base_MSRP"}}

Return ONLY valid JSON. No markdown formatting or extra text."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]

        return json.loads(content)
    except Exception as e:
        logging.warning("LLM viz_chat failed (%s), using rule-based fallback.", str(e))
        return extract_viz_params_fallback(message, columns)


def render_dataset_chart(
    df: pd.DataFrame,
    chart_category: str,
    chart_type: str,
    x_col: Optional[str] = None,
    y_col: Optional[str] = None,
    y_col_2: Optional[str] = None,
    group_col: Optional[str] = None,
    filters: Optional[dict] = None
) -> Tuple[Optional[dict], Optional[Tuple[str, int]]]:
    """
    Applies column inference, numeric conversions, filtering, aggregation/sampling,
    and dispatches to the correct PowerBI visuals module.
    """
    filters = filters or {}

    # Auto-resolve x_col and y_col if missing or invalid
    if not x_col or x_col not in df.columns:
        cat_cols = df.select_dtypes(include=['object', 'category', 'string']).columns.tolist()
        x_col = cat_cols[0] if cat_cols else df.columns[0]
    if not y_col or y_col not in df.columns:
        num_cols = df.select_dtypes(include=['number']).columns.tolist()
        y_col = num_cols[0] if num_cols else df.columns[-1]

    # Ensure y_col is numeric for plotting
    if y_col and y_col in df.columns:
        if df[y_col].dtype == object or str(df[y_col].dtype) in ['category', 'string']:
            cleaned_num = df[y_col].astype(str).str.replace(r'[\$,%\s,]', '', regex=True)
            num_series = pd.to_numeric(cleaned_num, errors='coerce')
            if num_series.notna().sum() > 0:
                df.loc[:, y_col] = num_series.fillna(0)
            else:
                df.loc[:, '_freq_metric'] = 1
                y_col = '_freq_metric'
        else:
            df.loc[:, y_col] = pd.to_numeric(df[y_col], errors='coerce').fillna(0)

    if y_col_2 and y_col_2 in df.columns:
        cleaned_num2 = df[y_col_2].astype(str).str.replace(r'[\$,%\s,]', '', regex=True)
        df.loc[:, y_col_2] = pd.to_numeric(cleaned_num2, errors='coerce').fillna(0)

    # Apply filters
    for col, f_val in filters.items():
        if col in df.columns:
            if isinstance(f_val, dict):
                for op, v in f_val.items():
                    if op == '>': df = df[df[col] > v]
                    elif op == '<': df = df[df[col] < v]
                    elif op == '>=': df = df[df[col] >= v]
                    elif op == '<=': df = df[df[col] <= v]
                    elif op == '==': df = df[df[col] == v]
            else:
                df = df[df[col] == f_val]

    if df.empty:
        return None, ("Filtered dataset is empty.", 400)

    # DoS Protection & Memory Safety
    max_plot_points = 1000
    if chart_category in ['comparison', 'part_to_whole']:
        if x_col in df.columns and y_col in df.columns:
            try:
                agg_cols = [y_col]
                if y_col_2 and y_col_2 in df.columns and y_col_2 != y_col:
                    agg_cols.append(y_col_2)
                if df[x_col].nunique() > 30 or len(df) > 100:
                    grouped_df = df.groupby(x_col, as_index=False)[agg_cols].mean().head(30)
                    if not grouped_df.empty:
                        df = grouped_df
            except Exception as agg_ex:
                logging.warning("Chart pre-aggregation fallback: %s", agg_ex)
    elif len(df) > max_plot_points:
        step = len(df) // max_plot_points
        df = df.iloc[::step].copy()

    try:
        result = None
        if chart_category == 'trend':
            import powerbi_visuals.trend_charts as tc
            if chart_type == 'line': result = tc.render_line_chart(df, x_col, y_col)
            elif chart_type == 'area': result = tc.render_area_chart(df, x_col, y_col)
            elif chart_type == 'column': result = tc.render_column_chart(df, x_col, y_col)
            elif chart_type == 'combo': result = tc.render_combo_chart(df, x_col, y_col, y_col_2)

        elif chart_category == 'comparison':
            import powerbi_visuals.comparison_charts as cc
            if chart_type == 'bar': result = cc.render_bar_chart(df, x_col, y_col)
            elif chart_type == 'clustered_column': result = cc.render_clustered_column_chart(df, x_col, y_col, y_col_2)

        elif chart_category == 'part_to_whole':
            import powerbi_visuals.part_to_whole_charts as ptc
            if chart_type == 'pie': result = ptc.render_pie_chart(df, x_col, y_col)
            elif chart_type == 'donut': result = ptc.render_donut_chart(df, x_col, y_col)
            elif chart_type == 'stacked_column': result = ptc.render_stacked_column_chart(df, x_col, group_col, y_col)
            elif chart_type == '100_stacked_column': result = ptc.render_100_stacked_column_chart(df, x_col, group_col, y_col)
            elif chart_type == 'treemap': result = ptc.render_treemap(df, x_col, y_col)
            elif chart_type == 'sunburst': result = ptc.render_sunburst_chart(df, [x_col, group_col] if group_col else [x_col], y_col)

        elif chart_category == 'change_flow':
            import powerbi_visuals.change_flow_charts as cfc
            if chart_type == 'waterfall': result = cfc.render_waterfall_chart(df, x_col, y_col)
            elif chart_type == 'funnel': result = cfc.render_funnel_chart(df, x_col, y_col)
            elif chart_type == 'sankey': result = cfc.render_sankey_diagram(df, x_col, group_col, y_col)
            elif chart_type == 'ribbon': result = cfc.render_ribbon_chart(df, x_col, group_col, y_col)

        elif chart_category == 'relationship':
            import powerbi_visuals.relationship_charts as rc
            if chart_type == 'scatter': result = rc.render_scatter_chart(df, x_col, y_col)
            elif chart_type == 'bubble': result = rc.render_bubble_chart(df, x_col, y_col, y_col_2)
            elif chart_type == 'key_influencers': result = rc.render_key_influencers(df, y_col)

        elif chart_category == 'distribution':
            import powerbi_visuals.distribution_charts as dc
            if chart_type == 'histogram': result = dc.render_histogram(df, x_col)
            elif chart_type == 'box': result = dc.render_box_and_whisker(df, y_col, x_col)

        elif chart_category == 'single_metric':
            import powerbi_visuals.single_metric_visuals as smv
            if chart_type == 'card': result = smv.render_card(df, y_col)
            elif chart_type == 'multi_row_card': result = smv.render_multi_row_card(df, x_col, y_col)
            elif chart_type == 'gauge': result = smv.render_gauge_chart(df, y_col)

        elif chart_category == 'geo':
            import powerbi_visuals.geo_charts as gc
            if chart_type == 'bubble_map': result = gc.render_bubble_map(df, x_col, y_col, y_col_2, group_col)
            elif chart_type == 'choropleth': result = gc.render_choropleth_map(df, x_col, y_col)

        elif chart_category == 'tabular':
            import powerbi_visuals.tabular_visuals as tv
            if chart_type == 'table': result = tv.render_table(df)
            elif chart_type == 'matrix': result = tv.render_matrix(df, x_col, group_col, y_col)

        elif chart_category == 'scheduling':
            import powerbi_visuals.time_based_scheduling as tbs
            if chart_type == 'gantt': result = tbs.render_gantt_chart(df, group_col, x_col, y_col)
            elif chart_type == 'calendar_heatmap': result = tbs.render_calendar_heatmap(df, x_col, y_col)

        elif chart_category == 'interactivity':
            import powerbi_visuals.interactivity as ic
            if chart_type == 'smart_narrative': result = ic.render_smart_narrative(df, x_col, y_col)

        if not result:
            return None, ("Unsupported chart type or category", 400)

        return result, None

    except Exception as e:
        logging.error("Error generating chart: %s", str(e))
        return None, (f"Error generating chart: {str(e)}", 500)
