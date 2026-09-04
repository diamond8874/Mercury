"""
README: Geo Charts
Covers: Bubble map, Choropleth, Shape map.
Dependencies: folium, geopandas
Note: ArcGIS map in Power BI is proprietary, we use Folium as standard open source alternative.
"""
import pandas as pd
import folium
import geopandas as gpd

def _get_base_map(center_lat=0, center_lon=0, zoom=2):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, tiles='CartoDB dark_matter')
    return m

def render_bubble_map(df: pd.DataFrame, lat_col: str, lon_col: str, size_col: str = None, tooltip_col: str = None):
    # Determine center
    if lat_col in df.columns and lon_col in df.columns:
        center_lat = df[lat_col].mean()
        center_lon = df[lon_col].mean()
    else:
        center_lat, center_lon = 0, 0
        
    m = _get_base_map(center_lat, center_lon)
    
    if lat_col in df.columns and lon_col in df.columns:
        # Normalize size if provided
        if size_col and size_col in df.columns:
            sizes = df[size_col].fillna(0)
            max_s = sizes.max()
            min_s = sizes.min()
        else:
            sizes = None
            
        for idx, row in df.iterrows():
            if pd.isna(row[lat_col]) or pd.isna(row[lon_col]):
                continue
            
            radius = 5.0
            if sizes is not None and idx in sizes.index:
                val = sizes.loc[idx]
                if pd.notna(val) and max_s > min_s:
                    radius = 3.0 + 15.0 * float((val - min_s) / (max_s - min_s))
                
            tooltip = str(row[tooltip_col]) if tooltip_col and tooltip_col in df.columns else None
            
            folium.CircleMarker(
                location=[row[lat_col], row[lon_col]],
                radius=radius,
                color='#3b82f6',
                fill=True,
                fill_color='#3b82f6',
                fill_opacity=0.6,
                tooltip=tooltip
            ).add_to(m)
            
    # Return html string
    return {"type": "html", "data": m._repr_html_()}

def render_choropleth_map(df: pd.DataFrame, region_col: str, value_col: str):
    # Note: Requires a GeoJSON boundary file mapping regions to geometries.
    # Without a specific GeoJSON, we will generate a descriptive placeholder.
    html = f'''
    <div style="background: rgba(255,255,255,0.05); padding: 2rem; border-radius: 12px; text-align: center; border: 1px solid rgba(255,255,255,0.1);">
        <div style="font-size: 1.2rem; color: #38bdf8; margin-bottom: 1rem;">Choropleth Map Placeholder</div>
        <div style="color: #cbd5e1;">A Choropleth map for '{value_col}' by '{region_col}' requires matching GeoJSON geometries for the regions, which vary depending on dataset (e.g. World Countries vs US States).</div>
    </div>
    '''
    return {"type": "html", "data": html}
