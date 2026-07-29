"""
Visualisation engine.

Charts are produced in three steps:

1. **Spec generation** - decide *what* to plot. The LLM proposes charts when a
   key is configured (:func:`generate_ai_charts`); otherwise a deterministic
   statistical planner does it (:func:`generate_auto_charts`). Both emit the
   same spec shape, so everything downstream is provider-agnostic.
2. **Payload building** - :func:`build_chart_payload` turns a spec plus the
   cleaned DataFrame into the label/value arrays Chart.js renders in the browser.
3. **Image rendering** - :func:`render_chart_images` draws the same specs with
   Matplotlib for the PDF report.

Spec shape::

    {"chart_type": "histogram|bar|pie|line|scatter|box|correlation",
     "title": str, "x_axis": str, "y_axis": str|None, "description": str}
"""

import os
import json
import logging

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # non-interactive backend: safe inside worker threads
import matplotlib.pyplot as plt  # noqa: E402

from utils.helpers import parse_json_response  # noqa: E402

CHART_TYPES = ("histogram", "bar", "pie", "line", "scatter", "box", "correlation")
PALETTE = ["#6366f1", "#a855f7", "#10b981", "#f59e0b", "#3b82f6", "#ec4899", "#14b8a6", "#ef4444"]
MAX_CHARTS = 6


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------

def _numeric_columns(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().any()]


def _categorical_columns(df, max_cardinality=20):
    out = []
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        unique = df[col].nunique(dropna=True)
        if 1 < unique <= max_cardinality:
            out.append(col)
    return out


def _datetime_columns(df):
    return [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]


# Verbs that introduce the thing being modelled: "predict <target> from ...".
TARGET_VERBS = ("predicting", "predict", "classify", "forecast", "estimate",
                "target is", "target:", "model the", "detect")
# Words that end the target clause and start the feature list.
FEATURE_PREPOSITIONS = (" from ", " using ", " based on ", " with ", " given ",
                        " by ", " against ", " on the basis of ")


def guess_target_column(df, goal=None):
    """Find the most likely modelling target from the goal text or column names."""
    # Longest column names first, so "Churned_Status" wins over "Status".
    by_length = sorted((str(c) for c in df.columns), key=len, reverse=True)

    if goal:
        goal_lower = goal.lower()
        # A column named right after a modelling verb is the target. The window
        # stops at the first "from"/"using"/... so feature columns listed later
        # in the sentence cannot win.
        for verb in TARGET_VERBS:
            position = goal_lower.find(verb)
            if position == -1:
                continue
            window = goal_lower[position + len(verb):position + len(verb) + 80]
            cut = min((window.find(word) for word in FEATURE_PREPOSITIONS
                       if window.find(word) != -1), default=-1)
            if cut > 0:
                window = window[:cut]
            for col in by_length:
                if col.lower() in window:
                    return col
        for col in by_length:
            if col.lower() in goal_lower:
                return col

    keywords = ("target", "label", "churn", "outcome", "result", "class",
                "price", "sales", "revenue", "score", "status")
    for col in by_length:
        lowered = col.lower()
        if lowered == "y" or any(keyword in lowered for keyword in keywords):
            return col
    return None


# ---------------------------------------------------------------------------
# Deterministic planner (no API key needed)
# ---------------------------------------------------------------------------

