#!/usr/bin/env python3
"""dimcheck: offline dimensional-analysis calculator and formula checker.

Every quantity is an exact Fraction in SI base units tagged with its
dimension (exponents of m, kg, s, A, K, mol, cd). Conversions never round,
and unit mistakes are caught before a number is trusted. Standard library only.
"""

from __future__ import annotations

import argparse
import decimal
import difflib
import functools
import json
import re
import sys
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

BASE_UNITS = ("kg", "m", "s", "A", "K", "mol", "cd")  # order sets how dim_str prints
ZERO_DIM = (0,) * len(BASE_UNITS)
DEFAULT_DIGITS = 6
DEFAULT_REL_TOL = Fraction("1e-9")
NAME = r"[A-Za-z_]\w*"

# Exact SI values for the constants a formula file can use without redefining.
CONSTANTS = {
    "c0": "299792458 m/s",
    "g0": "9.80665 m/s^2",
    "hP": "6.62607015e-34 J*s",
    "kB": "1.380649e-23 J/K",
    "NA": "6.02214076e23 1/mol",
    "qe": "1.602176634e-19 C",
    "Rgas": "8.314462618 J/(mol*K)",
    "Ggrav": "6.67430e-11 m^3/(kg*s^2)",
}

# Non-base units, written as expressions so they are resolved from first principles.
DERIVED_UNITS = {
    # length
    "in": "0.0254 m", "ft": "12 in", "yd": "3 ft", "mi": "5280 ft", "nmi": "1852 m",
    "mil": "0.001 in", "fathom": "6 ft", "angstrom": "1e-10 m",
    "au": "149597870700 m", "ly": "9460730472580800 m",
    # time
    "min": "60 s", "h": "60 min", "d": "24 h", "wk": "7 d", "yr": "365.25 d",
    # mass
    "g": "0.001 kg", "t": "1000 kg", "lb": "0.45359237 kg", "oz": "lb/16",
    "gr": "lb/7000", "st": "14 lb",
    # area and volume
    "ha": "10000 m^2", "acre": "43560 ft^2", "L": "0.001 m^3", "l": "L",
    "gal": "231 in^3", "qt": "gal/4", "pt": "gal/8", "floz": "gal/128",
    # speed
    "mph": "mi/h", "kn": "nmi/h", "kph": "km/h",
    # force, pressure, energy, power
    "N": "kg*m/s^2", "kgf": "9.80665 N", "lbf": "lb*9.80665 m/s^2",
    "Pa": "N/m^2", "bar": "100000 Pa", "atm": "101325 Pa", "torr": "atm/760",
    "psi": "lbf/in^2",
    "J": "N*m", "cal": "4.184 J", "kcal": "1000 cal", "Wh": "3600 J",
    "kWh": "3600000 J", "eV": "1.602176634e-19 J", "BTU": "1055.05585262 J",
    "W": "J/s", "hp": "745.6998715822702 W",
    # electrical and frequency
    "Hz": "1/s", "C": "A*s", "V": "W/A", "ohm": "V/A", "F": "C/V", "S": "A/V",
    "H": "V*s/A", "T": "V*s/m^2",
    # dimensionless ratios
    "pct": "0.01", "ppm": "1e-6", "ppb": "1e-9",
}

_PREFIX_EXPONENTS = {
    "Y": 24, "Z": 21, "E": 18, "P": 15, "T": 12, "G": 9, "M": 6, "k": 3, "h": 2,
    "da": 1, "d": -1, "c": -2, "m": -3, "u": -6, "n": -9, "p": -12, "f": -15,
    "a": -18, "z": -21, "y": -24,
}
PREFIXES = {prefix: Fraction(10) ** exp for prefix, exp in _PREFIX_EXPONENTS.items()}
PREFIXABLE = frozenset({
    "m", "g", "s", "A", "K", "mol", "cd", "N", "Pa", "J", "W", "Hz", "C", "V", "F",
    "ohm", "S", "L", "eV", "bar", "T", "H",
})
# Coherent SI derived units, tried in order when naming a dimension.
NAMED_DERIVED = ("N", "Pa", "J", "W", "C", "V", "F", "ohm", "S", "H", "T")
ALL_UNIT_NAMES = tuple(sorted(set(BASE_UNITS) | set(DERIVED_UNITS)))


