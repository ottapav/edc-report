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
        "others_shared": "Shared to unselected members",
        "others_short": "unselected",
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
        "pie_title": "Where the production went",
        "pie_unshared_only": "unshared",
        "pie_shared": "shared to selected",
        "pie_others": "shared to unselected members",
        "pie_wasted": "could have been shared",
        "pie_subtitle": "Could have been shared = min(unshared, unmet of selected) per 15-min interval",
        "pie_no_overlap": "No concurrent overlap",
        "pie_union": "Total source: {total} kWh",
        # --- web UI ---
        "app_title": "EDC sharing report",
        "upload_prompt": "Drag and drop the CSV report from edc-cr.cz here, or click to choose a file",
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
        # --- phase 4: keys at upload, jobs, theme ---
        "job_cancelled": "The computation was cancelled (another file was uploaded, or the page stopped responding). Start it again.",
        "job_timeout": "The computation took too long and was stopped. Try a smaller report.",
        "job_lost": "The computation was lost (the server restarted or went to sleep) together with the uploaded data. Upload the file again.",
        "queued": "Waiting for a free slot (another computation is running)",
        "fit_title": "Allocation keys estimated from the report",
        "fit_summary": "The approximate static method (EDC) with {rounds} reproduces the report in {pct} of 15-min "
                       "intervals with these keys{other}. Estimated in {secs}.",
        "fit_other": " ({rounds}: {pct})",
        "rounds_1": "1 round",
        "rounds_5": "5 rounds",
        "fit_check": "Check the keys marked with a range: the report fits every value in it "
                     "equally well. Keys act as ratios in the exact method.",
        "fit_low": "The estimated keys reproduce less than 95 % of intervals; please check "
                   "them against your contract.",
        "key_range": "{lo}–{hi} %",
        "key_lower": "≥ {lo} % (always covered)",
        "key_nodata": "no data (key 0)",
        "key_zero": "0 % (receives nothing; below {hi} % cannot be told apart)",
        "fit_rough": "Rough estimate: the time limit was reached, so the keys are the best found so far and may not be optimal. Check them against your contract.",
        "theme_toggle": "Light / dark mode",
        "others": "Others ({n} places)",

        "sharing_on": "Sharing on {date}",
        "intraday_ylabel": "Energy [kWh per 15 min]",
        "hour_of_day": "Hour of day",
        "heatmap_cbar": "Mean kWh per 15-min interval",
        "heatmap_title_production": "Average total production by hour × month",
        "heatmap_title_consumption": "Average total consumption of selected members by hour × month",
        "heatmap_title_shared": "Average shared energy by hour × month",
        "sel_day": "Day for the hourly plot",
        "sel_day_hint": "Or click a day in the daily plot.",
        "prev_day": "Previous day",
        "next_day": "Next day",
        "heat_metric": "Heatmap shows",
        "heat_production": "total production",
        "heat_consumption": "total consumption (selected members)",
        "heat_shared": "shared",
        # --- phase 2: exact static method ---
        "keys": "Key [%]",
        "keys_hint": "Allocation keys are estimated from the report right after upload "
                     "(so that the approximate static method reproduces it); correct them before the "
                     "recompute. Keys act as ratios; 0 = member gets nothing.",
        "key_ph": "auto",
        "clear_keys": "Estimate",
        "reserve": "Reserve for sale [%]",
        "recompute_title": "Exact static method (proposal)",
        "recompute_desc": "Every 15-min interval is recomputed with rozdel() from presna_staticka.py: "
                          "s_i = min(D_i, k_i · H), with the level H computed to the end. "
                          "The result is shown side by side with the approximate static method (the EDC report).",
        "recompute_btn": "Recompute sharing with the exact static method",
        "part_no_recompute": "Recompute needs an all report (members' consumption is required).",
        "phase_fit": "Estimating keys from the report",
        "phase_compute": "Recomputing 15-min intervals",
        "phase_done": "Done",
        "phase_error": "Recompute failed",
        "col_edc": "Approximate static method (EDC report)",
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
        "t_wall": "Whole job (incl. data preparation)",
        "keys_used": "Keys used",
        "keys_est": "estimated from report",
        "keys_user": "entered",
        "keys_sum": "sum",
        "edc_check": "Check: the approximate static method (EDC, {rounds}) with these keys reproduces the report in {pct} of intervals.",
        "loss_title": "Sharing error of the approximate static method (EDC)",
        "loss_text": "The exact static method shares {max} kWh (the maximum). The approximate static method (EDC) shared {edc} kWh and sent {kwh} kWh to the grid that members could have used.",
        "loss_none": "No sharing error: the approximate static method (EDC) shares as much as the exact one.",
        "stale": "Keys or reserve changed since the last recompute; press the button again.",
        "cmp_title": "Comparison per destination",
        "cmp_shared_edc": "Shared approx. [kWh]",
        "cmp_shared_exact": "Shared exact [kWh]",
        "cmp_delta_pct": "EDC error [%]",
        "cmp_error_hint": "EDC error = (Shared exact − Shared approx.) ÷ Shared exact: the part of the sharing the exact method makes possible that the approximate method (EDC) missed. Per member it is relative to that member's exact sharing; the Σ row is the whole group and equals the sharing error in the box above.",
        "cmp_cov": "Covered by sharing: approx. → exact",
        "cmp_key": "Key",
    },
    "cs": {
        "report_title": "Report sdílení elektřiny",
        "report_title_group": "Report sdílení elektřiny — skupina {group}",
        "total_by_flow_title": "Celková energie podle toku (skládaný)",
        "total_energy_xlabel": "Celková energie [kWh]",
        "daily_title": "Denní energie podle odběrného místa (skládaný)",
        "others_shared": "Sdíleno nevybraným místům",
        "others_short": "nevybraným",
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
        "pie_title": "Kam šla výroba",
        "pie_unshared_only": "nesdíleno",
        "pie_shared": "sdíleno vybraným",
        "pie_others": "sdíleno nevybraným místům",
        "pie_wasted": "mohlo být sdíleno",
        "pie_subtitle": "Mohlo být sdíleno = min(nesdíleno, nepokryto vybraných) za 15min interval",
        "pie_no_overlap": "Žádný souběžný překryv",
        "pie_union": "Celkem výroba: {total} kWh",
        "app_title": "Report sdílení EDC",
        "upload_prompt": "Přetáhněte sem CSV report z portálu edc-cr.cz, nebo klikněte a vyberte soubor",
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
        "intraday_ylabel": "Energie [kWh za 15 min]",
        "hour_of_day": "Hodina dne",
        "heatmap_cbar": "Průměr kWh na 15min interval",
        "heatmap_title_production": "Průměrná celková výroba podle hodiny × měsíce",
        "heatmap_title_consumption": "Průměrný celkový odběr vybraných míst podle hodiny × měsíce",
        "heatmap_title_shared": "Průměrná sdílená energie podle hodiny × měsíce",
        "sel_day": "Den pro hodinový graf",
        "sel_day_hint": "Nebo klikněte na den v denním grafu.",
        "prev_day": "Předchozí den",
        "next_day": "Další den",
        "heat_metric": "Teplotní mapa ukazuje",
        "heat_production": "celkovou výrobu",
        "heat_consumption": "celkový odběr (vybraná místa)",
        "heat_shared": "sdílenou energii",
        "job_cancelled": "Výpočet byl zrušen (byl nahrán jiný soubor, nebo stránka přestala odpovídat). Spusťte ho znovu.",
        "job_timeout": "Výpočet trval příliš dlouho a byl zastaven. Zkuste menší report.",
        "job_lost": "Výpočet se ztratil i s nahranými daty (server se restartoval nebo uspal). Nahrajte soubor znovu.",
        "queued": "Čeká na volné místo (běží jiný výpočet)",
        "fit_title": "Alokační klíče odhadnuté z reportu",
        "fit_summary": "Přibližná statická metoda (EDC) s {rounds} reprodukuje s těmito klíči report v {pct} "
                       "čtvrthodin{other}. Odhad trval {secs}.",
        "fit_other": " ({rounds}: {pct})",
        "rounds_1": "1 kolem",
        "rounds_5": "5 koly",
        "fit_check": "Zkontrolujte klíče s vyznačeným rozsahem: report vysvětluje každou "
                     "hodnotu v něm stejně dobře. V přesné metodě se klíče berou jako poměry.",
        "fit_low": "Odhadnuté klíče reprodukují méně než 95 % intervalů; zkontrolujte je "
                   "prosím podle smlouvy.",
        "key_range": "{lo}–{hi} %",
        "key_lower": "≥ {lo} % (vždy pokryt)",
        "key_nodata": "bez dat (klíč 0)",
        "key_zero": "0 % (nic nedostává; pod {hi} % nelze rozlišit)",
        "fit_rough": "Hrubý odhad: byl dosažen časový limit, klíče jsou nejlepší dosud nalezené a nemusí být optimální. Zkontrolujte je podle smlouvy.",
        "theme_toggle": "Světlý / tmavý režim",
        "others": "Ostatní ({n} míst)",
        "keys": "Klíč [%]",
        "keys_hint": "Alokační klíče se odhadnou z reportu hned po nahrání (tak, aby je "
                     "přibližná statická metoda reprodukovala); před přepočtem je můžete opravit. "
                     "Klíče se berou jako poměry; 0 = člen nedostane nic.",
        "key_ph": "auto",
        "clear_keys": "Odhad",
        "reserve": "Rezerva k prodeji [%]",
        "recompute_title": "Přesná statická metoda (návrh)",
        "recompute_desc": "Každá čtvrthodina se přepočítá funkcí rozdel() z presna_staticka.py: "
                          "s_i = min(D_i, k_i · H), hladina H dopočtená do konce. "
                          "Výsledek se zobrazí vedle přibližné statické metody (reportu EDC).",
        "recompute_btn": "Přepočítat sdílení přesnou statickou metodou",
        "part_no_recompute": "Přepočet potřebuje úplný report (odběry členů).",
        "phase_fit": "Odhad klíčů z reportu",
        "phase_compute": "Přepočet čtvrthodin",
        "phase_done": "Hotovo",
        "phase_error": "Přepočet selhal",
        "col_edc": "Přibližná statická metoda (report EDC)",
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
        "t_wall": "Celá úloha (vč. přípravy dat)",
        "keys_used": "Použité klíče",
        "keys_est": "odhad z reportu",
        "keys_user": "zadané",
        "keys_sum": "součet",
        "edc_check": "Kontrola: přibližná statická metoda (EDC, {rounds}) s těmito klíči reprodukuje report v {pct} čtvrthodin.",
        "loss_title": "Chyba sdílení přibližné statické metody (EDC)",
        "loss_text": "Přesná statická metoda sdílí {max} kWh (maximum). Přibližná statická metoda (EDC) sdílela {edc} kWh a {kwh} kWh poslala do sítě, ačkoli je členové mohli využít.",
        "loss_none": "Žádná chyba sdílení: přibližná statická metoda (EDC) sdílí stejně jako přesná.",
        "stale": "Klíče nebo rezerva se od posledního přepočtu změnily; stiskněte tlačítko znovu.",
        "cmp_title": "Srovnání podle odběrného místa",
        "cmp_shared_edc": "Nasdíleno přibl. [kWh]",
        "cmp_shared_exact": "Nasdíleno přesně [kWh]",
        "cmp_delta_pct": "Chyba EDC [%]",
        "cmp_error_hint": "Chyba EDC = (Nasdíleno přesně − Nasdíleno přibl.) ÷ Nasdíleno přesně: jaká část sdílení, které přesná metoda umožní, přibližné metodě (EDC) unikla. U člena se počítá z jeho přesného sdílení; řádek Σ je celá skupina a odpovídá chybě sdílení v boxu nahoře.",
        "cmp_cov": "Pokryto sdílením: přibl. → přesně",
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
