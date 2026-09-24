"""
README: Geo Charts
Covers: Bubble map, Choropleth, Shape map.
Dependencies: folium, geopandas
Note: ArcGIS map in Power BI is proprietary, we use Folium as standard open source alternative.
"""
from html import escape as html_escape
import pandas as pd
import folium
import geopandas as gpd

def _get_base_map(center_lat=0, center_lon=0, zoom=2):
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, tiles='OpenStreetMap')
    return m

def render_bubble_map(df: pd.DataFrame, lat_col: str, lon_col: str, size_col: str = None, tooltip_col: str = None):
    # Coerce lat and lon to numeric floats safely
    valid_df = df.copy()
    
    # Try converting specified lat/lon columns
    has_valid_coords = False
    if lat_col in valid_df.columns and lon_col in valid_df.columns:
        valid_df.loc[:, '_lat_num'] = pd.to_numeric(valid_df[lat_col], errors='coerce')
        valid_df.loc[:, '_lon_num'] = pd.to_numeric(valid_df[lon_col], errors='coerce')
        if valid_df['_lat_num'].notna().sum() > 0 and valid_df['_lon_num'].notna().sum() > 0:
            has_valid_coords = True

    # If the user selected text columns (e.g. Department, Gender, City) without coordinates:
    if not has_valid_coords:
        # Check if any columns in dataset look like coordinates
        coord_lat = None
        coord_lon = None
        for c in valid_df.columns:
            cl = str(c).lower()
            if any(k in cl for k in ['lat', 'latitude', 'y_coord']):
                coord_lat = c
            elif any(k in cl for k in ['lon', 'lng', 'longitude', 'x_coord']):
                coord_lon = c
        
        if coord_lat and coord_lon:
            valid_df.loc[:, '_lat_num'] = pd.to_numeric(valid_df[coord_lat], errors='coerce')
            valid_df.loc[:, '_lon_num'] = pd.to_numeric(valid_df[coord_lon], errors='coerce')
            if valid_df['_lat_num'].notna().sum() > 0 and valid_df['_lon_num'].notna().sum() > 0:
                has_valid_coords = True

    # If coordinates are present:
    if has_valid_coords:
        valid_coords_df = valid_df.dropna(subset=['_lat_num', '_lon_num'])
        center_lat = float(valid_coords_df['_lat_num'].mean())
        center_lon = float(valid_coords_df['_lon_num'].mean())
        m = _get_base_map(center_lat, center_lon, zoom=4)
        
        sizes = None
        max_s, min_s = 1.0, 0.0
        if size_col and size_col in valid_coords_df.columns:
            s_num = pd.to_numeric(valid_coords_df[size_col], errors='coerce').fillna(0)
            max_s = float(s_num.max())
            min_s = float(s_num.min())
            sizes = s_num

        for idx, row in valid_coords_df.head(1000).iterrows():
            radius = 6.0
            if sizes is not None and max_s > min_s:
                val = sizes.loc[idx]
                radius = 3.0 + 15.0 * float((val - min_s) / (max_s - min_s))
            
            tooltip_txt = None
            if tooltip_col and tooltip_col in row:
                tooltip_txt = f"{tooltip_col}: {row[tooltip_col]}"
            elif lat_col in row and lon_col in row:
                tooltip_txt = f"({row['_lat_num']:.2f}, {row['_lon_num']:.2f})"

            folium.CircleMarker(
                location=[float(row['_lat_num']), float(row['_lon_num'])],
                radius=radius,
                color='#38bdf8',
                fill=True,
                fill_color='#38bdf8',
                fill_opacity=0.65,
                tooltip=tooltip_txt
            ).add_to(m)
            
        full_html = m.get_root().render()
        iframe_wrapper = f'<iframe srcdoc="{html_escape(full_html)}" style="width: 100%; height: 420px; border: none; border-radius: 8px;" sandbox="allow-scripts allow-same-origin"></iframe>'
        return {"type": "html", "data": iframe_wrapper}

    # If the user selected non-coordinate columns (e.g. Categorical column like Department/Country/State),
    # generate an intelligent Geo Map preview with a helpful notice:
    # Build clean interactive world map with informational overlay
    m = _get_base_map(20, 0, zoom=2)
    sample_col = lat_col if lat_col in df.columns else df.columns[0]
    metric_col = lon_col if lon_col in df.columns else (df.columns[1] if len(df.columns) > 1 else df.columns[0])
    
    notice_html = f'''
    <div style="position: absolute; top: 15px; right: 15px; z-index: 1000; background: rgba(15, 23, 42, 0.9); border: 1px solid rgba(56, 189, 248, 0.4); border-radius: 10px; padding: 12px 16px; color: #f8fafc; font-family: sans-serif; max-width: 320px; box-shadow: 0 8px 24px rgba(0,0,0,0.5);">
        <div style="font-weight: 700; color: #38bdf8; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
            <span>🌍 Geo Map Notice</span>
        </div>
        <p style="margin: 0; font-size: 0.8rem; color: #cbd5e1; line-height: 1.4;">
            Column <strong>"{sample_col}"</strong> does not contain numerical coordinates (latitude/longitude). 
            To plot exact geospatial points, ensure your dataset includes numeric <em>Latitude</em> and <em>Longitude</em> columns.
        </p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(notice_html))
    full_html = m.get_root().render()
    iframe_wrapper = f'<iframe srcdoc="{html_escape(full_html)}" style="width: 100%; height: 420px; border: none; border-radius: 8px;" sandbox="allow-scripts allow-same-origin"></iframe>'
    return {"type": "html", "data": iframe_wrapper}

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
