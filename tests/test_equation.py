from __future__ import annotations

import pytest

from chemeq.core.equation import (
    balance_issues,
    element_counts,
    has_unreduced_coefficients,
    parse_equation,
    side_element_counts,
    try_parse,
)

GOOD = [
    "2H2 + O2 --点燃--> 2H2O",
    "2KClO3 --MnO2,Δ--> 2KCl + 3O2↑",
    "Fe + CuSO4 → FeSO4 + Cu",
    "NaOH + HCl → NaCl + H2O",
    "CaCO3 --高温--> CaO + CO2↑",
    "Na2CO3 + 2HCl → 2NaCl + H2O + CO2↑",
    "Ca(OH)2 + CO2 → CaCO3↓ + H2O",
    "2Na + 2H2O → 2NaOH + H2↑",
    "Cl2 + 2NaOH → NaCl + NaClO + H2O",
    "2FeCl3 + Fe → 3FeCl2",
    "2Al + 6HCl → 2AlCl3 + 3H2↑",
    "Fe2O3 + 6HCl → 2FeCl3 + 3H2O",
    "Cu + 2H2SO4(浓) --Δ--> CuSO4 + SO2↑ + 2H2O",
    "MnO2 + 4HCl(浓) --Δ--> MnCl2 + Cl2↑ + 2H2O",
    "2H2O2 --MnO2--> 2H2O + O2↑",
    "CH4 + 2O2 --点燃--> CO2 + 2H2O",
    "C2H5OH + 3O2 --点燃--> 2CO2 + 3H2O",
    "H+ + OH- → H2O",
    "Ag+ + Cl- → AgCl↓",
    "Ba2+ + SO4^2- → BaSO4↓",
    "Fe3+ + 3OH- → Fe(OH)3↓",
    "2H+ + CO3^2- → H2O + CO2↑",
    "Zn + 2H+ → Zn2+ + H2↑",
    "N2 + 3H2 ⇌ 2NH3",
    "2SO2 + O2 ⇌ 2SO3",
    "2Na2O2 + 2H2O → 4NaOH + O2↑",
    "2Na2O2 + 2CO2 → 2Na2CO3 + O2",
    "Al2O3 + 2NaOH → 2NaAlO2 + H2O",
    "Al(OH)3 + NaOH → NaAlO2 + 2H2O",
    "2Al + 2NaOH + 2H2O → 2NaAlO2 + 3H2↑",
    "4Fe(OH)2 + O2 + 2H2O → 4Fe(OH)3",
    "2Fe(OH)3 --Δ--> Fe2O3 + 3H2O",
    "Fe2O3 + 3CO --高温--> 2Fe + 3CO2",
    "3Fe + 4H2O(g) --高温--> Fe3O4 + 4H2",
    "2Mg + CO2 --点燃--> 2MgO + C",
    "2H2S + SO2 → 3S↓ + 2H2O",
    "Cu + 4HNO3(浓) → Cu(NO3)2 + 2NO2↑ + 2H2O",
    "3Cu + 8HNO3(稀) → 3Cu(NO3)2 + 2NO↑ + 4H2O",
    "CaCO3 + 2HCl → CaCl2 + H2O + CO2↑",
    "2NaHCO3 --Δ--> Na2CO3 + H2O + CO2↑",
    "NH4Cl --Δ--> NH3↑ + HCl↑",
    "2NH4Cl + Ca(OH)2 --Δ--> CaCl2 + 2NH3↑ + 2H2O",
    "4NH3 + 5O2 --催化剂,Δ--> 4NO + 6H2O",
    "2NO + O2 → 2NO2",
    "3NO2 + H2O → 2HNO3 + NO",
    "2H2O --通电--> 2H2↑ + O2↑",
    "2NaCl + 2H2O --通电--> 2NaOH + H2↑ + Cl2↑",
    "CuSO4·5H2O --Δ--> CuSO4 + 5H2O",
    "2Na + O2 --点燃--> Na2O2",
    "4Na + O2 → 2Na2O",
    "2Al2O3 --通电,冰晶石--> 4Al + 3O2↑",
    "2FeCl2 + Cl2 → 2FeCl3",
    "2KI + Cl2 → 2KCl + I2",
    "SO2 + 2H2S → 3S↓ + 2H2O",
    "2KMnO4 --Δ--> K2MnO4 + MnO2 + O2↑",
    "2HgO --Δ--> 2Hg + O2↑",
    "NaHCO3 + NaOH → Na2CO3 + H2O",
    "CaC2 + 2H2O → Ca(OH)2 + C2H2↑",
]


