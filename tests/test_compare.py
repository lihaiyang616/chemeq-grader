from __future__ import annotations

from chemeq.core.compare import (
    ERROR_ARROW,
    ERROR_BLANK,
    ERROR_COEFF,
    ERROR_CONDITION_MISSING,
    ERROR_DELTA_H_MISSING,
    ERROR_DELTA_H_WRONG,
    ERROR_PRODUCT,
    ERROR_STATE_MISSING,
    ERROR_TYPE,
    ERROR_UNBALANCED,
    ERROR_UNPARSABLE,
    grade_equation,
)

KEY = "2H2 + O2 --点燃--> 2H2O"


def test_exact_correct() -> None:
    out = grade_equation(KEY, [KEY])
    assert out.verdict == "correct"
    assert out.score == 2.0
    assert out.error_types == []


def test_missing_condition_is_partial() -> None:
    out = grade_equation("2H2 + O2 → 2H2O", [KEY])
    assert out.verdict == "partial"
    # 老师要求“只要出错都不给分”，所以部分错误也是 0 分。
    assert out.score == 0.0
    assert ERROR_CONDITION_MISSING in out.error_types


def test_missing_state_is_partial() -> None:
    key = "CaCO3 --高温--> CaO + CO2↑"
    out = grade_equation("CaCO3 --高温--> CaO + CO2", [key])
    assert out.verdict == "partial"
    assert ERROR_STATE_MISSING in out.error_types


def test_wrong_product_is_wrong() -> None:
    key = "NaOH + HCl → NaCl + H2O"
    out = grade_equation("NaOH + HCl → NaCl + H2O2", [key])
    assert out.verdict == "wrong"
    assert out.score == 0.0
    assert ERROR_PRODUCT in out.error_types
    assert ERROR_UNBALANCED in out.error_types


def test_unreduced_coefficients_are_partial() -> None:
    key = "2H2 + O2 → 2H2O"
    out = grade_equation("4H2 + 2O2 → 4H2O", [key])
    assert out.verdict == "partial"
    assert ERROR_COEFF in out.error_types


def test_reversible_arrow_mismatch() -> None:
    key = "N2 + 3H2 ⇌ 2NH3"
    out = grade_equation("N2 + 3H2 → 2NH3", [key])
    assert out.verdict == "partial"
    assert ERROR_ARROW in out.error_types


def test_ionic_vs_chemical_is_partial_not_uncertain() -> None:
    key = "NaOH + HCl → NaCl + H2O"
    out = grade_equation("H+ + OH- → H2O", [key])
    assert out.verdict == "partial"
    assert ERROR_TYPE in out.error_types


def test_alternative_key_is_accepted() -> None:
    keys = ["N2 + 3H2 → 2NH3", "N2 + 3H2 ⇌ 2NH3"]
    out = grade_equation("N2 + 3H2 → 2NH3", keys)
    assert out.verdict == "correct"


def test_blank_answer() -> None:
    out = grade_equation("", [KEY])
    assert out.verdict == "wrong"
    assert out.score == 0.0
    assert ERROR_BLANK in out.error_types


def test_unparsable_answer() -> None:
    out = grade_equation("这不是方程式", [KEY])
    assert out.verdict == "uncertain"
    assert out.score is None
    assert ERROR_UNPARSABLE in out.error_types


def test_no_key_only_checks_balance() -> None:
    out = grade_equation("2H2 + O2 → 2H2O", None)
    assert out.verdict == "correct"
    assert out.balance_only is True
    assert out.needs_review is True

    bad = grade_equation("H2 + O2 → H2O", None)
    assert bad.verdict == "wrong"
    assert ERROR_UNBALANCED in bad.error_types


def test_low_confidence_forces_review() -> None:
    out = grade_equation(KEY, [KEY], transcription_confidence=0.4)
    assert out.verdict == "uncertain"
    assert out.score is None
    assert out.needs_review is True


def test_require_flags_can_be_relaxed() -> None:
    out = grade_equation(
        "2H2 + O2 → 2H2O",
        [KEY],
        require_conditions=False,
    )
    assert out.verdict == "correct"

    out2 = grade_equation(
        "CaCO3 --高温--> CaO + CO2",
        ["CaCO3 --高温--> CaO + CO2↑"],
        require_states=False,
    )
    assert out2.verdict == "correct"


TC_KEY = "H2(g) + 1/2O2(g) → H2O(l) ΔH = -285.8 kJ/mol"


def test_thermochemical_exact() -> None:
    out = grade_equation(TC_KEY, [TC_KEY])
    assert out.verdict == "correct"
    assert out.score == 2.0


def test_thermochemical_wrong_delta_h() -> None:
    out = grade_equation(
        "H2(g) + 1/2O2(g) → H2O(l) ΔH = -241.8 kJ/mol",
        [TC_KEY],
    )
    assert out.verdict == "partial"
    assert out.score == 0.0
    assert ERROR_DELTA_H_WRONG in out.error_types


def test_thermochemical_missing_delta_h() -> None:
    out = grade_equation("H2(g) + 1/2O2(g) → H2O(l)", [TC_KEY])
    assert out.verdict == "partial"
    assert out.score == 0.0
    assert ERROR_DELTA_H_MISSING in out.error_types

