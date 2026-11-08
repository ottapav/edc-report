"""Plotly figures of the report.

:mod:`figures.base` holds the themes, member colours and the shared chart shapes;
:mod:`figures.energy` draws the energy report (kWh), :mod:`figures.money` the billing (Kč),
:mod:`figures.spot` the spot-market comparison (Kč).
"""

from .base import (
    OTHER, THEMES, colour_map, legend_entries, pair_figures, share_stack_ymax,
    share_xrange, theme, top_dests,
)
from .energy import (
    fig_daily, fig_heatmap, fig_intraday, fig_total_by_flow, fig_wasted_pie, flow_order,
    heat_metrics, heat_pivot, intraday_ymax,
)
from .money import (
    bill_columns, fig_bill_daily, fig_bill_intraday, fig_bill_monthly, fig_bill_pie,
)
from .spot import (
    fig_spot_daily, fig_spot_intraday, fig_spot_members, fig_spot_mix, fig_spot_monthly,
    fig_spot_parties,
)

__all__ = [
    "OTHER", "THEMES", "bill_columns", "colour_map", "fig_bill_daily",
    "fig_bill_intraday", "fig_bill_monthly", "fig_bill_pie", "fig_daily",
    "fig_spot_daily", "fig_spot_intraday", "fig_spot_members", "fig_spot_mix", "fig_spot_monthly",
    "fig_spot_parties",
    "fig_heatmap", "fig_intraday", "fig_total_by_flow", "fig_wasted_pie", "flow_order",
    "heat_metrics", "heat_pivot", "intraday_ymax", "legend_entries", "pair_figures",
    "share_stack_ymax", "share_xrange", "theme", "top_dests",
]
