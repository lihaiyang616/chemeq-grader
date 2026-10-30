"""Deterministic grading of a transcribed equation against an answer key."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .equation import (
    Equation,
    balance_issues,
    equation_has_unreduced_coefficients,
    normalized_coefficients,
    species_side_key,
    try_parse,
)

ERROR_UNBALANCED = "未配平"
ERROR_CHARGE = "电荷不守恒"
ERROR_REACTANT = "反应物错误"
ERROR_PRODUCT = "产物错误"
ERROR_CONDITION_MISSING = "条件缺失"
ERROR_CONDITION_WRONG = "条件错误"
ERROR_STATE_MISSING = "状态符号缺失"
ERROR_STATE_WRONG = "状态符号错误"
ERROR_COEFF = "系数未约简"
ERROR_COEFF_WRONG = "系数错误"
ERROR_ARROW = "箭头类型错误"
ERROR_TYPE = "方程式类型不符"
ERROR_DELTA_H_MISSING = "ΔH 缺失"
ERROR_DELTA_H_WRONG = "ΔH 错误"
ERROR_UNREADABLE = "无法识别"
ERROR_UNPARSABLE = "无法解析"
ERROR_DIFFERENT = "与标准答案不同（可能合理）"
ERROR_BLANK = "未作答"
ERROR_KEY_INVALID = "标准答案无法解析"


@dataclass
class GradeOutcome:
    verdict: str  # correct | partial | wrong | uncertain
    score: float | None
    error_types: list[str] = field(default_factory=list)
    detail: str = ""
    needs_review: bool = False
    matched_key: str = ""
    student_canonical: str = ""
    key_canonical: str = ""
    balance_only: bool = False

    @property
    def ok(self) -> bool:
        return self.verdict == "correct"


def _score_for(verdict: str, max_score: float, strict: bool = True) -> float | None:
    if verdict == "correct":
        return round(float(max_score), 2)
    if verdict == "partial":
        return 0.0 if strict else round(float(max_score) / 2, 2)
    if verdict == "wrong":
        return 0.0
    return None


def _fmt(value: float | int) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _species_diff(student_side, key_side) -> tuple[list[str], list[str]]:
    student_counter: Counter = species_side_key(student_side)
    key_counter: Counter = species_side_key(key_side)
    missing = key_counter - student_counter
    extra = student_counter - key_counter

    def label(counter: Counter) -> list[str]:
        labels: list[str] = []
        for key, count in counter.items():
            # Find a readable formula for this identity.
            candidates = [sp.formula for sp in [*key_side, *student_side] if sp.match_key == key]
            formula = candidates[0] if candidates else "?"
            labels.extend([formula] * count)
        return labels

    return label(missing), label(extra)


def _state_issues(
    student: Equation, key: Equation, require_states: bool
) -> tuple[list[str], list[str]]:
    if not require_states:
        return [], []
    errors: list[str] = []
    details: list[str] = []
    key_species = [*key.left, *key.right]
    student_species = [*student.left, *student.right]
    for key_sp in key_species:
        if key_sp.state is None and key_sp.annotation is None:
            continue
        # 'aq' is often omitted in Chinese high-school equations; do not punish
        # it unless the teacher explicitly marks the question as strict.
        if key_sp.state == "aq" and key_sp.annotation is None:
            continue
        matches = [sp for sp in student_species if sp.match_key == key_sp.match_key]
        if not matches:
            continue
        student_sp = matches[0]
        if key_sp.annotation and not student_sp.annotation:
            errors.append(ERROR_STATE_MISSING)
            details.append(f"{key_sp.formula} 缺少浓度标注（{key_sp.annotation}）")
        elif key_sp.annotation and student_sp.annotation != key_sp.annotation:
            errors.append(ERROR_STATE_WRONG)
            details.append(
                f"{key_sp.formula} 浓度标注错误：应为 {key_sp.annotation}，写了 {student_sp.annotation}"
            )
        if key_sp.state and not student_sp.state:
            errors.append(ERROR_STATE_MISSING)
            details.append(f"{key_sp.formula} 缺少状态符号（{key_sp.state}）")
        elif key_sp.state and student_sp.state != key_sp.state:
            errors.append(ERROR_STATE_WRONG)
            details.append(
                f"{key_sp.formula} 状态符号错误：应为 {key_sp.state}，写了 {student_sp.state}"
            )
    return list(dict.fromkeys(errors)), list(dict.fromkeys(details))


def _condition_issues(
    student: Equation, key: Equation, require_conditions: bool
) -> tuple[list[str], list[str]]:
    if not require_conditions:
        return [], []
    missing = set(key.conditions) - set(student.conditions)
    extra = set(student.conditions) - set(key.conditions)
    errors: list[str] = []
    details: list[str] = []
    if missing:
        errors.append(ERROR_CONDITION_MISSING)
        details.append(f"缺少条件：{'、'.join(sorted(missing))}")
    if extra:
        errors.append(ERROR_CONDITION_WRONG)
        details.append(f"多余/错误条件：{'、'.join(sorted(extra))}")
    return errors, details


def _compare(
    student: Equation,
    key: Equation,
    max_score: float,
    *,
    require_conditions: bool = True,
    require_states: bool = True,
    strict: bool = True,
) -> GradeOutcome:
    errors: list[str] = []
    details: list[str] = []

    student_left, key_left = species_side_key(student.left), species_side_key(key.left)
    student_right, key_right = species_side_key(student.right), species_side_key(key.right)
    species_match = student_left == key_left and student_right == key_right

    if not species_match:
        miss_l, extra_l = _species_diff(student.left, key.left)
        miss_r, extra_r = _species_diff(student.right, key.right)
        if miss_l or extra_l:
            errors.append(ERROR_REACTANT)
            if miss_l:
                details.append(f"反应物缺少：{'、'.join(miss_l)}")
            if extra_l:
                details.append(f"反应物多出：{'、'.join(extra_l)}")
        if miss_r or extra_r:
            errors.append(ERROR_PRODUCT)
            if miss_r:
                details.append(f"产物缺少：{'、'.join(miss_r)}")
            if extra_r:
                details.append(f"产物多出：{'、'.join(extra_r)}")

    issues = balance_issues(student)
    elements = [issue for issue in issues if issue.kind == "element"]
    charges = [issue for issue in issues if issue.kind == "charge"]
    if elements:
        errors.append(ERROR_UNBALANCED)
        details.extend(issue.describe() for issue in elements)
    if charges:
        errors.append(ERROR_CHARGE)
        details.extend(issue.describe() for issue in charges)
    balanced = not issues

    if key.is_ionic != student.is_ionic:
        errors.append(ERROR_TYPE)
        details.append(
            "标准答案是离子方程式，学生写成了化学方程式"
            if key.is_ionic
            else "标准答案是化学方程式，学生写成了离子方程式"
        )

    if key.reversible != student.reversible:
        errors.append(ERROR_ARROW)
        details.append("可逆/不可逆箭头不一致")

    cond_errors, cond_details = _condition_issues(student, key, require_conditions)
    state_errors, state_details = _state_issues(student, key, require_states)
    errors.extend(cond_errors)
    errors.extend(state_errors)
    details.extend(cond_details)
    details.extend(state_details)

    if key.delta_h is not None or student.delta_h is not None:
        if key.delta_h is None:
            errors.append(ERROR_DELTA_H_WRONG)
            details.append("标准答案没有 ΔH，学生多写了")
        elif student.delta_h is None:
            errors.append(ERROR_DELTA_H_MISSING)
            details.append(f"缺少 ΔH（应为 {key.delta_h:g} kJ/mol）")
        elif abs(float(key.delta_h) - float(student.delta_h)) > 0.1:
            errors.append(ERROR_DELTA_H_WRONG)
            details.append(f"ΔH 错误：应为 {key.delta_h:g}，写了 {student.delta_h:g}")

    if species_match and balanced:
        if key.is_thermochemical or student.is_thermochemical:
            # Thermochemical coefficients are meaningful (ΔH scales with them),
            # so compare them directly instead of reducing to the simplest ratio.
            s_coeff = tuple(sorted((sp.match_key, sp.coefficient) for sp in student.left)) + tuple(
                sorted((sp.match_key, sp.coefficient) for sp in student.right)
            )
            k_coeff = tuple(sorted((sp.match_key, sp.coefficient) for sp in key.left)) + tuple(
                sorted((sp.match_key, sp.coefficient) for sp in key.right)
            )
            if s_coeff != k_coeff:
                errors.append(ERROR_COEFF_WRONG)
                details.append("系数与标准答案不一致（热化学方程式的系数影响 ΔH）")
        else:
            s_norm = (
                normalized_coefficients(student.left),
                normalized_coefficients(student.right),
            )
            k_norm = (normalized_coefficients(key.left), normalized_coefficients(key.right))
            if s_norm != k_norm:
                errors.append(ERROR_COEFF_WRONG)
                details.append("系数与标准答案不一致")
            elif equation_has_unreduced_coefficients(student):
                errors.append(ERROR_COEFF)
                details.append("系数未约成最简整数比")

    # Decide the verdict.  Species errors are hard; balance errors with the right
    # species get partial credit; balanced but chemically different answers are
    # sent to the teacher instead of being called wrong.
    hard_species = ERROR_REACTANT in errors or ERROR_PRODUCT in errors
    if hard_species:
        if balanced and ERROR_TYPE not in errors:
            return GradeOutcome(
                verdict="uncertain",
                score=None,
                error_types=[ERROR_DIFFERENT, *errors],
                detail="；".join([ERROR_DIFFERENT, *details]),
                needs_review=True,
                student_canonical=student.format(),
                key_canonical=key.format(),
            )
        verdict = "partial" if balanced and ERROR_TYPE in errors else "wrong"
    elif elements or charges:
        verdict = "partial" if species_match else "wrong"
    elif errors:
        verdict = "partial"
    else:
        verdict = "correct"

    # Remove duplicates while preserving order.
    unique_errors = list(dict.fromkeys(errors))
    detail = "；".join(details)
    if verdict == "correct":
        detail = "配平、条件、状态与标准答案一致"
    return GradeOutcome(
        verdict=verdict,
        score=_score_for(verdict, max_score, strict),
        error_types=unique_errors,
        detail=detail,
        needs_review=verdict != "correct",
        student_canonical=student.format(),
        key_canonical=key.format(),
    )


def grade_equation(
    student_raw: str,
    key_raws: list[str] | tuple[str, ...] | None,
    *,
    max_score: float = 2.0,
    transcription_confidence: float = 1.0,
    require_conditions: bool = True,
    require_states: bool = True,
    strict: bool = True,
) -> GradeOutcome:
    """Grade one transcribed answer against one or more accepted answers."""

    raw = (student_raw or "").strip()
    key_list = [k for k in (key_raws or []) if (k or "").strip()]
    if not raw:
        return GradeOutcome(
            verdict="wrong",
            score=0.0,
            error_types=[ERROR_BLANK],
            detail="未识别到该题作答，请老师确认",
            needs_review=True,
            balance_only=not key_list,
        )

    student = try_parse(raw)
    if student.parse_error:
        return GradeOutcome(
            verdict="uncertain",
            score=None,
            error_types=[ERROR_UNPARSABLE],
            detail=f"无法解析学生答案：{student.parse_error}",
            needs_review=True,
            student_canonical="",
        )

    keys = [try_parse(k) for k in key_list]
    valid_keys = [k for k in keys if k.parse_error is None]

    if not key_list:
        # No answer key: only check balance/charge.  Do not pretend this is a
        # full grade; flag it so the teacher can add the key and re-grade.
        issues = balance_issues(student)
        if issues:
            error = ERROR_CHARGE if all(i.kind == "charge" for i in issues) else ERROR_UNBALANCED
            return GradeOutcome(
                verdict="wrong",
                score=0.0,
                error_types=[error],
                detail="；".join(i.describe() for i in issues),
                needs_review=True,
                balance_only=True,
                student_canonical=student.format(),
            )
        return GradeOutcome(
            verdict="correct",
            score=round(float(max_score), 2),
            error_types=[],
            detail="未提供标准答案：仅检查了配平/电荷，条件与状态未判",
            needs_review=True,
            balance_only=True,
            student_canonical=student.format(),
        )

    if not valid_keys:
        return GradeOutcome(
            verdict="uncertain",
            score=None,
            error_types=[ERROR_KEY_INVALID],
            detail="标准答案无法解析，请先在作业设置里修正标准答案",
            needs_review=True,
            student_canonical=student.format(),
        )

    outcomes: list[GradeOutcome] = []
    for key in valid_keys:
        outcome = _compare(
            student,
            key,
            max_score,
            require_conditions=require_conditions,
            require_states=require_states,
            strict=strict,
        )
        outcome.matched_key = key.raw
        outcomes.append(outcome)

    # Prefer an exact match; otherwise partial before uncertain before wrong,
    # and fewer errors before more errors.  This supports multiple accepted
    # answers for the same question.
    rank = {"correct": 0, "partial": 1, "uncertain": 2, "wrong": 3}
    outcomes.sort(key=lambda o: (rank.get(o.verdict, 9), len(o.error_types)))
    best = outcomes[0]
    if transcription_confidence < 0.7:
        best.needs_review = True
        best.detail = (best.detail + "；" if best.detail else "") + "转写置信度偏低，请核对原图"
        if best.verdict == "correct":
            best.verdict = "uncertain"
            best.score = None
            best.error_types = [*best.error_types, ERROR_UNREADABLE]
    return best
