"""
README: Comparison Charts
Covers: Bar chart, Column chart, Clustered bar/column chart.
Dependency: matplotlib
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from .trend_charts import _fig_to_base64

def render_bar_chart(df: pd.DataFrame, x_col: str, y_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    # Horizontal bar
    ax.barh(df[x_col].astype(str), df[y_col], color='#10b981')
    ax.set_title(f"Bar Chart: {y_col} by {x_col}", color='white')
    ax.set_xlabel(y_col, color='lightgray')
    ax.set_ylabel(x_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(axis='x', alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_clustered_column_chart(df: pd.DataFrame, x_col: str, y_col_1: str, y_col_2: str = None):
    # Clustered column logic requires two metrics. If only one provided, we duplicate it for demo purposes.
    y1 = y_col_1
    y2 = y_col_2 if y_col_2 and y_col_2 in df.columns else y_col_1
    
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(df))
    width = 0.35
    
    ax.bar(x - width/2, df[y1], width, label=y1, color='#3b82f6')
    if y_col_2:
        ax.bar(x + width/2, df[y2], width, label=y2, color='#f59e0b')
    
    ax.set_title(f"Clustered Column Chart: {y1}" + (f" and {y2}" if y_col_2 else ""), color='white')
    ax.set_xticks(x)
    ax.set_xticklabels(df[x_col].astype(str))
    ax.set_xlabel(x_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.legend(facecolor='#1e293b', edgecolor='none', labelcolor='lightgray')
    ax.grid(axis='y', alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}
