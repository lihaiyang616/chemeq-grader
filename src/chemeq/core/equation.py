"""Chemical equation parsing and validation.

The goal is deliberately modest: parse the notation used in Chinese high-school
chemistry worksheets, check element/charge balance, and expose a canonical form
so a deterministic grader can compare a student's answer with the answer key.

We do *not* try to be a full chemistry engine (no thermodynamics, no organic
structure parsing).  Anything outside the supported grammar is reported as a
parse error and sent to the teacher for review.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache


class ParseError(ValueError):
    """Raised when a chemical equation cannot be parsed."""


# All element symbols accepted in v0.1.  Keeping a whitelist catches common OCR
# confusions (e.g. "FI" for "F") instead of silently counting nonsense.
_ELEMENTS: frozenset[str] = frozenset(
    ["H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og"]
)

_STATE_ALIASES = {
    "g": "g",
    "gas": "g",
    "l": "l",
    "liquid": "l",
    "s": "s",
    "solid": "s",
    "aq": "aq",
    "aqueous": "aq",
}

_ANNOTATION_ALIASES = {
    "浓": "浓",
    "稀": "稀",
    "浓硫酸": "浓硫酸",
    "浓盐酸": "浓盐酸",
    "浓硝酸": "浓硝酸",
}

# Flattened docx/OCR text often loses superscripts: CO32- instead of CO3^2-.
# Only rewrite when the trailing digit matches the known charge of the ion.
_POLYATOMIC_CHARGES = {
    "CO3": 2,
    "SO4": 2,
    "SO3": 2,
    "PO4": 3,
    "Cr2O7": 2,
    "CrO4": 2,
    "C2O4": 2,
    "S2O3": 2,
    "SiO3": 2,
    "HPO4": 2,
    "MnO4": 1,
    "ClO": 1,
    "ClO3": 1,
    "ClO4": 1,
    "BrO3": 1,
    "IO3": 1,
    "AlO2": 1,
    "Fe(CN)6": 3,
    "Cu(NH3)4": 2,
    "Ag(NH3)2": 1,
}

_FULLWIDTH = str.maketrans(
    {
        "＋": "+",
        "－": "-",
        "＝": "=",
        "═": "=",
        "≒": "=",
        "（": "(",
        "）": ")",
        "［": "[",
        "］": "]",
        "，": ",",
        "、": ",",
        "；": ";",
        "：": ":",
        "　": " ",
        "０": "0",
        "１": "1",
        "２": "2",
        "３": "3",
        "４": "4",
        "５": "5",
        "６": "6",
        "７": "7",
        "８": "8",
        "９": "9",
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "⁺": "+",
        "⁻": "-",
        "²": "^2",
        "³": "^3",
        "⁴": "^4",
        "⁵": "^5",
        "⁶": "^6",
        "⁷": "^7",
        "⁸": "^8",
        "⁹": "^9",
        "¹": "^1",
        "⇋": "⇌",
        "⇄": "⇌",
        "⟶": "→",
        "➔": "→",
        "➜": "→",
        "•": "·",
        "∙": "·",
        "⋅": "·",
        "\u200b": "",
        "\ufeff": "",
    }
)

_COND_ARROW_RE = re.compile(
    r"^(?P<left>.+?)\s*--\s*(?P<cond>.*?)\s*(?:-->|—>|->|→)\s*(?P<right>.+)$"
)
_SIMPLE_ARROW_RE = re.compile(r"\s*(⇌|-->|—>|->|→|=>|=)\s*")
_DELTA_H_RE = re.compile(
    r"(?:Δ|△)\s*H\s*=\s*(?P<value>[+-]?\s*\d+(?:\.\d+)?)\s*"
    r"(?P<unit>kJ\s*(?:[·/]\s*mol(?:\s*\^?\s*-?1)?)?|J\s*(?:[·/]\s*mol)?)?",
    re.IGNORECASE,
)
_SUPERSCRIPT_MAP = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
}


def normalize_text(raw: str) -> str:
    """Normalise common OCR/student variants before parsing."""

    text = (raw or "").strip()
    text = text.translate(_FULLWIDTH)
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("<=>", "⇌").replace("<=>", "⇌")
    text = text.replace("⇋", "⇌").replace("⇄", "⇌")
    text = text.replace("⟶", "→").replace("➔", "→").replace("➜", "→")
    text = text.replace("—>", "->").replace("–>", "->").replace("−>", "->")
    # Superscript digits are almost always charges in this context (SO4²⁻).
    text = re.sub(
        r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)([⁺⁻])",
        lambda m: "^" + "".join(_SUPERSCRIPT_MAP[c] for c in m.group(1)) + m.group(2),
        text,
    )
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    # Docx authors often use a row of full-width '═' as an arrow.
    text = re.sub(r"={2,}", "=", text)
    # A condition written above an equals/arrow sign is often flattened to
    # "=△=" or "=点燃=" by the transcriber.  Turn it back into --cond-->.
    text = re.sub(
        r"=\s*(△|Δ|加热|点燃|高温|催化剂|通电|光照|MnO2|浓硫酸)\s*=",
        lambda m: " --" + ("加热" if m.group(1) in {"△", "Δ"} else m.group(1)) + "--> ",
        text,
    )
    # Organic condensed formulae often use hyphens as bonds: CH3-CH2-OH.
    # Remove only hyphens that sit between two formula characters (a hyphen
    # surrounded by spaces is a half-reaction minus sign and is left alone).
    text = re.sub(r"(?<=[A-Za-z0-9])-(?=[A-Za-z])", "", text)
    # A '+' immediately followed by the next species is a separator, not a
    # charge: "2H2+O2" -> "2H2 + O2".  Charges are followed by whitespace, '+',
    # end of string (handled by the lookahead) or a closing bracket.
    text = re.sub(r"(?<=[^\s+])\+(?=[A-Z0-9(\[])", " + ", text)
    return text.strip()


def _parse_coefficient(text: str, i: int) -> tuple[float, int]:
    """Parse an integer, decimal or fractional coefficient (e.g. 1/2)."""

    n = len(text)
    if i < n and text[i] in "½¼¾":
        return {"½": 0.5, "¼": 0.25, "¾": 0.75}[text[i]], i + 1
    j = i
    while j < n and text[j].isdigit():
        j += 1
    if j < n and text[j] == ".":
        j += 1
        while j < n and text[j].isdigit():
            j += 1
    if j > i and j < n and text[j] == "/":
        k = j + 1
        while k < n and text[k].isdigit():
            k += 1
        if k > j + 1:
            value = float(text[i:j]) / float(text[j + 1 : k])
            if value <= 0:
                raise ParseError("系数必须为正数")
            return value, k
    if j > i:
        value = float(text[i:j])
        if value <= 0:
            raise ParseError("系数必须为正数")
        return value, j
    return 1.0, i


def _parse_number(text: str, i: int) -> tuple[int, int]:
    start = i
    while i < len(text) and text[i].isdigit():
        i += 1
    if i == start:
        return 1, i
    value = int(text[start:i])
    if value <= 0:
        raise ParseError("下标/系数必须为正整数")
    return value, i


@lru_cache(maxsize=2048)
def element_counts(formula: str) -> dict[str, int]:
    """Return element counts for a formula, including parentheses/hydrates."""

    if formula == "e":
        return {}

    i = 0
    n = len(formula)

    def parse_group(stop: str | None = None) -> dict[str, int]:
        nonlocal i
        counts: Counter[str] = Counter()
        while i < n:
            c = formula[i]
            if stop is not None and c == stop:
                break
            if c in "([":
                close = ")" if c == "(" else "]"
                i += 1
                sub = parse_group(close)
                if i >= n or formula[i] != close:
                    raise ParseError(f"括号不匹配：{formula}")
                i += 1
                mult, i = _parse_number(formula, i)
                for el, num in sub.items():
                    counts[el] += num * mult
            elif c == "·":
                i += 1
                mult, i = _parse_number(formula, i)
                sub = parse_group(None)
                for el, num in sub.items():
                    counts[el] += num * mult
                break
            elif c.isupper():
                el = c
                i += 1
                if i < n and formula[i].islower():
                    el += formula[i]
                    i += 1
                if el not in _ELEMENTS:
                    raise ParseError(f"无效元素符号：{el}")
                mult, i = _parse_number(formula, i)
                counts[el] += mult
            elif c.islower():
                raise ParseError(f"小写字母开头/位置错误：{formula}")
            elif c.isdigit():
                raise ParseError(f"数字位置错误：{formula}")
            else:
                raise ParseError(f"无法识别的化学式字符 {c!r}：{formula}")
        return dict(counts)

    result = parse_group()
    if i != n:
        raise ParseError(f"化学式解析未完成：{formula}")
    if not result:
        raise ParseError(f"空化学式：{formula}")
    return result


@dataclass(frozen=True)
class Species:
    formula: str
    coefficient: float = 1.0
    charge: int = 0
    state: str | None = None
    annotation: str | None = None
    raw: str = ""

    @property
    def elements(self) -> dict[str, int]:
        return element_counts(self.formula)

    @property
    def element_key(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self.elements.items()))

    @property
    def match_key(self) -> tuple[tuple[tuple[str, int], ...], int]:
        """Species identity ignoring state/annotation (compared separately)."""

        return (self.element_key, self.charge)

    @property
    def key(self) -> tuple[tuple[tuple[str, int], ...], int, str | None, str | None]:
        return (self.element_key, self.charge, self.state, self.annotation)

    def format(self) -> str:
        prefix = ""
        if abs(self.coefficient - 1.0) > 1e-9:
            if abs(self.coefficient - round(self.coefficient)) < 1e-9:
                prefix = str(int(round(self.coefficient)))
            else:
                prefix = str(Fraction(self.coefficient).limit_denominator(20))
        charge = ""
        if self.charge:
            if abs(self.charge) == 1:
                charge = "+" if self.charge > 0 else "-"
            else:
                charge = f"^{abs(self.charge)}{'+' if self.charge > 0 else '-'}"
        state = ""
        if self.state == "g":
            state = "↑"
        elif self.state == "s":
            state = "↓"
        elif self.state:
            state = f"({self.state})"
        annotation = f"({self.annotation})" if self.annotation else ""
        return f"{prefix}{self.formula}{charge}{annotation}{state}"


@dataclass
class Equation:
    raw: str
    left: list[Species]
    right: list[Species]
    arrow: str = "→"
    conditions: tuple[str, ...] = ()
    delta_h: float | None = None
    delta_h_text: str = ""
    parse_error: str | None = None

    @property
    def reversible(self) -> bool:
        return self.arrow == "⇌"

    @property
    def is_ionic(self) -> bool:
        return any(sp.charge != 0 for sp in [*self.left, *self.right])

    @property
    def is_thermochemical(self) -> bool:
        return self.delta_h is not None

    def format(self) -> str:
        left = " + ".join(sp.format() for sp in self.left)
        right = " + ".join(sp.format() for sp in self.right)
        if self.conditions:
            body = f"{left} --{','.join(self.conditions)}--> {right}"
        else:
            body = f"{left} {self.arrow} {right}"
        if self.delta_h is not None:
            body += f"  ΔH = {self.delta_h:g} kJ/mol"
        return body


def _is_annotation_at(text: str, i: int) -> bool:
    """Is text[i] the start of a trailing state/annotation such as '(aq)'?"""

    if i >= len(text) or text[i] != "(":
        return False
    close = text.find(")", i)
    if close == -1:
        return False
    token = text[i + 1 : close].strip()
    lower = token.lower()
    if lower in _STATE_ALIASES or token in _ANNOTATION_ALIASES:
        return True
    # Chinese annotations used in Chinese worksheets: (少量), (过量), (溶液), (熔融).
    return any("\u4e00" <= ch <= "\u9fff" for ch in token)


def _split_charge_magnitude(formula: str) -> tuple[int, str]:
    """Split 'Fe3' into (3, 'Fe') and 'CO32' into (2, 'CO3').

    A single element followed by a number before a charge sign is almost always
    a charge magnitude (Fe3+, Ca2+, Al3+).  Polyatomic ions keep the digit as a
    subscript unless the base matches a known ion whose charge equals the digit
    (flattened docx text: CO32- -> CO3^2-).  NH4+ stays NH4+.
    """

    m = re.fullmatch(r"(.+?)(\d+)", formula)
    if m:
        base, magnitude = m.group(1), int(m.group(2))
        if 2 <= magnitude <= 8 and _POLYATOMIC_CHARGES.get(base) == magnitude:
            return magnitude, base
        if re.fullmatch(r"[A-Z][a-z]?", base) and 2 <= magnitude <= 8:
            return magnitude, base
    return 1, formula


def _parse_species(text: str, i: int) -> tuple[Species, int]:
    start = i
    n = len(text)
    coefficient, i = _parse_coefficient(text, i)

    formula_start = i
    while i < n:
        c = text[i]
        if c in "+-^":
            break
        if c in "↑↓":
            break
        if c.isspace():
            break
        if c == "(" and i > formula_start and _is_annotation_at(text, i):
            break
        if c.isalpha() or c.isdigit() or c in "()[]·":
            i += 1
            continue
        raise ParseError(f"无法识别字符 {c!r}：{text}")
    formula = text[formula_start:i]
    if not formula:
        raise ParseError(f"缺少化学式：{text}")
    formula = formula.replace("*", "·")

    charge = 0
    if i < n and text[i] == "^":
        i += 1
        mag_start = i
        while i < n and text[i].isdigit():
            i += 1
        magnitude = int(text[mag_start:i]) if i > mag_start else 1
        if i >= n or text[i] not in "+-":
            raise ParseError(f"电荷缺少正负号：{text}")
        charge = magnitude if text[i] == "+" else -magnitude
        i += 1
    elif i < n and text[i] in "+-":
        sign = 1 if text[i] == "+" else -1
        i += 1
        magnitude, formula = _split_charge_magnitude(formula)
        charge = sign * magnitude

    state: str | None = None
    annotation: str | None = None
    while i < n:
        if text[i] == "(":
            close = text.find(")", i)
            if close == -1:
                raise ParseError(f"括号未闭合：{text}")
            token = text[i + 1 : close].strip()
            lower = token.lower()
            if lower in _STATE_ALIASES:
                state = _STATE_ALIASES[lower]
            elif token in _ANNOTATION_ALIASES or any(
                "\u4e00" <= ch <= "\u9fff" for ch in token
            ):
                annotation = token
            else:
                raise ParseError(f"无法识别的状态/标注：({token})")
            i = close + 1
            continue
        if text[i] in "↑↓":
            state = "g" if text[i] == "↑" else "s"
            i += 1
            continue
        break

    if not formula:
        raise ParseError(f"空化学式：{text}")
    if formula == "e":
        element_counts("e")  # validates the special case
    else:
        element_counts(formula)
    if abs(charge) > 8:
        raise ParseError(f"电荷异常：{charge}")
    return (
        Species(
            formula=formula,
            coefficient=coefficient,
            charge=charge,
            state=state,
            annotation=annotation,
            raw=text[start:i],
        ),
        i,
    )


def parse_side(text: str) -> list[Species]:
    text = text.strip()
    if not text:
        raise ParseError("方程式一侧为空")
    species: list[Species] = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        sp, i = _parse_species(text, i)
        species.append(sp)
        while i < n and text[i].isspace():
            i += 1
        if i < n:
            if text[i] != "+":
                raise ParseError(f"化学式后有多余字符：{text[i:i + 12]!r}")
            i += 1
            # A trailing separator is a parse error; do not silently drop it.
            j = i
            while j < n and text[j].isspace():
                j += 1
            if j >= n:
                raise ParseError("方程式以 '+' 结尾")
            i = j
    if not species:
        raise ParseError("方程式一侧没有物质")
    return species


def _parse_conditions(cond: str) -> tuple[str, ...]:
    if not cond.strip():
        return ()
    parts: list[str] = []
    for chunk in re.split(r"[,，、;；/]+", cond):
        chunk = chunk.strip()
        if not chunk:
            continue
        chunk = chunk.replace("△", "Δ").strip()
        if chunk in {"Δ", "加热", "受热"}:
            chunk = "加热"
        parts.append(chunk)
    return tuple(sorted(dict.fromkeys(parts)))


def _split_equation(text: str) -> tuple[str, str, str, str]:
    m = _COND_ARROW_RE.match(text)
    if m:
        return m.group("left").strip(), m.group("cond").strip(), m.group("right").strip(), "→"
    m = _SIMPLE_ARROW_RE.search(text)
    if not m:
        raise ParseError("找不到反应箭头（→ / ⇌ / -->）")
    left = text[: m.start()].strip()
    right = text[m.end() :].strip()
    if not left or not right:
        raise ParseError("箭头两侧不能为空")
    raw_arrow = m.group(1)
    if raw_arrow in {"⇌"}:
        arrow = "⇌"
    elif raw_arrow == "=":
        arrow = "="
    else:
        arrow = "→"
    return left, "", right, arrow


def _extract_delta_h(text: str) -> tuple[str, float | None, str]:
    """Pull a trailing thermochemical ΔH term out of the equation body."""

    match = _DELTA_H_RE.search(text)
    if not match:
        return text, None, ""
    value = float(match.group("value").replace(" ", ""))
    unit = (match.group("unit") or "kJ/mol").replace(" ", "")
    if unit.upper().startswith("J") and not unit.upper().startswith("KJ"):
        value = value / 1000.0
        unit = "kJ/mol"
    body = (text[: match.start()] + " " + text[match.end() :]).strip()
    return body, value, unit


def parse_equation(raw: str) -> Equation:
    text = normalize_text(raw)
    if not text:
        raise ParseError("空方程式")
    text, delta_h, delta_h_unit = _extract_delta_h(text)
    left_text, cond_text, right_text, arrow = _split_equation(text)
    left = parse_side(left_text)
    right = parse_side(right_text)
    return Equation(
        raw=raw,
        left=left,
        right=right,
        arrow=arrow,
        conditions=_parse_conditions(cond_text),
        delta_h=delta_h,
        delta_h_text=delta_h_unit,
    )


def try_parse(raw: str) -> Equation:
    """Parse without raising; keep the error on the Equation object."""

    try:
        return parse_equation(raw)
    except ParseError as exc:
        return Equation(raw=raw, left=[], right=[], parse_error=str(exc))


@dataclass(frozen=True)
class BalanceIssue:
    kind: str  # "element" | "charge"
    element: str = ""
    left: float | int = 0
    right: float | int = 0

    def describe(self) -> str:
        if self.kind == "charge":
            return f"电荷不守恒：左 {self.left:+g}，右 {self.right:+g}"
        return f"{self.element} 不守恒：左 {self.left:g}，右 {self.right:g}"


def side_element_counts(side: Iterable[Species]) -> Counter[str]:
    total: Counter[str] = Counter()
    for sp in side:
        for el, num in sp.elements.items():
            total[el] += sp.coefficient * num
    return total


def side_charge(side: Iterable[Species]) -> int:
    return sum(sp.coefficient * sp.charge for sp in side)


def balance_issues(eq: Equation) -> list[BalanceIssue]:
    if eq.parse_error:
        return []
    left = side_element_counts(eq.left)
    right = side_element_counts(eq.right)
    issues: list[BalanceIssue] = []
    for el in sorted(set(left) | set(right)):
        if abs(float(left[el]) - float(right[el])) > 1e-9:
            issues.append(BalanceIssue("element", el, left[el], right[el]))
    lc, rc = side_charge(eq.left), side_charge(eq.right)
    if abs(float(lc) - float(rc)) > 1e-9:
        issues.append(BalanceIssue("charge", "", lc, rc))
    return issues


def equation_signature(eq: Equation) -> tuple:
    """Canonical, hashable representation used for exact matching."""

    def side_sig(side: Iterable[Species]) -> tuple:
        return tuple(sorted((sp.key, sp.coefficient) for sp in side))

    return (side_sig(eq.left), eq.arrow == "⇌", side_sig(eq.right), eq.conditions)


def species_side_key(side: Iterable[Species]) -> Counter:
    """Species multiset ignoring coefficients and states."""

    return Counter(sp.match_key for sp in side)


def normalized_coefficients(side: Iterable[Species]) -> tuple:
    """Coefficients divided by their gcd, paired with species identities."""

    items = list(side)
    if not items:
        return ()
    if not all(abs(float(sp.coefficient) - round(float(sp.coefficient))) < 1e-9 for sp in items):
        # Fractional coefficients (thermochemical equations) are compared as-is.
        return tuple(sorted((sp.match_key, sp.coefficient) for sp in items))
    gcd = 0
    for sp in items:
        gcd = _gcd(gcd, int(round(sp.coefficient)))
    gcd = gcd or 1
    return tuple(sorted((sp.match_key, int(round(sp.coefficient)) // gcd) for sp in items))


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return abs(a)


def has_unreduced_coefficients(side: Iterable[Species]) -> bool:
    items = list(side)
    if not items:
        return False
    if not all(abs(float(sp.coefficient) - round(float(sp.coefficient))) < 1e-9 for sp in items):
        return False
    gcd = 0
    for sp in items:
        gcd = _gcd(gcd, int(round(sp.coefficient)))
    return gcd > 1


def equation_has_unreduced_coefficients(eq: Equation) -> bool:
    """True when every coefficient on both sides shares a common factor."""

    items = [*eq.left, *eq.right]
    if len(items) < 2:
        return False
    if not all(abs(float(sp.coefficient) - round(float(sp.coefficient))) < 1e-9 for sp in items):
        return False
    gcd = 0
    for sp in items:
        gcd = _gcd(gcd, int(round(sp.coefficient)))
    return gcd > 1