def generate_auto_charts(df, goal=None, max_charts=MAX_CHARTS):
    """
    Pick a sensible chart set from the data itself.

    Used when no LLM is configured, when the provider call fails, and as the
    validation baseline for AI-proposed charts.
    """
    if df is None or df.empty:
        return []

    charts = []
    numeric = _numeric_columns(df)
    categorical = _categorical_columns(df)
    datetimes = _datetime_columns(df)
    target = guess_target_column(df, goal)

    # 1. Distribution of the most-varying numeric column.
    if numeric:
        spread = {c: float(df[c].std(skipna=True) or 0) for c in numeric}
        primary = max(spread, key=spread.get)
        charts.append({
            "chart_type": "histogram",
            "title": f"Distribution of {primary}",
            "x_axis": primary,
            "y_axis": None,
            "description": f"How values of '{primary}' are spread, revealing skew, gaps and outliers.",
        })

    # 2. Breakdown of the smallest categorical column.
    if categorical:
        smallest = min(categorical, key=lambda c: df[c].nunique(dropna=True))
        chart_type = "pie" if df[smallest].nunique(dropna=True) <= 6 else "bar"
        charts.append({
            "chart_type": chart_type,
            "title": f"{smallest} Breakdown",
            "x_axis": smallest,
            "y_axis": None,
            "description": f"Share of each '{smallest}' category, showing class balance in the dataset.",
        })

    # 3. Target vs. strongest driver.
    if target is not None and numeric:
        driver = next((c for c in numeric if c != target), None)
        if pd.api.types.is_numeric_dtype(df[target]) and driver:
            charts.append({
                "chart_type": "bar",
                "title": f"Average {target} by {driver} band"
                         if df[driver].nunique() > 15 else f"Average {target} by {driver}",
                "x_axis": driver,
                "y_axis": target,
                "description": f"Relationship between '{driver}' and the modelling target '{target}'.",
            })
        elif categorical and driver:
            grouping = next((c for c in categorical if c != target), categorical[0])
            charts.append({
                "chart_type": "bar",
                "title": f"Average {driver} by {grouping}",
                "x_axis": grouping,
                "y_axis": driver,
                "description": f"Mean '{driver}' across each '{grouping}' group.",
            })

    # 4. Strongest numeric correlation as a scatter.
    if len(numeric) >= 2:
        try:
            matrix = df[numeric].corr(numeric_only=True).abs()
            np.fill_diagonal(matrix.values, 0)
            x = matrix.max().idxmax()
            y = matrix[x].idxmax()
            if x != y and float(matrix.loc[x, y]) > 0.1:
                charts.append({
                    "chart_type": "scatter",
                    "title": f"{y} vs {x}",
                    "x_axis": x,
                    "y_axis": y,
                    "description": f"Strongest numeric relationship in the dataset (|r| = {matrix.loc[x, y]:.2f}).",
                })
        except Exception as exc:  # noqa: BLE001
            logging.debug(f"Auto scatter skipped: {exc}")

    # 5. Trend over time when a real date column survived cleaning.
    if datetimes and numeric:
        charts.append({
            "chart_type": "line",
            "title": f"{numeric[0]} over {datetimes[0]}",
            "x_axis": datetimes[0],
            "y_axis": numeric[0],
            "description": f"Chronological trend of '{numeric[0]}' across '{datetimes[0]}'.",
        })

    # 6. Correlation overview.
    if len(numeric) >= 3:
        charts.append({
            "chart_type": "correlation",
            "title": "Strongest Feature Correlations",
            "x_axis": None,
            "y_axis": None,
            "description": "Top absolute Pearson correlations between numeric features - useful for spotting multicollinearity.",
        })

    return charts[:max_charts]


# ---------------------------------------------------------------------------
# AI planner (works with any provider)
# ---------------------------------------------------------------------------

CHART_PROMPT = """You are a senior data visualisation analyst.

The user's goal is:
"{goal}"

Cleaned dataset profile:
{profile}

Propose between 3 and {max_charts} charts that best explain this dataset for that goal.
Rules:
- chart_type must be one of: histogram, bar, pie, line, scatter, box, correlation.
- x_axis and y_axis must be EXACT column names from the profile (or null).
- histogram/pie need only x_axis. scatter/line need numeric x_axis AND y_axis.
- bar may use x_axis alone (counts) or x_axis + numeric y_axis (group means).
- correlation needs neither axis.
- Never propose the same chart twice.

Return valid JSON only:
{{"charts": [{{"chart_type": "...", "title": "...", "x_axis": "...", "y_axis": null,
              "description": "One sentence on what this chart reveals."}}]}}"""


def validate_chart_specs(specs, df, max_charts=MAX_CHARTS):
    """Drop specs that reference missing columns or impossible axis combinations."""
    valid = []
    seen = set()
    columns = set(map(str, df.columns))

    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        chart_type = str(spec.get("chart_type", "")).lower().strip()
        if chart_type not in CHART_TYPES:
            continue

        x = spec.get("x_axis")
        y = spec.get("y_axis")
        x = str(x) if x is not None else None
        y = str(y) if y is not None else None

        if chart_type == "correlation":
            if len(_numeric_columns(df)) < 2:
                continue
            x = y = None
        else:
            if x not in columns:
                continue
            if chart_type in ("scatter", "line"):
                if y not in columns or not pd.api.types.is_numeric_dtype(df[y]):
                    continue
            elif y is not None and y not in columns:
                y = None

        key = (chart_type, x, y)
        if key in seen:
            continue
        seen.add(key)

        valid.append({
            "chart_type": chart_type,
            "title": str(spec.get("title") or f"{chart_type.title()} of {x or 'dataset'}"),
            "x_axis": x,
            "y_axis": y,
            "description": str(spec.get("description") or ""),
        })
        if len(valid) >= max_charts:
            break
    return valid


