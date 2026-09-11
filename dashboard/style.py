import streamlit as st

# `st.metric` truncates its label/value with an ellipsis (Streamlit measures
# the rendered text against the container and swaps in `white-space: nowrap;
# overflow: hidden; text-overflow: ellipsis` once it doesn't fit) rather than
# shrinking or wrapping. That's tuned for a handful of digits in a wide
# column; on a phone, or a 4-tile row like Policy Health's, a figure like
# "3608 of 3608" or a two-sided range like "£372.07-£3,180.53" routinely
# doesn't fit and gets clipped mid-number.
#
# `container-type: inline-size` + `cqw` ties the font size to the metric's
# own box width rather than the viewport, so it scales down in a narrow
# column even when the viewport itself is wide (a 4-up row). `white-space:
# normal` + `overflow-wrap: anywhere` is the fallback for whatever the clamp
# floor still doesn't fit — wrapping to a second line, never an ellipsis.
_METRIC_CSS = """
<style>
[data-testid="stMetric"] {
    container-type: inline-size;
    overflow: visible !important;
}
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] p {
    font-size: clamp(0.85rem, 13cqw, 2.25rem) !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    overflow-wrap: anywhere !important;
    line-height: 1.2 !important;
}
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p {
    font-size: clamp(0.7rem, 6.5cqw, 0.95rem) !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    overflow-wrap: anywhere !important;
}
[data-testid="stMetricDelta"],
[data-testid="stMetricDelta"] p {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    overflow-wrap: anywhere !important;
}
</style>
"""


def inject_responsive_metric_css() -> None:
    st.markdown(_METRIC_CSS, unsafe_allow_html=True)
