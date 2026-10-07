import numpy as np

import keyfit
import recompute
import edc_data as core
from conftest import all_report_csv


def test_load_all_report_roundtrip(small_group):
    P, D, S, _ = small_group
    data = core.load_report(all_report_csv(P, D, S))
    assert data.fmt == "all" and len(data.dest_eans) == 5
    P2, D2, S2 = recompute.to_hundredths(data)
    assert (P2 == P).all() and (D2 == D).all() and (S2 == S).all()


def test_wasted_overlap_is_what_the_exact_method_adds(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    split = core.compute_wasted_split(data.frame)
    res = recompute.recompute(data, list(k), rounds=5)
    gain = core.compute_wasted_split(res.data.frame).shared_total - split.shared_total
    # single producer: the exact method shares exactly the "could have been shared" part
    assert abs(gain - split.overlap) < 0.05
    assert core.compute_wasted_split(res.data.frame).overlap < 0.05


def test_grid_loss_matches_the_wasted_overlap(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    res = recompute.recompute(data, list(k), rounds=5)
    loss = recompute.grid_loss(data, res.data)
    assert abs(loss.lost - core.compute_wasted_split(data.frame).overlap) < 0.05
    assert 0 <= loss.pct_of_production <= loss.pct_of_max <= 100
    assert abs(loss.pct_of_max - 100 * loss.lost / loss.shared_exact) < 1e-9
    same = recompute.grid_loss(res.data, res.data)
    assert same.negligible and same.pct_of_production == 0


def test_could_have_been_shared_matches_the_exact_gain_for_any_selection(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    res = recompute.recompute(data, list(k), rounds=5)
    a, b = core.per_destination(data).set_index("ean"), core.per_destination(res.data).set_index("ean")
    E = data.dest_eans
    for sel in ({E[0]}, set(E[:3]), set(E[1::2]), set(E)):
        gain = core.exact_gain(data, res.data, sel)
        table = sum(b.at[e, "shared"] - a.at[e, "shared"] for e in sel)
        assert abs(gain - table) < 1e-6
        assert abs(recompute.grid_loss(data, res.data, sel).lost - gain) < 1e-6
        s = core.with_overlap(core.summarize(data, sel), gain)
        assert abs(s.overlap - gain) < 1e-9 and abs(s.overlap + s.unshared_only - s.unshared) < 1e-6
        sp = core.with_overlap(core.compute_wasted_split(core.filter_dests(data, sel)), gain)
        total = sp.shared_total + sp.shared_others + sp.overlap + sp.unshared_only
        assert abs(total - float(data.production.sum())) < 0.05
        # before the recompute the tile is only an upper bound
        assert gain <= core.summarize(data, sel).overlap + 0.05


def test_recompute_timing_counts_every_interval(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    tm = recompute.recompute(data, list(k)).timing
    assert tm.intervals == len(P) == tm.n_night + tm.n_enough + tm.n_full
    assert tm.t_total > 0 and tm.per_interval > 0


def test_memoised_filter_is_reused(small_group):
    P, D, S, _ = small_group
    data = core.load_report(all_report_csv(P, D, S))
    a = core.filter_dests(data, set(data.dest_eans[:3]))
    b = core.filter_dests(data, set(data.dest_eans[:3]))
    assert a is b


def _group_data(small_group):
    P, D, S, _ = small_group
    return core.load_report(all_report_csv(P, D, S)), P


def test_production_adds_up_for_any_selection(small_group):
    """selected + shared to unselected + could-have-been + unshared == production."""
    import itertools
    data, P = _group_data(small_group)
    production = P.sum() / 100
    for r in range(1, len(data.dest_eans) + 1):
        for sel in itertools.combinations(data.dest_eans, r):
            sp = core.compute_wasted_split(core.filter_dests(data, set(sel)))
            total = sp.shared_total + sp.shared_others + sp.overlap + sp.unshared_only
            assert abs(total - production) < 0.05, (sel, total, production)
            assert (sp.shared_others > 0) == (len(sel) < len(data.dest_eans))


def test_selection_only_changes_what_is_selected(small_group):
    data, _ = _group_data(small_group)
    one = {data.dest_eans[0]}
    df = core.filter_dests(data, one)
    assert core.KEY_OTHERS in df.columns
    assert core.KEY_OTHERS not in core.filter_dests(data, set(data.dest_eans)).columns
    assert len(core.shared_cols(df)) == 1                     # the others column is not a pair
    s_all = core.summarize(data, set(data.dest_eans))
    s_one = core.summarize(data, one)
    assert s_one.production == s_all.production                # production never depends on it
    assert s_one.shared < s_all.shared


def test_heatmap_production_and_consumption(small_group):
    import figures
    data, P = _group_data(small_group)
    one = {data.dest_eans[0]}
    prod_all = figures.heat_pivot(data, set(data.dest_eans), "production")
    prod_one = figures.heat_pivot(data, one, "production")
    assert prod_all.equals(prod_one)                           # total production, any selection
    cons_all = figures.heat_pivot(data, set(data.dest_eans), "consumption")
    cons_one = figures.heat_pivot(data, one, "consumption")
    assert cons_one.to_numpy().sum() < cons_all.to_numpy().sum()
    assert figures.heat_metrics(data) == ("production", "consumption")


def test_figures_build_for_every_selection(small_group):
    import figures
    data, _ = _group_data(small_group)
    names = {e: f"M{i}" for i, e in enumerate(data.dest_eans + data.source_eans)}
    for sel in (set(data.dest_eans), {data.dest_eans[0]}, {data.dest_eans[1], data.dest_eans[3]}):
        df = core.filter_dests(data, sel)
        figures.fig_total_by_flow(df, data, names)
        figures.fig_daily(df, data, names, sel_day="2026-06-10")
        figures.fig_intraday(df, data, names, "2026-06-10")
        pie = figures.fig_wasted_pie(core.compute_wasted_split(df))
        assert abs(sum(pie.data[0].values) - small_group[0].sum() / 100) < 0.05


def test_intraday_axis_fits_the_selected_day(small_group):
    import figures
    data, _ = _group_data(small_group)
    names = {e: f"M{i}" for i, e in enumerate(data.dest_eans + data.source_eans)}
    df = core.filter_dests(data, set(data.dest_eans))
    agg = figures.aggregate_grid_flows(df).fillna(0)
    days = sorted(set(agg.index.normalize()))
    for day in days[:3]:
        d = str(day.date())
        peak = float(agg.loc[agg.index.normalize() == day].sum(axis=1).max())
        top = figures.intraday_ymax(df, d)
        assert top == (peak if peak > 0 else 1.0)
        assert top <= figures.intraday_ymax(df)               # never above the whole-period peak
        fig = figures.fig_intraday(df, data, names, d)
        assert abs(fig.layout.yaxis.range[1] - top * 1.05) < 1e-9
