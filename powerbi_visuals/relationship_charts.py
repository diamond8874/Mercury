"""
README: Relationship Charts
Covers: Scatter chart, Bubble chart, Key Influencers (using Random Forest feature importances).
Dependencies: matplotlib, scikit-learn
"""
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from .trend_charts import _fig_to_base64

def render_scatter_chart(df: pd.DataFrame, x_col: str, y_col: str):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df[x_col], df[y_col], alpha=0.6, color='#0ea5e9', edgecolors='white', linewidth=0.5)
    ax.set_title(f"Scatter Chart: {y_col} vs {x_col}", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel(y_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(True, alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_bubble_chart(df: pd.DataFrame, x_col: str, y_col: str, size_col: str):
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # Normalize sizes for bubble plotting
    sizes = df[size_col].fillna(0)
    sizes = (sizes - sizes.min()) / (sizes.max() - sizes.min() + 1e-9) * 1000 + 20
    
    ax.scatter(df[x_col], df[y_col], s=sizes, alpha=0.6, color='#8b5cf6', edgecolors='white', linewidth=0.5)
    ax.set_title(f"Bubble Chart: {y_col} vs {x_col} (Size: {size_col})", color='white')
    ax.set_xlabel(x_col, color='lightgray')
    ax.set_ylabel(y_col, color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(True, alpha=0.1)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}

def render_key_influencers(df: pd.DataFrame, target_col: str):
    """
    Uses scikit-learn Random Forest to compute feature importances (Key Influencers).
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    
    clean_df = df.dropna(subset=[target_col]).copy()
    if len(clean_df) < 5:
        ax.text(0.5, 0.5, "Not enough data for Key Influencers", color='white', ha='center')
        fig.patch.set_alpha(0.0); ax.patch.set_alpha(0.0)
        return {"type": "image", "data": _fig_to_base64(fig)}
        
    y = clean_df[target_col]
    X = clean_df.drop(columns=[target_col])
    
    # Simple encoding for categorical variables
    for col in X.columns:
        if X[col].dtype == 'object' or str(X[col].dtype) == 'category':
            X[col] = LabelEncoder().fit_transform(X[col].astype(str))
            
    X = X.fillna(0)
    
    if pd.api.types.is_numeric_dtype(y):
        model = RandomForestRegressor(n_estimators=50, random_state=42)
    else:
        model = RandomForestClassifier(n_estimators=50, random_state=42)
        
    model.fit(X, y)
    
    importances = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=True)
    importances = importances.tail(10) # Top 10 influencers
    
    ax.barh(importances.index, importances.values, color='#f43f5e')
    ax.set_title(f"Key Influencers on {target_col}", color='white')
    ax.set_xlabel("Importance Score", color='lightgray')
    ax.tick_params(colors='lightgray')
    ax.grid(axis='x', alpha=0.1)
    
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)
    return {"type": "image", "data": _fig_to_base64(fig)}
