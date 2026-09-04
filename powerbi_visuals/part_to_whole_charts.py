"""
README: Part-to-Whole Charts
Covers: Pie chart, Donut chart, Stacked column, 100% Stacked column, Treemap, Sunburst.
Dependencies: matplotlib, squarify, plotly
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import squarify
import plotly.express as px
import json
from .trend_charts import _fig_to_base64

def render_pie_chart(df: pd.DataFrame, label_col: str, value_col: str, top_n: int = 10):
    fig, ax = plt.subplots(figsize=(8, 6)) # slightly wider for legend if needed
    data = df.groupby(label_col)[value_col].sum().sort_values(ascending=False)
    
    if len(data) > top_n:
        top_data = data.iloc[:top_n]
        other_data = pd.Series([data.iloc[top_n:].sum()], index=['Other'])
        data = pd.concat([top_data, other_data])

    ax.pie(data, labels=data.index, autopct='%1.1f%%', startangle=90, textprops={'color': 'lightgray'}, pctdistance=0.85)
    
    # Optional: adjust label distance or use legend if labels overlap, but top 10 usually fits well
    ax.set_title(f"Pie Chart: {value_col} by {label_col}", color='white')
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}


def render_donut_chart(df: pd.DataFrame, label_col: str, value_col: str, top_n: int = 10):
    fig, ax = plt.subplots(figsize=(8, 6))
    data = df.groupby(label_col)[value_col].sum().sort_values(ascending=False)
    
    if len(data) > top_n:
        top_data = data.iloc[:top_n]
        other_data = pd.Series([data.iloc[top_n:].sum()], index=['Other'])
        data = pd.concat([top_data, other_data])

    ax.pie(data, labels=data.index, autopct='%1.1f%%', startangle=90, 
           textprops={'color': 'lightgray'}, pctdistance=0.85, wedgeprops=dict(width=0.4, edgecolor='w'))
    ax.set_title(f"Donut Chart: {value_col} by {label_col}", color='white')
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_stacked_column_chart(df: pd.DataFrame, x_col: str, group_col: str, value_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    pivot = df.pivot_table(index=x_col, columns=group_col, values=value_col, aggfunc='sum').fillna(0)
    
    bottom = np.zeros(len(pivot))
    for col in pivot.columns:
        ax.bar(pivot.index.astype(str), pivot[col], bottom=bottom, label=col)
        bottom += pivot[col].values
        
    ax.set_title(f"Stacked Column: {value_col} by {x_col} and {group_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel(value_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.legend(facecolor='#1e293b', edgecolor='none', labelcolor='lightgray')
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_100_stacked_column_chart(df: pd.DataFrame, x_col: str, group_col: str, value_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    pivot = df.pivot_table(index=x_col, columns=group_col, values=value_col, aggfunc='sum').fillna(0)
    pivot_pct = pivot.div(pivot.sum(axis=1), axis=0)
    
    bottom = np.zeros(len(pivot_pct))
    for col in pivot_pct.columns:
        ax.bar(pivot_pct.index.astype(str), pivot_pct[col], bottom=bottom, label=col)
        bottom += pivot_pct[col].values
        
    ax.set_title(f"100% Stacked Column: {value_col} by {x_col} and {group_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel('Percentage', color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.legend(facecolor='#1e293b', edgecolor='none', labelcolor='lightgray', bbox_to_anchor=(1.05, 1))
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_treemap(df: pd.DataFrame, label_col: str, value_col: str):
    fig, ax = plt.subplots(figsize=(8, 4))
    data = df.groupby(label_col)[value_col].sum().sort_values(ascending=False)
    data = data[data > 0]
    
    if len(data) > 0:
        squarify.plot(sizes=data.values, label=data.index, alpha=0.8, ax=ax, text_kwargs={'color':'white'})
    ax.set_title(f"Treemap: {value_col} by {label_col}", color='white')
    ax.axis('off')
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_sunburst_chart(df: pd.DataFrame, path_cols: list, value_col: str):
    # Sunburst uses plotly
    fig = px.sunburst(df, path=path_cols, values=value_col, title=f"Sunburst Chart: {value_col}")
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='lightgray'))
    return {"type": "plotly", "data": json.loads(fig.to_json())}