class DimError(ValueError):
    """A problem with the user's input, reported as a plain message."""


@dataclass(frozen=True)
class Quantity:
    """A value in SI base units. value is None when only the dimension is known."""

    value: Optional[Fraction]
    dim: tuple


@dataclass(frozen=True)
class Entry:
    """The outcome of one line of a formula file."""

    line: int
    kind: str  # unit, define, symbol, show, check, error
    status: str  # ok, fail, error
    message: str


# ---------------------------------------------------------------- dimensions

def _unit_dim(index):
    dim = [0] * len(BASE_UNITS)
    dim[index] = 1
    return tuple(dim)


def dim_str(dim):
    """Render a dimension vector as base-unit powers, e.g. kg*m/s^2."""
    num, den = [], []
    for sym, exp in zip(BASE_UNITS, dim):
        if exp > 0:
            num.append(sym if exp == 1 else f"{sym}^{exp}")
        elif exp < 0:
            den.append(sym if exp == -1 else f"{sym}^{-exp}")
    if not num and not den:
        return "1"
    text = "*".join(num) or "1"
    return text + ("/" + "*".join(den) if den else "")


def _dims(a, b, sign=1):
    return tuple(x + sign * y for x, y in zip(a, b))


# ---------------------------------------------------------------- arithmetic

def _combine(a, b, fn):
    return None if a is None or b is None else fn(a, b)


def _mul(a, b):
    return Quantity(_combine(a.value, b.value, lambda x, y: x * y), _dims(a.dim, b.dim))


def _div(a, b):
    if b.value == 0:
        raise DimError("division by zero")
    return Quantity(_combine(a.value, b.value, lambda x, y: x / y), _dims(a.dim, b.dim, -1))


def _pow(q, n):
    if q.value is not None and n < 0 and q.value == 0:
        raise DimError("division by zero")
    value = None if q.value is None else q.value ** n
    return Quantity(value, tuple(x * n for x in q.dim))


def _neg(q):
    return Quantity(None if q.value is None else -q.value, q.dim)


def _add(a, b, subtract=False):
    if a.dim != b.dim:
        op = "-" if subtract else "+"
        raise DimError(f"dimension mismatch in '{op}': {_dim_label(a.dim)} vs {_dim_label(b.dim)}")
    fn = (lambda x, y: x - y) if subtract else (lambda x, y: x + y)
    return Quantity(_combine(a.value, b.value, fn), a.dim)


# ---------------------------------------------------------------- tokenizer and parser

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    r"|(?P<name>[A-Za-z_]\w*)|(?P<op>\*\*|[-+*/^()]))"
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    col: int


def tokenize(text):
    text = text.replace("µ", "u")  # micro sign -> plain u
    tokens, pos = [], 0
    while True:
        match = _TOKEN.match(text, pos)
        if match is None:
            rest = text[pos:]
            if not rest.strip():
                return tokens
            col = len(text) - len(rest.lstrip()) + 1
            raise DimError(f"unexpected {rest.strip()[0]!r} at column {col}")
        pos = match.end()
        kind = match.lastgroup
        tokens.append(Token(kind, match.group(kind), match.start(kind) + 1))


