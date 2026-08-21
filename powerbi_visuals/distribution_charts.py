"""
README: Distribution Charts
Covers: Histogram, Box and Whisker chart.
Dependencies: matplotlib, seaborn
"""
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from .trend_charts import _fig_to_base64

def render_histogram(df: pd.DataFrame, x_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    sns.histplot(data=df, x=x_col, kde=True, color='#14b8a6', ax=ax, edgecolor='white')
    ax.set_title(f"Histogram of {x_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel("Count", color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(True, alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_box_and_whisker(df: pd.DataFrame, value_col: str, group_col: str = None):
    fig, ax = plt.subplots(figsize=(8, 4))
    if group_col:
        sns.boxplot(data=df, x=group_col, y=value_col, ax=ax, palette="Set2")
        ax.set_title(f"Box Plot: {value_col} by {group_col}", color='white')
        ax.set_xlabel(group_col, color='lightgray')
    else:
        sns.boxplot(data=df, y=value_col, ax=ax, color='#6366f1')
        ax.set_title(f"Box Plot: {value_col}", color='white')
        
    ax.set_ylabel(value_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(axis='y', alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}
