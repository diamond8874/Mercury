"""
README: Trend Charts
Covers: Line chart, Area chart, Column/Bar chart (clustered, stacked, 100% stacked), Line and column combo chart.
Dependency: matplotlib
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import io
import base64

import threading
PLOT_LOCK = threading.RLock()

def _fig_to_base64(fig):
    """Helper to convert matplotlib figure to high-quality base64 image string with thread safety."""
    with PLOT_LOCK:
        try:
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=200, bbox_inches='tight', transparent=True)
            buf.seek(0)
            data = base64.b64encode(buf.read()).decode('utf-8')
            return data
        finally:
            plt.close(fig)

def render_line_chart(df: pd.DataFrame, x_col: str, y_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    if pd.api.types.is_numeric_dtype(df[x_col]) or pd.api.types.is_datetime64_any_dtype(df[x_col]):
        data = df.sort_values(by=x_col)
    else:
        data = df
    ax.plot(data[x_col], data[y_col], marker='o', linestyle='-', color='#0ea5e9')
    ax.set_title(f"{y_col} by {x_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel(y_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(True, alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_area_chart(df: pd.DataFrame, x_col: str, y_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    if pd.api.types.is_numeric_dtype(df[x_col]) or pd.api.types.is_datetime64_any_dtype(df[x_col]):
        data = df.sort_values(by=x_col)
    else:
        data = df
    ax.fill_between(data[x_col], data[y_col], color='#0ea5e9', alpha=0.5)
    ax.plot(data[x_col], data[y_col], color='#0ea5e9')
    ax.set_title(f"Area Chart: {y_col} by {x_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel(y_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(True, alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_column_chart(df: pd.DataFrame, x_col: str, y_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(df[x_col], df[y_col], color='#0ea5e9')
    ax.set_title(f"Column Chart: {y_col} by {x_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel(y_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(axis='y', alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_combo_chart(df: pd.DataFrame, x_col: str, y_col_bar: str, y_col_line: str = None):
    # If no secondary y_col, we just plot the same column as a line to demonstrate
    y_line = y_col_line if y_col_line and y_col_line in df.columns else y_col_bar
    fig, ax1 = plt.subplots(figsize=(8, 4))
    ax1.bar(df[x_col], df[y_col_bar], color='#3b82f6', alpha=0.7)
    ax1.set_xlabel(x_col, color='lightgray')
    ax1.set_ylabel(y_col_bar, color='lightgray')
    ax1.tick_params(axis='y', colors='lightgray')
    ax1.tick_params(axis='x', colors='lightgray')
    
    ax2 = ax1.twinx()
    ax2.plot(df[x_col], df[y_line], color='#f59e0b', marker='o', linewidth=2)
    ax2.set_ylabel(y_line, color='lightgray')
    ax2.tick_params(axis='y', colors='lightgray')
    
    plt.title(f"Combo Chart: {y_col_bar} and {y_line} by {x_col}", color='white')
    fig.patch.set_alpha(0.0)
    ax1.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}