class _Parser:
    """Recursive-descent parser: +,- < *,/ and juxtaposition < ^ < unary < atoms."""

    def __init__(self, text, resolve):
        self.tokens = tokenize(text)
        self.pos = 0
        self.resolve = resolve

    def parse(self):
        if not self.tokens:
            raise DimError("empty expression")
        result = self._expr()
        extra = self._peek()
        if extra is not None:
            raise DimError(f"unexpected {extra.text!r} at column {extra.col}")
        return result

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self):
        tok = self._peek()
        if tok is None:
            raise DimError("unexpected end of expression")
        self.pos += 1
        return tok

    def _is_op(self, *ops):
        tok = self._peek()
        return tok is not None and tok.kind == "op" and tok.text in ops

    def _starts_factor(self):
        tok = self._peek()
        return tok is not None and (tok.kind in ("num", "name") or (tok.kind == "op" and tok.text == "("))

    def _expr(self):
        q = self._term()
        while self._is_op("+", "-"):
            op = self._take().text
            q = _add(q, self._term(), subtract=(op == "-"))
        return q

    def _term(self):
        q = self._power()
        while True:
            if self._is_op("*", "/"):
                op = self._take().text
                right = self._power()
                q = _mul(q, right) if op == "*" else _div(q, right)
            elif self._starts_factor():  # juxtaposition, e.g. "2 m" or "kg m"
                q = _mul(q, self._power())
            else:
                return q

    def _power(self):
        q = self._unary()
        if self._is_op("^", "**"):
            self._take()
            q = _pow(q, self._exponent())
        return q

    def _unary(self):
        if self._is_op("-"):
            self._take()
            return _neg(self._unary())
        if self._is_op("+"):
            self._take()
            return self._unary()
        return self._atom()

    def _exponent(self):
        sign = 1
        if self._is_op("-"):
            self._take()
            sign = -1
        elif self._is_op("+"):
            self._take()
        tok = self._take()
        if tok.kind != "num" or not tok.text.isdigit():
            raise DimError(f"exponent must be a whole number at column {tok.col}")
        return sign * int(tok.text)

    def _atom(self):
        tok = self._take()
        if tok.kind == "num":
            return Quantity(Fraction(tok.text), ZERO_DIM)
        if tok.kind == "name":
            return self.resolve(tok.text)
        if tok.kind == "op" and tok.text == "(":
            q = self._expr()
            if not self._is_op(")"):
                raise DimError(f"missing ')' for '(' at column {tok.col}")
            self._take()
            return q
        raise DimError(f"unexpected {tok.text!r} at column {tok.col}")


def evaluate(text, resolve: Callable[[str], Quantity]):
    return _Parser(text, resolve).parse()


# ---------------------------------------------------------------- built-in units

def _unknown_message(name, candidates):
    close = difflib.get_close_matches(name, list(candidates), n=3, cutoff=0.6)
    hint = f"; did you mean {', '.join(repr(c) for c in close)}?" if close else ""
    return f"unknown name {name!r}{hint}"


@functools.lru_cache(maxsize=None)
def builtin_unit(name):
    """Return the Quantity for a built-in unit name (value = one unit in SI), or None."""
    if name in BASE_UNITS:
        return Quantity(Fraction(1), _unit_dim(BASE_UNITS.index(name)))
    if name in DERIVED_UNITS:
        return evaluate(DERIVED_UNITS[name], builtin_resolve)
    for prefix in sorted(PREFIXES, key=len, reverse=True):
        rest = name[len(prefix):]
        if name.startswith(prefix) and rest in PREFIXABLE:
            base = builtin_unit(rest)
            return Quantity(base.value * PREFIXES[prefix], base.dim)
    return None


def builtin_resolve(name):
    q = builtin_unit(name)
    if q is None:
        raise DimError(_unknown_message(name, ALL_UNIT_NAMES))
    return q


def canonical_unit(dim):
    """Name a dimension with a coherent SI name when one exists, else base powers."""
    if dim == ZERO_DIM:
        return ""
    for name in NAMED_DERIVED:
        if builtin_unit(name).dim == dim:
            return name
    return dim_str(dim)


def _dim_label(dim):
    return canonical_unit(dim) or "dimensionless"


# ---------------------------------------------------------------- formatting

def format_number(value, digits=DEFAULT_DIGITS, exact=False):
    """Round to `digits` significant figures, or print the exact fraction."""
    if exact:
        if value.denominator == 1:
            return str(value.numerator)
        return f"{value.numerator}/{value.denominator}"
    ctx = decimal.Context(prec=digits)
    dec = ctx.divide(decimal.Decimal(value.numerator), decimal.Decimal(value.denominator))
    dec = dec.normalize(ctx)
    if -6 <= dec.adjusted() <= 15:
        return format(dec, "f")
    return format(dec, "e")


def describe(q, digits=DEFAULT_DIGITS):
    unit = canonical_unit(q.dim)
    if q.value is None:
        return f"(symbolic) {unit}".rstrip()
    number = format_number(q.value, digits)
    return f"{number} {unit}" if unit else number


# ---------------------------------------------------------------- formula files

