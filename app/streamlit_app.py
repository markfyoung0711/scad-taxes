"""Entry point: gate the request, then hand off to the page that was asked for."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import gate

# The butterfly alone, without the wordmark: the header and the browser tab
# both draw it at 32px or less, where the lettering would only be a smudge.
ICON = str(Path(__file__).parent / "static" / "icon.png")

st.set_page_config(page_title="Butterfly · Smith County property taxes",
                   page_icon=ICON, layout="wide")
st.logo(ICON, size="large")

# Before anything is rendered or queried, on every page.
gate.check()

st.navigation([
    st.Page("lookup.py", title="Parcel lookup", default=True),
    st.Page("heatmap.py", title="Heat map", url_path="heatmap"),
]).run()
