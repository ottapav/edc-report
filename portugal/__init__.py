"""Portugal: collective self-consumption (autoconsumo coletivo, ERSE Regulamento 2/2023).

* ``partilha``  – the ERSE fixed and proportional modes as E-REDES applies them, the exact
  method (the Czech exact static method on the same coefficients) and the sharing error.
* ``eredes``    – reading 15-min meter data and writing the per-pair coefficient files for
  the dynamic mode (partilha dinâmica).
* ``cli``       – command line: ``python -m portugal.cli data.csv coefficients.csv``.
* ``exemplo``   – synthetic test data.

All energies are integers in Wh (1 = 0.001 kWh).
"""