def generate_ai_charts(llm, df, goal, profile=None, max_charts=MAX_CHARTS):
    """
    Ask the configured model for a chart plan; fall back to the deterministic
    planner whenever that is not possible or the answer is unusable.

    Returns ``(specs, source)`` where source is ``"ai"`` or ``"auto"``.
    """
    if llm is None or not llm.is_live:
        return generate_auto_charts(df, goal, max_charts), "auto"

    try:
        if profile is None:
            from services.profile_service import build_profile, compact_profile_for_llm
            profile = compact_profile_for_llm(build_profile(df))

        prompt = CHART_PROMPT.format(
            goal=goal or "General exploratory analysis",
            profile=json.dumps(profile, indent=2, default=str)[:6000],
            max_charts=max_charts,
        )
        response = llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=1200, json_mode=True,
        )
        parsed = parse_json_response(response)
        specs = validate_chart_specs(parsed.get("charts", []), df, max_charts)
        if specs:
            return specs, "ai"
        logging.warning("AI chart plan produced no valid specs; using the statistical planner.")
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades gracefully
        logging.warning(f"AI chart planning failed ({exc}); using the statistical planner.")

    return generate_auto_charts(df, goal, max_charts), "auto"


# ---------------------------------------------------------------------------
# Chart.js payloads
# ---------------------------------------------------------------------------

def _histogram_bins(series, bins=12):
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return [], []
    if values.nunique() <= bins:
        counts = values.value_counts().sort_index()
        return [str(i) for i in counts.index], [int(v) for v in counts.values]
    counts, edges = np.histogram(values, bins=bins)
    labels = [f"{edges[i]:.4g} - {edges[i + 1]:.4g}" for i in range(len(counts))]
    return labels, [int(c) for c in counts]


def _top_correlations(df, limit=10):
    numeric = _numeric_columns(df)
    if len(numeric) < 2:
        return [], []
    matrix = df[numeric].corr(numeric_only=True)
    pairs = []
    seen = set()
    for x in matrix.columns:
        for y in matrix.columns:
            if x == y or (y, x) in seen:
                continue
            seen.add((x, y))
            value = matrix.loc[x, y]
            if pd.notna(value):
                pairs.append((f"{x} ~ {y}", float(value)))
    pairs.sort(key=lambda item: abs(item[1]), reverse=True)
    pairs = pairs[:limit]
    return [p[0] for p in pairs], [round(p[1], 3) for p in pairs]


def build_chart_payload(df, specs):
    """Turn validated specs into ready-to-render Chart.js data."""
    rendered = []
    for spec in specs or []:
        chart_type = spec.get("chart_type")
        x, y = spec.get("x_axis"), spec.get("y_axis")
        item = {
            "chart_type": chart_type,
            "title": spec.get("title"),
            "description": spec.get("description", ""),
            "x_axis": x,
            "y_axis": y,
        }

        try:
            if chart_type == "correlation":
                labels, values = _top_correlations(df)
                if not labels:
                    continue
                item.update(labels=labels, values=values, chart_type="bar", orientation="horizontal")

            elif chart_type == "histogram":
                labels, values = _histogram_bins(df[x])
                if not labels:
                    continue
                item.update(labels=labels, values=values)

            elif chart_type == "pie":
                counts = df[x].astype(str).value_counts().head(8)
                item.update(labels=[str(i) for i in counts.index],
                            values=[int(v) for v in counts.values])

            elif chart_type == "box":
                values = pd.to_numeric(df[x], errors="coerce").dropna()
                if values.empty:
                    continue
                quartiles = [values.min(), values.quantile(0.25), values.median(),
                             values.quantile(0.75), values.max()]
                item.update(chart_type="bar",
                            labels=["min", "Q1", "median", "Q3", "max"],
                            values=[round(float(q), 4) for q in quartiles])

            elif chart_type == "scatter":
                subset = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna().head(400)
                if subset.empty:
                    continue
                item["points"] = [{"x": float(row[x]), "y": float(row[y])}
                                  for _, row in subset.iterrows()]

            elif chart_type == "line":
                subset = df[[x, y]].dropna().sort_values(by=x).head(120)
                if subset.empty:
                    continue
                item.update(labels=[str(v) for v in subset[x]],
                            values=[float(v) for v in pd.to_numeric(subset[y], errors="coerce").fillna(0)])

            else:  # bar
                if y and y in df.columns and pd.api.types.is_numeric_dtype(df[y]):
                    if df[x].nunique(dropna=True) > 15 and pd.api.types.is_numeric_dtype(df[x]):
                        # Too many distinct x values: bucket them before averaging.
                        buckets = pd.cut(pd.to_numeric(df[x], errors="coerce"), bins=10)
                        grouped = df.groupby(buckets, observed=True)[y].mean().dropna()
                        labels = [str(i) for i in grouped.index]
                    else:
                        grouped = df.groupby(df[x].astype(str), observed=True)[y].mean().dropna().head(15)
                        labels = [str(i) for i in grouped.index]
                    if grouped.empty:
                        continue
                    item.update(labels=labels, values=[round(float(v), 4) for v in grouped.values])
                else:
                    counts = df[x].astype(str).value_counts().head(15)
                    if counts.empty:
                        continue
                    item.update(labels=[str(i) for i in counts.index],
                                values=[int(v) for v in counts.values])

            rendered.append(item)
        except Exception as exc:  # noqa: BLE001 - one bad chart must not sink the batch
            logging.warning(f"Chart payload failed for '{spec.get('title')}': {exc}")

    return rendered


