"""
README: Tabular Visuals
Covers: Table, Matrix.
Returns HTML tables styled for the dark theme.
"""
import pandas as pd

def render_table(df: pd.DataFrame, columns: list = None):
    if columns:
        valid_cols = [c for c in columns if c in df.columns]
        data = df[valid_cols].head(100) # Limit rows for UI performance
    else:
        data = df.head(100)
        
    html = data.to_html(index=False, classes="preview-table", border=0)
    # The frontend already has .preview-table CSS, so we just wrap it
    wrapped = f'''
    <div class="table-scroll-container" style="max-height: 400px; width: 100%;">
        {html}
    </div>
    '''
    return {"type": "html", "data": wrapped}

def render_matrix(df: pd.DataFrame, rows_col: str, cols_col: str, values_col: str, aggfunc='sum'):
    try:
        pivot = df.pivot_table(index=rows_col, columns=cols_col, values=values_col, aggfunc=aggfunc, fill_value=0)
        
        # Add totals
        pivot['Row Total'] = pivot.sum(axis=1)
        pivot.loc['Column Total'] = pivot.sum(axis=0)
        
        html = pivot.to_html(classes="preview-table", border=0)
        wrapped = f'''
        <div class="table-scroll-container" style="max-height: 400px; width: 100%;">
            {html}
        </div>
        '''
        return {"type": "html", "data": wrapped}
    except Exception as e:
        return {"type": "html", "data": f"<div style='color:red;'>Matrix Error: {str(e)}</div>"}
