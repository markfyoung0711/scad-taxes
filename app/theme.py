"""Chart tokens for the Streamlit gallery.

Both modes are selected, not flipped: the dark column is the same hues stepped
for the dark surface. The four-slot categorical set is validated for adjacent
pairs in both modes; on light, aqua and yellow fall under 3:1 against the
surface, so every chart that uses them also offers the table view.
"""
from __future__ import annotations

LIGHT = {
    "surface": "#fcfcfb",
    "text_primary": "#0b0b0b",
    "text_secondary": "#52514e",
    "grid": "#e6e5e1",
    "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "pos": "#2a78d6",
    "neg": "#e34948",
    "mid": "#f0efec",
    "template": "plotly_white",
}

DARK = {
    "surface": "#1a1a19",
    "text_primary": "#ffffff",
    "text_secondary": "#c3c2b7",
    "grid": "#38383a",
    "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    "pos": "#3987e5",
    "neg": "#e66767",
    "mid": "#383835",
    "template": "plotly_dark",
}


def tokens(mode: str) -> dict:
    return DARK if mode == "dark" else LIGHT


def style(fig, t: dict, *, height: int = 380, legend: bool = True,
          margin: dict | None = None):
    """Recessive grid and axes, text in ink tokens, surface behind the marks."""
    fig.update_layout(
        template=t["template"],
        height=height,
        paper_bgcolor=t["surface"],
        plot_bgcolor=t["surface"],
        font=dict(color=t["text_primary"], size=13),
        margin=margin or dict(l=8, r=8, t=32, b=8),
        hovermode="x unified",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(color=t["text_secondary"])),
    )
    fig.update_xaxes(showgrid=False, linecolor=t["grid"], tickfont=dict(color=t["text_secondary"]))
    fig.update_yaxes(gridcolor=t["grid"], zeroline=False, linecolor=t["grid"],
                     tickfont=dict(color=t["text_secondary"]))
    return fig