class Context:
    """Variables and user units for one run. Built-in units are shared."""

    def __init__(self):
        self.variables = {name: evaluate(text, builtin_resolve) for name, text in CONSTANTS.items()}
        self.user_units = {}

    def resolve(self, name):
        for table in (self.variables, self.user_units):
            if name in table:
                return table[name]
        q = builtin_unit(name)
        if q is None:
            candidates = [*self.variables, *self.user_units, *ALL_UNIT_NAMES]
            raise DimError(_unknown_message(name, candidates))
        return q

    def evaluate(self, text):
        return evaluate(text, self.resolve)


def _require_new_name(ctx, name):
    if name in ctx.variables or name in ctx.user_units:
        raise DimError(f"{name!r} is already defined")
    if builtin_unit(name) is not None:
        raise DimError(f"{name!r} is a built-in unit; choose another name")


def _convert(q, target):
    if q.dim != target.dim:
        raise DimError(f"cannot convert {_dim_label(q.dim)} to {_dim_label(target.dim)}")
    if q.value is None or target.value is None:
        raise DimError("cannot convert a value that is not set")
    if target.value == 0:
        raise DimError("target unit has zero size")
    return q.value / target.value


def _close(a, b, rel_tol):
    if a == b:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b))


def _statement(ctx, text, line, rel_tol, digits):
    if m := re.fullmatch(rf"unit\s+({NAME})\s*=\s*(.+)", text):
        name, expr = m.groups()
        _require_new_name(ctx, name)
        q = ctx.evaluate(expr)
        if q.value is None or q.value == 0:
            raise DimError(f"unit {name!r} needs a known, non-zero value")
        ctx.user_units[name] = q
        return Entry(line, "unit", "ok", f"{name} = {describe(q, digits)}")

    if m := re.fullmatch(r"show\s+(.+?)(?:\s*->\s*(.+))?", text):
        expr, target_text = m.groups()
        q = ctx.evaluate(expr)
        if target_text is None:
            return Entry(line, "show", "ok", f"{expr.strip()} = {describe(q, digits)}")
        number = _convert(q, ctx.evaluate(target_text))
        return Entry(line, "show", "ok",
                     f"{expr.strip()} = {format_number(number, digits)} {target_text.strip()}")

    if m := re.fullmatch(r"check\s+(.+?)\s*=\s*(.+)", text):
        lhs, rhs = ctx.evaluate(m[1]), ctx.evaluate(m[2])
        if lhs.dim != rhs.dim:
            return Entry(line, "check", "fail",
                         f"dimension mismatch: {_dim_label(lhs.dim)} vs {_dim_label(rhs.dim)}")
        if lhs.value is None or rhs.value is None:
            return Entry(line, "check", "ok",
                         f"dimensions agree ({_dim_label(lhs.dim)}); values not compared")
        if not _close(lhs.value, rhs.value, rel_tol):
            return Entry(line, "check", "fail",
                         f"value mismatch: {describe(lhs, digits)} vs {describe(rhs, digits)}")
        return Entry(line, "check", "ok", f"{describe(lhs, digits)} = {describe(rhs, digits)}")

    if m := re.fullmatch(rf"({NAME})\s*:\s*(.+)", text):
        name, expr = m.groups()
        _require_new_name(ctx, name)
        dim = ctx.evaluate(expr).dim
        ctx.variables[name] = Quantity(None, dim)
        return Entry(line, "symbol", "ok", f"{name} : {_dim_label(dim)} (value not set)")

    if m := re.fullmatch(rf"({NAME})\s*=\s*(.+)", text):
        name, expr = m.groups()
        _require_new_name(ctx, name)
        q = ctx.evaluate(expr)
        ctx.variables[name] = q
        return Entry(line, "define", "ok", f"{name} = {describe(q, digits)}")

    raise DimError("unrecognised statement; expected 'NAME = expr', 'NAME : unit', "
                   "'unit NAME = expr', 'check A = B' or 'show expr [-> unit]'")


def run_source(source, rel_tol=DEFAULT_REL_TOL, digits=DEFAULT_DIGITS, ctx=None):
    """Evaluate every statement in a formula file; errors do not stop later lines."""
    if ctx is None:
        ctx = Context()
    entries = []
    for line, raw in enumerate(source.splitlines(), start=1):
        text = raw.split("#", 1)[0].strip()
        if not text:
            continue
        try:
            entries.append(_statement(ctx, text, line, rel_tol, digits))
        except DimError as exc:
            entries.append(Entry(line, "error", "error", str(exc)))
    return entries