@pytest.mark.parametrize("raw", GOOD)
def test_good_equations_parse_and_balance(raw: str) -> None:
    eq = parse_equation(raw)
    assert eq.parse_error is None, eq.parse_error
    assert balance_issues(eq) == [], balance_issues(eq)


def test_charge_magnitude_and_caret() -> None:
    eq = parse_equation("Fe3+ + 3OH- → Fe(OH)3↓")
    assert eq.left[0].charge == 3
    assert eq.left[0].formula == "Fe"
    assert eq.left[1].charge == -1
    assert eq.left[1].coefficient == 3

    eq2 = parse_equation("Ba2+ + SO4^2- → BaSO4↓")
    assert eq2.left[0].charge == 2
    assert eq2.left[1].charge == -2
    assert eq2.left[1].formula == "SO4"


def test_hydrate_and_parentheses_counts() -> None:
    assert element_counts("CuSO4·5H2O") == {"Cu": 1, "S": 1, "O": 9, "H": 10}
    assert element_counts("Ca3(PO4)2") == {"Ca": 3, "P": 2, "O": 8}
    assert element_counts("(NH4)2SO4") == {"N": 2, "H": 8, "S": 1, "O": 4}
    assert element_counts("Fe(OH)3") == {"Fe": 1, "O": 3, "H": 3}


def test_conditions_and_states() -> None:
    eq = parse_equation("2KClO3 --MnO2,Δ--> 2KCl + 3O2↑")
    assert eq.conditions == ("MnO2", "加热")
    assert eq.right[1].state == "g"

    eq2 = parse_equation("Cu + 2H2SO4(浓) --Δ--> CuSO4 + SO2↑ + 2H2O")
    assert eq2.left[1].annotation == "浓"
    assert eq2.conditions == ("加热",)


def test_no_space_separator() -> None:
    eq = parse_equation("2H2+O2→2H2O")
    assert len(eq.left) == 2
    assert balance_issues(eq) == []


def test_bad_equations_are_reported() -> None:
    eq = try_parse("NaOH + HCl → NaCl + H2O2")
    assert eq.parse_error is None
    assert balance_issues(eq), "H2O2 版本应当不平衡"

    bad = try_parse("这不是一个方程式")
    assert bad.parse_error

    bad2 = try_parse("H2 + O2 →")
    assert bad2.parse_error


def test_side_counts() -> None:
    eq = parse_equation("2H2 + O2 → 2H2O")
    assert side_element_counts(eq.left) == {"H": 4, "O": 2}
    assert side_element_counts(eq.right) == {"H": 4, "O": 2}


def test_unreduced_coefficients() -> None:
    eq = parse_equation("4H2 + 2O2 → 4H2O")
    assert has_unreduced_coefficients(eq.left)
    assert has_unreduced_coefficients(eq.right)
    eq2 = parse_equation("2H2 + O2 → 2H2O")
    assert not has_unreduced_coefficients(eq2.left)


def test_thermochemical_and_fractional_coefficients() -> None:
    eq = parse_equation("H2(g) + 1/2O2(g) → H2O(l) ΔH = -285.8 kJ/mol")
    assert eq.parse_error is None
    assert eq.delta_h == -285.8
    assert eq.left[1].coefficient == 0.5
    assert balance_issues(eq) == []

    eq2 = parse_equation(
        "2H2(g) + O2(g) → 2H2O(l) ΔH = -571.6 kJ·mol-1"
    )
    assert eq2.delta_h == -571.6
    assert balance_issues(eq2) == []


def test_annotations_and_organic_condensed() -> None:
    eq = parse_equation("NaHCO3 + Ca(OH)2(过量) → CaCO3↓ + NaOH + H2O")
    assert eq.parse_error is None
    assert eq.left[1].annotation == "过量"
    assert balance_issues(eq) == []

    eq2 = parse_equation("CH3-CH2-OH + 3O2 --点燃--> 2CO2 + 3H2O")
    assert eq2.parse_error is None
    assert eq2.left[0].formula == "CH3CH2OH"
    assert balance_issues(eq2) == []

    eq3 = parse_equation("CH3COOH + C2H5OH ⇌ CH3COOC2H5 + H2O")
    assert eq3.parse_error is None
    assert balance_issues(eq3) == []


def test_condition_above_equals() -> None:
    eq = parse_equation("2NaHCO3 =△= Na2CO3 + H2O + CO2↑")
    assert eq.parse_error is None
    assert eq.conditions == ("加热",)
    assert balance_issues(eq) == []

