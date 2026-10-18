# dimcheck

**Offline dimensional analysis for formulas: every number carries its units, and every mistake gets a line number.**

dimcheck evaluates unit-bearing expressions with exact fractions, converts between units without rounding, and checks formula files line by line. A formula that adds metres to seconds, or claims that 36 J equals 36 N, fails before anyone trusts the result.

It is a single standard-library Python file. No servers, no accounts, no network calls.

## Features

- **Exact arithmetic.** Quantities are `Fraction`s in SI base units, so `1 mi` is exactly `1609.344 m`.
- **Dimension tracking.** Every value carries exponents of m, kg, s, A, K, mol and cd. Mixing dimensions in `+` or `-` is an error.
- **Unit expressions.** Use `*`, `/`, `^` (including negative powers), parentheses and juxtaposition: `kg*m/s^2`, `2 km/h`, `(2 m)^3`.
- **SI prefixes.** `kN`, `mm`, `mL`, `MHz`, `uF` (or `µF`) work for prefixable units. Exact names win, so `min` is a minute, not a milli-inch.
- **Built-in catalogue.** Imperial and US units, time, mass, volume, force, pressure, energy, power and electrical units, each defined from first principles (`lbf` is `lb × 9.80665 m/s²`).
- **Named results.** Coherent SI results display by name, e.g. `kg*m/s^2` shows as `N`.
- **Conversion** between any two compatible units, rounded to N significant figures or printed as an exact fraction (`--exact`).
- **Dimension report** for any unit expression (`dim`), with its SI value.
- **Physical constants** with exact SI values (`c0`, `g0`, `hP`, `kB`, `NA`, `qe`, `Rgas`, `Ggrav`).
- **Formula files** with four statement types: variables (`mass = 2 kg`), custom units (`unit furlong = 201.168 m`), dimension-only symbols (`force : N`) and checks.
- **Equation checks** that compare dimensions always and values within a relative tolerance (`check A = B`).
- **Shown results** with optional target units (`show ke -> J`).
- **Line-numbered errors** for syntax, unknown names, redefinitions and dimension mismatches. Later lines still run after an error.
- **"Did you mean" hints** for misspelled unit names.
- **CI-ready exit codes:** `0` clean, `1` errors or failed checks, `2` bad usage or unreadable file.
- **JSON reports** with `run --json` for other tools.

## Quick start

Evaluate and convert:

```console
$ python3 dimcheck.py eval "9.80665 m/s^2"
9.80665 m/s^2

$ python3 dimcheck.py convert "5 km" mi
3.10686 mi
```

Lint a formula file (`examples/projectile.dim` is a clean example; `examples/bad.dim` is a deliberately broken one):

```console
$ python3 dimcheck.py lint examples/bad.dim
examples/bad.dim:6: FAIL: dimension mismatch: kg*m/s vs N
examples/bad.dim:8: FAIL: dimension mismatch: kg*m/s vs J
examples/bad.dim:9: error: dimension mismatch in '+': m vs s
examples/bad.dim:10: error: dimension mismatch in '+': kg vs m/s
examples/bad.dim:11: error: cannot convert kg*m/s to N
examples/bad.dim:13: error: unknown name 'ghost'
12 statement(s), 4 error(s), 2 failed check(s)
```

An excerpt from `examples/projectile.dim`:

```text
# A 0.5 kg ball thrown at 12 m/s: energy, weight and conversions.
unit furlong = 201.168 m
mass = 0.5 kg
speed = 12 m/s
ke = 0.5 * mass * speed^2
check ke = 36 J
check ke = 36 kg*m^2/s^2
weight = mass * g0
check weight = 4.903325 N
show ke -> J
show 2 furlong -> m
```

Run it to see every statement's result:

```console
$ python3 dimcheck.py run examples/projectile.dim
```

## Formula file syntax

| Statement | Meaning |
| --- | --- |
| `NAME = expr` | Define a value. Names may not match a unit or constant. |
| `NAME : unit-expr` | Declare a symbol with a dimension but no value. |
| `unit NAME = expr` | Define a custom unit with a known value. |
| `check A = B` | Dimensions must match; values must agree within `--rel-tol`. |
| `show expr` or `show expr -> unit` | Print a value, optionally converted. |
| `# ...` | Comment. |

## Commands

| Command | Purpose |
| --- | --- |
| `eval EXPR` | Evaluate in SI base units with a named result |
| `convert EXPR TARGET` | Convert, with `--exact` for fractions |
| `dim EXPR` | Show dimension and SI value of one unit |
| `units [SEARCH]` | List built-in units, optionally filtered |
| `consts` | List physical constants |
| `run FILE` | Evaluate and report every statement |
| `lint FILE` | Report only errors and failed checks |

`run` and `lint` accept `--json`, `--rel-tol` (default `1e-9`) and `--digits`.

## Requirements

Python 3.8 or newer for the program. Python 3.12 is what it was written against. Tests need `pytest`.

## Run

```console
$ python3 dimcheck.py --help
$ python3 dimcheck.py units gal
$ python3 dimcheck.py run examples/projectile.dim
```

## Test

Install pytest once, then run from the project root:

```console
$ python3 -m pip install pytest
$ python3 -m pytest -q
```

The tests in `tests/test_dimcheck.py` cover parsing, exact conversion, prefixes, dimension errors, equation checks with tolerances, formula-file line numbers, and CLI exit codes and output.

Status: this version was written without being executed in the authoring environment, so the test suite and the sample outputs above have not been run yet. Run the commands above to confirm them.

## Limits

- Temperatures use absolute scales only (K). Offset scales such as °C and °F are not supported.
- Exponents must be whole numbers.
- Angles are dimensionless and are not converted between degrees and radians.
- Variables cannot share a name with a unit, so `m` cannot be a variable. Use names such as `mass`.
