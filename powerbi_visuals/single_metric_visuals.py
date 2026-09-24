"""
README: Single Metric Visuals
Covers: Card, Multi-row card, KPI, Gauge.
Returns HTML/CSS strings for clean integration, or matplotlib for Gauge.
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from .trend_charts import _fig_to_base64

def render_card(df: pd.DataFrame, value_col: str, agg_func='sum'):
    if agg_func == 'sum':
        val = df[value_col].sum()
    elif agg_func == 'mean':
        val = df[value_col].mean()
    elif agg_func == 'count':
        val = df[value_col].count()
    else:
        val = df[value_col].iloc[0]
        
    if pd.api.types.is_numeric_dtype(type(val)):
        val_str = f"{val:,.2f}"
    else:
        val_str = str(val)
        
    html = f'''
    <div style="background: rgba(255,255,255,0.05); padding: 2rem; border-radius: 12px; text-align: center; border: 1px solid rgba(255,255,255,0.1);">
        <div style="font-size: 0.9rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem;">{value_col} ({agg_func})</div>
        <div style="font-size: 3rem; font-weight: 700; color: #38bdf8;">{val_str}</div>
    </div>
    '''
    return {"type": "html", "data": html}

def render_multi_row_card(df: pd.DataFrame, group_col: str, value_col: str):
    data = df.groupby(group_col)[value_col].sum().head(5) # limit to 5 for UI
    
    rows_html = ""
    for idx, val in data.items():
        val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
        rows_html += f'''
        <div style="display: flex; justify-content: space-between; padding: 0.75rem 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
            <div style="color: #cbd5e1; font-weight: 500;">{idx}</div>
            <div style="color: #38bdf8; font-weight: 700;">{val_str}</div>
        </div>
        '''
        
    html = f'''
    <div style="background: rgba(255,255,255,0.05); padding: 1.5rem; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); width: 100%; max-width: 400px; margin: 0 auto;">
        <div style="font-size: 0.9rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 1rem;">{value_col} by {group_col}</div>
        {rows_html}
    </div>
    '''
    return {"type": "html", "data": html}

def render_gauge_chart(df: pd.DataFrame, value_col: str, target: float = None):
    val = df[value_col].sum()
    if target is None:
        target = val * 1.5 if val > 0 else 100
        
    fig = plt.figure(figsize=(6, 4))
    ax = fig.add_subplot(111, polar=True)
    
    # Background arc
    ax.bar(x=0, height=1, width=np.pi, bottom=1, color=(1, 1, 1, 0.1), align='edge')

    
    # Value arc
    ratio = min(val / target, 1.0)
    ax.bar(x=0, height=1, width=np.pi * ratio, bottom=1, color='#10b981', align='edge')
    
    ax.set_theta_zero_location('W')
    ax.set_theta_direction(-1)
    
    ax.axis('off')
    
    # Text
    ax.text(np.pi/2, 0.5, f"{val:,.0f}", ha='center', va='center', fontsize=24, fontweight='bold', color='white')
    ax.text(np.pi/2, 0.2, f"Target: {target:,.0f}", ha='center', va='center', fontsize=12, color='lightgray')
    ax.text(np.pi/2, 2.5, f"Gauge: {value_col}", ha='center', va='center', fontsize=14, color='white')
    
    fig.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}
