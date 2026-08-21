import pandas as pd
import logging
from powerbi_visuals.comparison_charts import render_bar_chart, render_clustered_column_chart
from powerbi_visuals.trend_charts import render_line_chart, render_area_chart, render_combo_chart, render_column_chart
from powerbi_visuals.relationship_charts import render_scatter_chart, render_bubble_chart
from powerbi_visuals.part_to_whole_charts import render_pie_chart, render_donut_chart, render_treemap
from powerbi_visuals.distribution_charts import render_histogram, render_box_and_whisker
from powerbi_visuals.change_flow_charts import render_waterfall_chart

def generate_custom_chart(df: pd.DataFrame, chart_type: str, params: dict):
    """
    Routes a visualization request to the appropriate powerbi_visuals function.
    Returns {"type": "image", "data": "base64..."} or an error dict.
    """
    try:
        if chart_type == "bar":
            return render_bar_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "clustered_column":
            return render_clustered_column_chart(df, params.get('x_col'), params.get('y_col'), params.get('y_col_2'))
        elif chart_type == "column":
            return render_column_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "line":
            return render_line_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "area":
            return render_area_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "combo":
            return render_combo_chart(df, params.get('x_col'), params.get('y_col'), params.get('y_col_2'))
        elif chart_type == "scatter":
            return render_scatter_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "bubble":
            return render_bubble_chart(df, params.get('x_col'), params.get('y_col'), params.get('size_col'))
        elif chart_type == "pie":
            return render_pie_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "donut":
            return render_donut_chart(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "treemap":
            return render_treemap(df, params.get('x_col'), params.get('y_col'))
        elif chart_type == "histogram":
            return render_histogram(df, params.get('x_col'))
        elif chart_type == "box":
            return render_box_and_whisker(df, params.get('y_col'), params.get('x_col'))
        elif chart_type == "waterfall":
            return render_waterfall_chart(df, params.get('x_col'), params.get('y_col'))
        else:
            return {"error": f"Unsupported chart type: {chart_type}"}
    except Exception as e:
        logging.error(f"Error generating chart {chart_type}: {str(e)}")
        return {"error": str(e)}
