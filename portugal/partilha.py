"""
Sharing in Portuguese collective self-consumption, per 15-min interval.

Modes (ERSE Regulamento n.º 2/2023, RAC)
---------------------------------------
* **Fixed coefficients** (art. 29) – what E-REDES does today with a fixed key. The energy for
  sharing E (sum of all injections, art. 35(4)) is imputed to each installation as
  ``coefficient × E`` (art. 34(1)(e)). Whatever exceeds its consumption is that
  installation's surplus (art. 34(1)(c)(ii)); nothing is passed on to the others.
  An installation with net injection in the interval cannot receive (art. 28(4)); its
  coefficient goes to the remaining installations in proportion to their coefficients
  (art. 29(3)).
* **Proportional to consumption** (art. 30) – shares ``E × C_i / ΣC``, capped at C_i. It always
  shares the maximum min(E, ΣC), but ignores the coefficients.
* **Exact** – the Czech exact static method (``presna_staticka.bazen``) on the same
  coefficients: ``s_i = min(C_i, c_i × H)`` with one common level H, so everything usable is
  shared and members still short get it in the ratio of their coefficients. In the dynamic
  mode (art. 32) the EGAC can submit this allocation as per-pair coefficients.

If the coefficients add up to less than 1, the fixed mode leaves the rest unallocated.
The exact method keeps that same part unallocated (``rezerva``) by default, so the comparison
measures only what the fixed rule loses.

Units: integers in Wh. Each interval is independent.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from presna_staticka import bazen  # noqa: E402

EPS = 1e-12


# ---------------------------------------------------------------------------
# One interval
# ---------------------------------------------------------------------------
def fixed_erse(injections: list[int], consumption: list[int], coef: list[float]) -> list[int]:
    """
    Energy each installation self-consumes from the collective under the fixed mode.

      injections   injection of every installation in the interval (0 if it does not inject)
      consumption  consumption of every installation (net 15-min balance, same order)
      coef         fixed coefficients (shares of E), sum ≤ 1

    Returns the shared energy per installation, Wh. The rest of E is surplus.
    """
    E = sum(injections)
    n = len(consumption)
    if E <= 0:
        return [0] * n
    total = sum(coef)
    # art. 28(4) + 29(3): installations injecting now are skipped, their share is spread
    # over the eligible ones in proportion to their coefficients
    eligible = [coef[i] if injections[i] <= 0 else 0.0 for i in range(n)]
    s_el = sum(eligible)
    if s_el <= EPS:
        return [0] * n
    scale = total / s_el
    # floor to whole Wh, so the shares never exceed E
    return [min(consumption[i], int(eligible[i] * scale * E + 1e-9)) for i in range(n)]


def proportional_erse(injections: list[int], consumption: list[int]) -> list[int]:
    """Art. 30: shares proportional to consumption, capped at it (largest remainders)."""
    E, C = sum(injections), sum(consumption)
    n = len(consumption)
    if E <= 0 or C <= 0:
        return [0] * n
    if C <= E:
        return list(consumption)
    exact = [E * c / C for c in consumption]
    s = [int(x) for x in exact]
    rest = E - sum(s)
    for i in sorted(range(n), key=lambda i: exact[i] - s[i], reverse=True)[:rest]:
        s[i] += 1
    return s


def exact(injections: list[int], consumption: list[int], coef: list[float],
          keep_unallocated: bool = True) -> tuple[list[int], list[list[int]]]:
    """
    Exact allocation on the same coefficients.

    Returns (shared per installation, matrix[producer][installation]) where the producers are
    all installations, in the same order; rows of non-injecting installations are zero.
    """
    n = len(consumption)
    reserve = max(0.0, 1.0 - sum(coef)) if keep_unallocated else 0.0
    # an injecting installation has no consumption in a net balance, so it cannot receive
    D = [0 if injections[i] > 0 else consumption[i] for i in range(n)]
    s, m = bazen(list(injections), D, list(coef), reserve)
    return s, m


# ---------------------------------------------------------------------------
# A period
# ---------------------------------------------------------------------------
@dataclass
class Comparison:
    """Totals over a period, Wh."""
    cpes: list[str]
    energy_for_sharing: int = 0      # Σ E
    maximum: int = 0                 # Σ min(E − unallocated part, Σ C of eligible)
    fixed: int = 0                   # shared by the fixed mode
    exact: int = 0                   # shared by the exact method
    proportional: int = 0            # shared by art. 30 (for reference)
    per_member_consumption: list[int] = field(default_factory=list)
    per_member_fixed: list[int] = field(default_factory=list)
    per_member_exact: list[int] = field(default_factory=list)
    intervals: int = 0
    intervals_with_loss: int = 0

    @property
    def lost(self) -> int:
        """Energy the fixed mode sends to the grid although members could use it."""
        return self.exact - self.fixed

    @property
    def pct_of_max(self) -> float:
        """Sharing error of the fixed mode, % of the maximum sharing."""
        return 100 * self.lost / self.exact if self.exact else 0.0

    @property
    def pct_of_energy(self) -> float:
        return 100 * self.lost / self.energy_for_sharing if self.energy_for_sharing else 0.0

    def as_dict(self) -> dict:
        kwh = lambda x: round(x / 1000, 3)  # noqa: E731
        return {
            "intervals": self.intervals,
            "intervals_with_loss": self.intervals_with_loss,
            "energy_for_sharing_kwh": kwh(self.energy_for_sharing),
            "maximum_kwh": kwh(self.maximum),
            "fixed_kwh": kwh(self.fixed),
            "exact_kwh": kwh(self.exact),
            "proportional_kwh": kwh(self.proportional),
            "lost_kwh": kwh(self.lost),
            "sharing_error_pct_of_max": round(self.pct_of_max, 2),
            "lost_pct_of_energy": round(self.pct_of_energy, 2),
            "members": [
                {"cpe": c, "consumption_kwh": kwh(d), "fixed_kwh": kwh(f),
                 "exact_kwh": kwh(e), "gain_kwh": kwh(e - f)}
                for c, d, f, e in zip(self.cpes, self.per_member_consumption,
                                      self.per_member_fixed, self.per_member_exact)],
        }


def compare(cpes: list[str], injections: list[list[int]], consumption: list[list[int]],
            coef: list[float], keep_unallocated: bool = True
            ) -> tuple[Comparison, list[list[list[int]]]]:
    """
    Compare the modes over a period.

      injections[t][i], consumption[t][i]  Wh per interval t and installation i
      coef[i]                              fixed coefficient of installation i

    Returns (Comparison, exact matrices per interval: [t][producer][installation]).
    """
    n = len(cpes)
    res = Comparison(cpes=cpes, per_member_consumption=[0] * n,
                     per_member_fixed=[0] * n, per_member_exact=[0] * n)
    reserve = max(0.0, 1.0 - sum(coef)) if keep_unallocated else 0.0
    matrices = []
    for J, C in zip(injections, consumption):
        E = sum(J)
        f = fixed_erse(J, C, coef)
        s, m = exact(J, C, coef, keep_unallocated)
        p = proportional_erse(J, [0 if J[i] > 0 else C[i] for i in range(n)])
        eligible_c = sum(C[i] for i in range(n) if J[i] <= 0 and coef[i] > 0)
        res.intervals += 1
        res.energy_for_sharing += E
        res.maximum += min(E - round(E * reserve), eligible_c) if E > 0 else 0
        res.fixed += sum(f)
        res.exact += sum(s)
        res.proportional += sum(p)
        if sum(s) > sum(f):
            res.intervals_with_loss += 1
        for i in range(n):
            res.per_member_consumption[i] += C[i]
            res.per_member_fixed[i] += f[i]
            res.per_member_exact[i] += s[i]
        matrices.append(m)
    return res, matrices
