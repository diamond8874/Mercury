"""
README: Interactivity & Smart Narrative
Covers: Smart Narrative text generation.
"""
import pandas as pd

def render_smart_narrative(df: pd.DataFrame, col1: str, col2: str = None):
    # Generates a simple template-based text summary
    num_rows = len(df)
    
    html = f'''
    <div style="background: rgba(255,255,255,0.05); padding: 1.5rem; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); width: 100%; max-width: 600px;">
        <h3 style="color: #38bdf8; margin-top: 0;">Smart Narrative Insight</h3>
        <p style="color: #cbd5e1; line-height: 1.6;">
            Based on the current dataset, there are <strong>{num_rows:,}</strong> total records.
    '''
    
    if col1 in df.columns:
        if pd.api.types.is_numeric_dtype(df[col1]):
            mean_val = df[col1].mean()
            max_val = df[col1].max()
            html += f" The column <em>{col1}</em> has an average of <strong>{mean_val:,.2f}</strong> with a maximum peak of <strong>{max_val:,.2f}</strong>."
        else:
            top_cat = df[col1].mode()[0] if not df[col1].empty else "N/A"
            unique_vals = df[col1].nunique()
            html += f" The column <em>{col1}</em> contains <strong>{unique_vals}</strong> unique categories, with <strong>{top_cat}</strong> being the most frequent."
            
    if col2 and col2 in df.columns:
        if pd.api.types.is_numeric_dtype(df[col2]):
            mean_val2 = df[col2].mean()
            html += f" Meanwhile, <em>{col2}</em> averages at <strong>{mean_val2:,.2f}</strong>."
        else:
            top_cat2 = df[col2].mode()[0] if not df[col2].empty else "N/A"
            html += f" The most common value in <em>{col2}</em> is <strong>{top_cat2}</strong>."
            
    html += '''
        </p>
    </div>
    '''
    return {"type": "html", "data": html}
