"""UI strings (cs / en) and number formatting."""

from __future__ import annotations

import math

import pandas as pd

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # --- plots (from plot_energy_sharing.py) ---
        "report_title": "Electricity sharing report",
        "report_title_group": "Electricity sharing report — group {group}",
        "total_by_flow_title": "Total energy by flow (stacked)",
        "total_energy_xlabel": "Total energy [kWh]",
        "daily_title": "Daily energy by destination (stacked)",
        "daily_title_lines": "Daily energy by destination (lines, log)",
        "daily_ylabel": "Daily energy [kWh]",
        "shared": "shared",
        "unmet": "unmet",
        "unshared": "unshared",
        "source": "Source",
        "total_source": "TOTAL SOURCE",
        "total_destination": "TOTAL DESTINATION",
        "no_data": "No data",
        "grid": "GRID",
        "unshared_paren": "(unshared)",
        "unmet_paren": "(unmet)",
        "destination": "Destination",
        "source_a": "Source",
        "pie_title": "Shared vs unshared surplus",
        "pie_unshared_only": "unshared",
        "pie_shared": "shared",
        "pie_wasted": "could have been shared",
        "pie_subtitle": "Wasted = min(unshared, unmet) per 15-min interval",
        "pie_no_overlap": "No concurrent overlap",
        "pie_union": "Total source: {total} kWh",
        # --- web UI ---
        "app_title": "SharEl sharing report",
        "upload_prompt": "Drag and drop a SharEl CSV export here, or click to choose a file",
        "upload_hint": "Part report (<ean>-<ean> columns) or all report (IN/OUT-<ean>-D/O columns). "
                       "The file is processed in memory and not stored.",
        "upload_other": "Upload another file",
        "loaded": "Loaded",
        "error": "Could not read the file",
        "session_lost": "The uploaded data is no longer on the server (it was restarted). Please upload the file again.",
        "panel_dest": "Destinations",
        "panel_dest_hint": "Tick to include; type a name to relabel.",
        "panel_source": "Source",
        "panel_display": "Display",
        "panel_group": "Sharing group ID",
        "panel_group_ph": "e.g. 0000018947",
        "all": "All",
        "none": "None",
        "yscale": "Daily plot y-axis",
        "linear": "linear (stacked)",
        "log": "log (lines)",
        "show_unshared": "Show unshared (grid export)",
        "show_unmet": "Show unmet (from grid)",
        "language": "Language",
        # info section
        "info_title": "General information",
        "file": "File",
        "report_type": "Report type",
        "type_all": "all report (production + consumption)",
        "type_part": "part report (shared pairs only)",
        "period": "Period",
        "days": "days",
        "intervals": "15-min intervals",
        "producer": "Producer EAN",
        "n_dest": "Destinations",
        "selected_of": "{sel} of {n} selected",
        "peak": "Peak production",
        "best_day": "Best sharing day",
        "days_sharing": "Days with sharing",
        "kpi_production": "Production",
        "kpi_shared": "Shared",
        "kpi_wasted": "Could have been shared",
        "kpi_unshareable": "Surplus above group demand",
        "kpi_consumption": "Members' consumption",
        "kpi_from_grid": "From grid",
        "of_production": "of production",
        "of_consumption": "of consumption",
        "kpi_note": "Figures follow the destination selection; production and grid export are producer totals.",
        "table_title": "Per destination",
        "col_name": "Name",
        "col_ean": "EAN",
        "col_consumption": "Consumption [kWh]",
        "col_shared": "Shared [kWh]",
        "col_unmet": "Unmet [kWh]",
        "col_coverage": "Covered by sharing",
        "col_share": "Share of shared",
        "col_data": "Data from",
        "col_data_pct": "Data rows",
        "notes": "Data notes",
        # --- phase 3: hourly plot + heatmap ---
        "sharing_on": "Sharing on {date}",
        "lines_suffix": " — lines (log)",
        "intraday_ylabel": "Energy [kWh per 15 min]",
        "hour_of_day": "Hour of day",
        "heatmap_cbar": "Mean kWh per 15-min interval",
        "heatmap_title_production": "Average total outgoing energy by hour × month",
        "heatmap_title_shared": "Average shared energy by hour × month",
        "heatmap_title_unmet": "Average unmet demand (from grid) by hour × month",
        "sel_day": "Day for the hourly plot",
        "sel_day_hint": "Or click a day in the daily plot.",
        "prev_day": "Previous day",
        "next_day": "Next day",
        "show_heatmap": "Show heatmap (hour × month)",
        "heat_metric": "Heatmap shows",
        "heat_production": "total outgoing (production)",
        "heat_shared": "shared",
        "heat_unmet": "unmet (from grid)",
        # --- phase 2: exact static method ---
        "keys": "Key [%]",
        "keys_hint": "Allocation keys: leave empty to estimate them from the report "
                     "(fitted so that today's 5-round EDC method reproduces it). "
                     "Keys act as ratios; 0 = member gets nothing.",
        "key_ph": "auto",
        "clear_keys": "Clear",
        "reserve": "Reserve for sale [%]",
        "recompute_title": "Exact static method (proposal)",
        "recompute_desc": "Every 15-min interval is recomputed with rozdel() from presna_staticka.py: "
                          "s_i = min(D_i, k_i · H), with the level H computed to the end. "
                          "The result is shown side by side with today's report.",
        "recompute_btn": "Recompute sharing with the exact static method",
        "part_no_recompute": "Recompute needs an all report (members' consumption is required).",
        "phase_fit": "Estimating keys from the report",
        "phase_compute": "Recomputing 15-min intervals",
        "phase_done": "Done",
        "phase_error": "Recompute failed",
        "col_edc": "Today — EDC static method (report)",
        "col_exact": "Exact static method (recomputed)",
        "vs_edc": "vs EDC",
        "timing_title": "Computation timing",
        "t_intervals": "15-min intervals evaluated",
        "t_breakdown": "night, P = 0: {a} · production covers everyone: {b} · level H computed: {c}",
        "t_total": "Total computation time (rozdel calls)",
        "t_per": "Time per 15-min interval",
        "t_per_full": "per interval with level H computed",
        "t_members": "Group members",
        "t_clock_cpu": "CPU time of the compute thread",
        "t_clock_wall": "wall-clock time",
        "t_fit": "Key estimation",
        "t_wall": "Whole job (incl. data preparation and key estimation)",
        "keys_used": "Keys used",
        "keys_est": "estimated from report",
        "keys_user": "entered",
        "keys_sum": "sum",
        "edc_check": "Check: today's EDC method with these keys reproduces the report in {pct} of intervals.",
        "stale": "Keys or reserve changed since the last recompute; press the button again.",
        "cmp_title": "Comparison per destination",
        "cmp_shared_edc": "Shared today [kWh]",
        "cmp_shared_exact": "Shared exact [kWh]",
        "cmp_delta": "Difference [kWh]",
        "cmp_delta_pct": "Difference",
        "cmp_cov": "Covered by sharing: today → exact",
        "cmp_key": "Key",
    },
    "cs": {
        "report_title": "Report sdílení elektřiny",
        "report_title_group": "Report sdílení elektřiny — skupina {group}",
        "total_by_flow_title": "Celková energie podle toku (skládaný)",
        "total_energy_xlabel": "Celková energie [kWh]",
        "daily_title": "Denní energie podle odběrného místa (skládaný)",
        "daily_title_lines": "Denní energie podle odběrného místa (čáry, log)",
        "daily_ylabel": "Denní energie [kWh]",
        "shared": "sdíleno",
        "unmet": "nepokryto",
        "unshared": "nesdíleno",
        "source": "Výroba",
        "total_source": "CELKEM VÝROBA",
        "total_destination": "CELKEM ODBĚR",
        "no_data": "Žádná data",
        "grid": "SÍŤ",
        "unshared_paren": "(nesdíleno)",
        "unmet_paren": "(nepokryto)",
        "destination": "Spotřeba",
        "source_a": "Výroba",
        "pie_title": "Sdíleno vs nesdílený přebytek",
        "pie_unshared_only": "nesdíleno",
        "pie_shared": "sdíleno",
        "pie_wasted": "mohlo být sdíleno",
        "pie_subtitle": "Zmařené = min(nesdíleno, nepokryto) za 15min interval",
        "pie_no_overlap": "Žádný souběžný překryv",
        "pie_union": "Celkem výroba: {total} kWh",
        "app_title": "Report sdílení SharEl",
        "upload_prompt": "Přetáhněte sem CSV export ze SharEl, nebo klikněte a vyberte soubor",
        "upload_hint": "Dílčí report (sloupce <ean>-<ean>) nebo úplný report (sloupce IN/OUT-<ean>-D/O). "
                       "Soubor se zpracuje v paměti a neukládá se.",
        "upload_other": "Nahrát jiný soubor",
        "loaded": "Načteno",
        "error": "Soubor se nepodařilo načíst",
        "session_lost": "Nahraná data už na serveru nejsou (server byl restartován). Nahrajte prosím soubor znovu.",
        "panel_dest": "Odběrná místa",
        "panel_dest_hint": "Zaškrtněte pro zahrnutí; napište název pro přejmenování.",
        "panel_source": "Výrobna",
        "panel_display": "Zobrazení",
        "panel_group": "Číslo skupiny sdílení",
        "panel_group_ph": "např. 0000018947",
        "all": "Vše",
        "none": "Nic",
        "yscale": "Osa y denního grafu",
        "linear": "lineární (skládaný)",
        "log": "logaritmická (čáry)",
        "show_unshared": "Zobrazit nesdíleno (přetok do sítě)",
        "show_unmet": "Zobrazit nepokryto (odběr ze sítě)",
        "language": "Jazyk",
        "info_title": "Obecné informace",
        "file": "Soubor",
        "report_type": "Typ reportu",
        "type_all": "úplný report (výroba + spotřeba)",
        "type_part": "dílčí report (jen sdílené dvojice)",
        "period": "Období",
        "days": "dní",
        "intervals": "15min intervalů",
        "producer": "EAN výrobny",
        "n_dest": "Odběrná místa",
        "selected_of": "vybráno {sel} z {n}",
        "peak": "Špička výroby",
        "best_day": "Nejlepší den sdílení",
        "days_sharing": "Dnů se sdílením",
        "kpi_production": "Výroba",
        "kpi_shared": "Nasdíleno",
        "kpi_wasted": "Mohlo být sdíleno",
        "kpi_unshareable": "Přetok nad spotřebou skupiny",
        "kpi_consumption": "Odběr členů",
        "kpi_from_grid": "Ze sítě",
        "of_production": "výroby",
        "of_consumption": "odběru",
        "kpi_note": "Hodnoty odpovídají výběru odběrných míst; výroba a přetok do sítě jsou celkové za výrobnu.",
        "table_title": "Podle odběrného místa",
        "col_name": "Název",
        "col_ean": "EAN",
        "col_consumption": "Odběr [kWh]",
        "col_shared": "Nasdíleno [kWh]",
        "col_unmet": "Nepokryto [kWh]",
        "col_coverage": "Pokryto sdílením",
        "col_share": "Podíl na sdílení",
        "col_data": "Data od",
        "col_data_pct": "Řádků s daty",
        "notes": "Poznámky k datům",
        "sharing_on": "Sdílení dne {date}",
        "lines_suffix": " — čáry (log)",
        "intraday_ylabel": "Energie [kWh za 15 min]",
        "hour_of_day": "Hodina dne",
        "heatmap_cbar": "Průměr kWh na 15min interval",
        "heatmap_title_production": "Průměrná dodaná energie podle hodiny × měsíce",
        "heatmap_title_shared": "Průměrná sdílená energie podle hodiny × měsíce",
        "heatmap_title_unmet": "Průměrný nepokrytý odběr (ze sítě) podle hodiny × měsíce",
        "sel_day": "Den pro hodinový graf",
        "sel_day_hint": "Nebo klikněte na den v denním grafu.",
        "prev_day": "Předchozí den",
        "next_day": "Další den",
        "show_heatmap": "Zobrazit teplotní mapu (hodina × měsíc)",
        "heat_metric": "Teplotní mapa ukazuje",
        "heat_production": "celkovou dodávku (výrobu)",
        "heat_shared": "sdílenou energii",
        "heat_unmet": "nepokrytý odběr (ze sítě)",
        "keys": "Klíč [%]",
        "keys_hint": "Alokační klíče: prázdné = odhad z reportu (dopočteno tak, aby dnešní "
                     "metoda EDC s 5 koly report reprodukovala). Klíče se berou jako poměry; "
                     "0 = člen nedostane nic.",
        "key_ph": "auto",
        "clear_keys": "Vymazat",
        "reserve": "Rezerva k prodeji [%]",
        "recompute_title": "Přesná statická metoda (návrh)",
        "recompute_desc": "Každá čtvrthodina se přepočítá funkcí rozdel() z presna_staticka.py: "
                          "s_i = min(D_i, k_i · H), hladina H dopočtená do konce. "
                          "Výsledek se zobrazí vedle dnešního reportu.",
        "recompute_btn": "Přepočítat sdílení přesnou statickou metodou",
        "part_no_recompute": "Přepočet potřebuje úplný report (odběry členů).",
        "phase_fit": "Odhad klíčů z reportu",
        "phase_compute": "Přepočet čtvrthodin",
        "phase_done": "Hotovo",
        "phase_error": "Přepočet selhal",
        "col_edc": "Dnes — statická metoda EDC (report)",
        "col_exact": "Přesná statická metoda (přepočet)",
        "vs_edc": "oproti EDC",
        "timing_title": "Měření výpočtu",
        "t_intervals": "Vyhodnocených čtvrthodin",
        "t_breakdown": "noc, P = 0: {a} · výroba stačí všem: {b} · výpočet hladiny H: {c}",
        "t_total": "Čas výpočtu celkem (volání rozdel)",
        "t_per": "Čas na jednu čtvrthodinu",
        "t_per_full": "na čtvrthodinu s výpočtem hladiny H",
        "t_members": "Členů skupiny",
        "t_clock_cpu": "CPU čas výpočetního vlákna",
        "t_clock_wall": "čas na hodinách",
        "t_fit": "Odhad klíčů",
        "t_wall": "Celá úloha (vč. přípravy dat a odhadu klíčů)",
        "keys_used": "Použité klíče",
        "keys_est": "odhad z reportu",
        "keys_user": "zadané",
        "keys_sum": "součet",
        "edc_check": "Kontrola: dnešní metoda EDC s těmito klíči reprodukuje report v {pct} čtvrthodin.",
        "stale": "Klíče nebo rezerva se od posledního přepočtu změnily; stiskněte tlačítko znovu.",
        "cmp_title": "Srovnání podle odběrného místa",
        "cmp_shared_edc": "Nasdíleno dnes [kWh]",
        "cmp_shared_exact": "Nasdíleno přesně [kWh]",
        "cmp_delta": "Rozdíl [kWh]",
        "cmp_delta_pct": "Rozdíl",
        "cmp_cov": "Pokryto sdílením: dnes → přesně",
        "cmp_key": "Klíč",
    },
}