# ---------------------------------------------------------------- command line

def _print_entries(path, entries, only_problems):
    labels = {"ok": "ok", "fail": "FAIL", "error": "error"}
    for entry in entries:
        if only_problems and entry.status == "ok":
            continue
        print(f"{path}:{entry.line}: {labels[entry.status]}: {entry.message}")


def _check_file(args, only_problems):
    source = Path(args.file).read_text(encoding="utf-8")
    entries = run_source(source, args.rel_tol, args.digits)
    errors = sum(e.status == "error" for e in entries)
    failed = sum(e.status == "fail" for e in entries)
    if args.json:
        report = {
            "file": args.file,
            "statements": len(entries),
            "errors": errors,
            "failed": failed,
            "results": [asdict(e) for e in entries],
        }
        print(json.dumps(report, indent=2))
    else:
        _print_entries(args.file, entries, only_problems)
        print(f"{len(entries)} statement(s), {errors} error(s), {failed} failed check(s)")
    return 1 if errors or failed else 0


def _cmd_eval(args):
    print(describe(Context().evaluate(args.expression), args.digits))
    return 0


def _cmd_convert(args):
    ctx = Context()
    number = _convert(ctx.evaluate(args.expression), ctx.evaluate(args.target))
    print(f"{format_number(number, args.digits, exact=args.exact)} {args.target.strip()}")
    return 0


def _cmd_dim(args):
    q = Context().evaluate(args.expression)
    print(f"dimension: {dim_str(q.dim)}")
    print(f"SI value of one unit: {format_number(q.value, args.digits)}")
    return 0


def _cmd_units(args):
    needle = (args.search or "").lower()
    for name in ALL_UNIT_NAMES:
        if needle in name.lower():
            q = builtin_unit(name)
            print(f"{name:<10} {format_number(q.value, args.digits):>16}  {dim_str(q.dim)}")
    if not needle:
        print("prefixes: " + " ".join(PREFIXES) + " (apply to: " + " ".join(sorted(PREFIXABLE)) + ")")
    return 0


def _cmd_consts(args):
    ctx = Context()
    for name in CONSTANTS:
        print(f"{name:<8} {describe(ctx.variables[name], 9)}")
    return 0


def _cmd_run(args):
    return _check_file(args, only_problems=False)


def _cmd_lint(args):
    return _check_file(args, only_problems=True)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dimcheck",
        description="Offline dimensional analysis: evaluate, convert and check unit-bearing formulas.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name, help_text, handler):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--digits", type=int, default=DEFAULT_DIGITS,
                       help=f"significant figures for output (default {DEFAULT_DIGITS})")
        p.set_defaults(handler=handler)
        return p

    p = add("eval", "evaluate an expression in SI base units, e.g. '2 km/h'", _cmd_eval)
    p.add_argument("expression")

    p = add("convert", "convert a quantity to another unit, e.g. 'convert \"5 km\" mi'", _cmd_convert)
    p.add_argument("expression")
    p.add_argument("target")
    p.add_argument("--exact", action="store_true", help="print the exact fraction instead of rounding")

    p = add("dim", "show the dimension and SI value of a unit expression", _cmd_dim)
    p.add_argument("expression")

    p = add("units", "list built-in units, optionally filtered by a search string", _cmd_units)
    p.add_argument("search", nargs="?")

    add("consts", "list the built-in physical constants", _cmd_consts)

    for name, help_text, handler in (
        ("run", "evaluate every statement in a formula file and print results", _cmd_run),
        ("lint", "print only errors and failed checks; exit 1 if any", _cmd_lint),
    ):
        p = add(name, help_text, handler)
        p.add_argument("file")
        p.add_argument("--json", action="store_true", help="print a JSON report")
        p.add_argument("--rel-tol", type=Fraction, default=DEFAULT_REL_TOL,
                       help="relative tolerance for value checks (default 1e-9)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ValueError, OSError) as exc:  # DimError is a ValueError
        print(f"dimcheck: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