# ---------------------------------------------------------------------------
# Matplotlib rendering for the PDF report
# ---------------------------------------------------------------------------

def render_chart_images(df, specs, output_dir, prefix, font_name=None):
    """Draw every spec to a PNG. Returns ``[(path, description), ...]``."""
    images = []
    for index, spec in enumerate(specs or []):
        chart_type = spec.get("chart_type")
        title = spec.get("title") or f"Chart {index + 1}"
        x, y = spec.get("x_axis"), spec.get("y_axis")

        figure = plt.figure(figsize=(6.4, 3.6))
        try:
            axes = figure.add_subplot(111)

            if chart_type == "correlation":
                labels, values = _top_correlations(df)
                if not labels:
                    plt.close(figure)
                    continue
                colors = ["#ef4444" if v < 0 else "#6366f1" for v in values]
                axes.barh(labels[::-1], values[::-1], color=colors[::-1])
                axes.set_xlabel("Pearson r")

            elif chart_type == "histogram":
                values = pd.to_numeric(df[x], errors="coerce").dropna()
                if values.empty:
                    plt.close(figure)
                    continue
                axes.hist(values, bins=min(20, max(5, values.nunique())), color="#6366f1", edgecolor="white")
                axes.set_xlabel(x)
                axes.set_ylabel("Frequency")

            elif chart_type == "pie":
                counts = df[x].astype(str).value_counts().head(6)
                axes.pie(counts.values, labels=[str(i) for i in counts.index],
                         autopct="%1.1f%%", colors=PALETTE[:len(counts)])
                axes.set_ylabel("")

            elif chart_type == "box":
                values = pd.to_numeric(df[x], errors="coerce").dropna()
                if values.empty:
                    plt.close(figure)
                    continue
                axes.boxplot(values, vert=True, patch_artist=True,
                             boxprops={"facecolor": "#a855f7", "alpha": 0.6})
                axes.set_ylabel(x)

            elif chart_type == "scatter":
                subset = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna().head(1000)
                if subset.empty:
                    plt.close(figure)
                    continue
                axes.scatter(subset[x], subset[y], color="#a855f7", alpha=0.7, s=18)
                axes.set_xlabel(x)
                axes.set_ylabel(y)

            elif chart_type == "line":
                subset = df[[x, y]].dropna().sort_values(by=x).head(200)
                if subset.empty:
                    plt.close(figure)
                    continue
                axes.plot(subset[x], pd.to_numeric(subset[y], errors="coerce"), color="#6366f1")
                axes.set_xlabel(x)
                axes.set_ylabel(y)

            else:  # bar
                if y and y in df.columns and pd.api.types.is_numeric_dtype(df[y]):
                    grouped = df.groupby(df[x].astype(str), observed=True)[y].mean().dropna().head(12)
                    axes.bar([str(i) for i in grouped.index], grouped.values, color="#10b981")
                    axes.set_ylabel(f"Avg {y}")
                else:
                    counts = df[x].astype(str).value_counts().head(12)
                    axes.bar([str(i) for i in counts.index], counts.values, color="#6366f1")
                    axes.set_ylabel("Count")
                axes.set_xlabel(x)

            title_kwargs = {"fontsize": 12, "fontweight": "bold"}
            if font_name:
                title_kwargs["fontname"] = font_name
            axes.set_title(title, **title_kwargs)
            for label in axes.get_xticklabels():
                label.set_rotation(35)
                label.set_ha("right")
                label.set_fontsize(7)
            figure.tight_layout()

            image_path = os.path.join(output_dir, f"{prefix}_chart_{index}.png")
            figure.savefig(image_path, dpi=170)
            images.append((image_path, spec.get("description", "")))
        except Exception as exc:  # noqa: BLE001
            logging.warning(f"Could not render '{title}' for the PDF: {exc}")
        finally:
            plt.close(figure)

    return images