CS_MONTH_ABBR = ("led", "úno", "bře", "dub", "kvě", "čvn",
                 "čvc", "srp", "zář", "říj", "lis", "pro")


def t(key: str, lang: str) -> str:
    table = STRINGS.get(lang, STRINGS["en"])
    return table.get(key, STRINGS["en"].get(key, key))


def month_label(ts: pd.Timestamp, lang: str) -> str:
    if lang == "cs":
        return f"{CS_MONTH_ABBR[ts.month - 1]} {ts.year}"
    return ts.strftime("%b %Y")


def fmt_num(x: float | None, lang: str, decimals: int = 0) -> str:
    """Thousands-separated number; Czech uses a thin space and decimal comma."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    s = f"{x:,.{decimals}f}"
    if lang == "cs":
        s = s.replace(",", " ").replace(".", ",")
    return s


def fmt_pct(x: float | None, lang: str, decimals: int = 1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{fmt_num(x, lang, decimals)} %"


def fmt_date(ts: pd.Timestamp | None, lang: str) -> str:
    if ts is None or pd.isna(ts):
        return "—"
    return ts.strftime("%d.%m.%Y" if lang == "cs" else "%Y-%m-%d")


def plotly_separators(lang: str) -> str:
    """Plotly ``layout.separators``: decimal char then thousands char."""
    return ", " if lang == "cs" else ".,"


def fmt_duration(seconds: float, lang: str) -> str:
    """Human duration: µs below 1 ms, ms below 1 s, else s."""
    if seconds < 1e-3:
        return f"{fmt_num(seconds * 1e6, lang, 2)}\u00a0µs"
    if seconds < 1:
        return f"{fmt_num(seconds * 1e3, lang, 1)}\u00a0ms"
    return f"{fmt_num(seconds, lang, 2)}\u00a0s"


def fmt_signed(x: float, lang: str, decimals: int = 1) -> str:
    sign = "+" if x > 0 else ("−" if x < 0 else "±")
    return f"{sign}{fmt_num(abs(x), lang, decimals)}"
