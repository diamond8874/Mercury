"""
README: Time-based & Scheduling Charts
Covers: Gantt chart, Calendar Heatmap.
Dependencies: matplotlib, plotly
"""
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import numpy as np
import json
from .trend_charts import _fig_to_base64

def render_gantt_chart(df: pd.DataFrame, task_col: str, start_col: str, end_col: str):
    # Gantt using Plotly Express timeline
    fig = px.timeline(df, x_start=start_col, x_end=end_col, y=task_col, color=task_col)
    fig.update_yaxes(autorange="reversed") # tasks top to bottom
    fig.update_layout(title_text=f"Gantt Chart", font_color="lightgray", 
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False)
    return {"type": "plotly", "data": json.loads(fig.to_json())}

def render_calendar_heatmap(df: pd.DataFrame, date_col: str, value_col: str):
    # Basic calendar heatmap simulation using matplotlib
    # Group by date
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        
    data = df.groupby(df[date_col].dt.date)[value_col].sum().reset_index()
    data[date_col] = pd.to_datetime(data[date_col])
    
    # We will just plot a normal heatmap matrix (day of week vs week of year)
    data['day'] = data[date_col].dt.dayofweek
    data['week'] = data[date_col].dt.isocalendar().week
    
    pivot = data.pivot_table(index='day', columns='week', values=value_col, aggfunc='sum')
    
    fig, ax = plt.subplots(figsize=(10, 3))
    cax = ax.matshow(pivot, cmap='YlGnBu', alpha=0.8)
    
    ax.set_yticks(range(7))
    ax.set_yticklabels(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], color='lightgray')
    ax.set_xlabel('Week of Year', color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.set_title(f"Calendar Heatmap: {value_col}", color='white', pad=20)
    
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}
