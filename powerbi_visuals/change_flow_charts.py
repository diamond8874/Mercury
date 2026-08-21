"""
README: Change & Flow Charts
Covers: Waterfall chart, Funnel chart, Sankey diagram, Ribbon chart, Decomposition tree.
Dependencies: waterfallcharts, plotly, matplotlib
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import waterfall_chart
from .trend_charts import _fig_to_base64

def render_waterfall_chart(df: pd.DataFrame, label_col: str, value_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    
    # We will compute the waterfall using waterfall_chart package
    a = df[label_col].astype(str).tolist()
    b = df[value_col].tolist()
    
    # waterfall_chart creates a new figure, so we plot it directly.
    # To capture it, we'll use plot() which returns a matplotlib figure.
    wf_fig = waterfall_chart.plot(a, b, Title=f"Waterfall Chart: {value_col}",
                                   x_lab=label_col, y_lab=value_col,
                                   blue_color='#3b82f6', green_color='#10b981', red_color='#ef4444')
    
    # Get current figure since plot() draws on gcf
    fig = plt.gcf()
    fig.patch.set_alpha(0.0)
    for ax in fig.axes:
        ax.patch.set_alpha(0.0)
        ax.tick_params(colors='lightgray')
        ax.xaxis.label.set_color('lightgray')
        ax.yaxis.label.set_color('lightgray')
        ax.title.set_color('white')
        
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_funnel_chart(df: pd.DataFrame, stage_col: str, value_col: str):
    # Simulate a funnel chart using horizontal bars centered
    fig, ax = plt.subplots(figsize=(8, 5))
    data = df.groupby(stage_col)[value_col].sum().sort_values(ascending=False)
    
    y = np.arange(len(data))[::-1]
    max_val = data.max()
    lefts = (max_val - data) / 2
    
    ax.barh(y, data, left=lefts, color='#0ea5e9', height=0.6)
    
    ax.set_yticks(y)
    ax.set_yticklabels(data.index)
    ax.set_title(f"Funnel Chart: {value_col} by {stage_col}", color='white')
    ax.tick_params(colors='lightgray')
    
    # Hide spines
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    
    # Add data labels
    for i, v in enumerate(data):
        ax.text(max_val/2, y[i], str(v), color='white', ha='center', va='center')
        
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_sankey_diagram(df: pd.DataFrame, source_col: str, target_col: str, value_col: str):
    # Sankey uses Plotly
    nodes = list(pd.concat([df[source_col], df[target_col]]).unique())
    node_indices = {node: i for i, node in enumerate(nodes)}
    
    source_indices = df[source_col].map(node_indices)
    target_indices = df[target_col].map(node_indices)
    
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=nodes,
            color="#3b82f6"
        ),
        link=dict(
            source=source_indices,
            target=target_indices,
            value=df[value_col]
        )
    )])
    fig.update_layout(title_text=f"Sankey Diagram: {source_col} to {target_col}", font_color="lightgray",
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return {"type": "plotly", "data": json.loads(fig.to_json())}

def render_ribbon_chart(df: pd.DataFrame, x_col: str, category_col: str, value_col: str):
    # Ribbon chart is complex in matplotlib, we will simulate using Plotly filled area traces
    fig = go.Figure()
    categories = df[category_col].unique()
    
    for cat in categories:
        cat_data = df[df[category_col] == cat].sort_values(by=x_col)
        fig.add_trace(go.Scatter(
            x=cat_data[x_col], y=cat_data[value_col],
            mode='lines',
            line=dict(width=0.5),
            stackgroup='one',
            name=str(cat)
        ))
        
    fig.update_layout(title=f"Ribbon Chart: {value_col} by {x_col} and {category_col}", 
                      font_color="lightgray", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return {"type": "plotly", "data": json.loads(fig.to_json())}

# Decomposition Tree:
# Note: There is no direct open-source equivalent for Power BI's Decomposition tree 
# that dynamically calculates variance/drill-down on the fly in Python. 
# A common workaround is using Plotly Sunburst or Treemap (already provided in part_to_whole) 
# or custom Dash components.
