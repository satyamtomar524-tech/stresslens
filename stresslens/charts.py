"""Feature timelines that keep missing measurements visible as gaps."""
import pandas as pd
import streamlit as st

from stresslens.face import FEATURE_LABELS


def render_feature_trend(rows, height=220):
    st.vega_lite_chart(
        pd.DataFrame(rows),
        spec={
            "transform": [{"fold": list(FEATURE_LABELS), "as": ["Feature", "Coefficient"]}],
            "mark": {"type": "line", "invalid": "break-paths-show-domains",
                     "point": {"filled": True, "size": 12}},
            "encoding": {
                "x": {"field": "seconds", "type": "quantitative", "title": "Time (seconds)"},
                "y": {"field": "Coefficient", "type": "quantitative"},
                "color": {"field": "Feature", "type": "nominal"},
                "order": {"field": "seconds", "type": "quantitative"},
                "tooltip": [{"field": "seconds", "type": "quantitative"},
                            {"field": "Feature", "type": "nominal"},
                            {"field": "Coefficient", "type": "quantitative"}],
            },
        },
        height=height, width="stretch",
    )
