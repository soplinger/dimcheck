import json
from fractions import Fraction
from pathlib import Path

import pytest

from dimcheck import (
    Context,
    DimError,
    builtin_unit,
    canonical_unit,
    dim_str,
    format_number,
    main,
    run_source,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TIGHT = Fraction("1e-9")


def ev(text):
    return Context().evaluate(text)


def statuses(entries):
    return {e.line: e.status for e in entries}


def test_number_then_unit_is_implicit_multiplication():
    q = ev("2 m")
    assert q.value == 2
    assert dim_str(q.dim) == "m"


def test_conversion_is_exact():
    assert ev("1 mi").value == Fraction(1609344, 1000)
    assert ev("1 ft").value == Fraction(3048, 10000)


def test_kg_m_per_s_squared_is_newton():
    q = ev("kg*m/s^2")
    assert q.value == 1
    assert canonical_unit(q.dim) == "N"


def test_prefixes_apply_to_units():
    assert ev("1 kN").value == 1000
    assert ev("1 mm").value == Fraction(1, 1000)
    assert ev("1 mL").value == Fraction(1, 10**6)


def test_min_is_minute_not_milli_inch():
    assert ev("1 min").value == 60


def test_negative_exponent_gives_reciprocal_dimension():
    assert dim_str(ev("m^-2").dim) == "1/m^2"


def test_power_of_parenthesised_quantity():
    q = ev("(2 m)^3")
    assert q.value == 8
    assert dim_str(q.dim) == "m^3"


def test_adding_different_dimensions_is_rejected():
    with pytest.raises(DimError, match="dimension mismatch"):
        ev("1 m + 1 s")


def test_division_by_zero_is_rejected():
    with pytest.raises(DimError, match="division by zero"):
        ev("1 m / 0")


def test_unknown_unit_suggests_close_name():
    with pytest.raises(DimError, match="did you mean 'ft'"):
        ev("ftt")


def test_constants_are_exact():
    assert ev("c0").value == 299792458
    assert dim_str(ev("hP").dim) == "kg*m^2/s"


def test_format_number_switches_to_scientific_for_tiny_values():
    assert format_number(Fraction(1, 10**7)) == "1e-7"
    assert format_number(Fraction(1, 3), digits=4) == "0.3333"
    assert format_number(Fraction(1, 3), exact=True) == "1/3"


def test_run_reports_error_with_line_number():
    entries = run_source("a = 1 m\n\nb = a + 1 s\n")
    assert [e.line for e in entries] == [1, 3]
    assert entries[1].status == "error"
    assert "dimension mismatch" in entries[1].message


def test_check_passes_when_dimensions_and_values_agree():
    entries = run_source("check 1 kg*m/s^2 = 1 N", TIGHT)
    assert entries[0].status == "ok"


def test_check_flags_dimension_mismatch():
    entries = run_source("check 1 J = 1 N", TIGHT)
    assert entries[0].status == "fail"
    assert "dimension mismatch" in entries[0].message


def test_check_flags_value_mismatch_beyond_tolerance():
    entries = run_source("check 5 N = 4.9 N", TIGHT)
    assert entries[0].status == "fail"
    assert "value mismatch" in entries[0].message


def test_check_tolerance_accepts_tiny_difference():
    entries = run_source("check 9.80665 m/s^2 = 9.806650001 m/s^2", Fraction("1e-6"))
    assert entries[0].status == "ok"


def test_symbolic_declarations_check_dimensions_only():
    src = "mass : kg\naccel : m/s^2\nforce : N\ncheck force = mass*accel\n"
    entries = run_source(src, TIGHT)
    assert entries[-1].status == "ok"
    assert "not compared" in entries[-1].message


def test_user_unit_definition_and_conversion():
    entries = run_source("unit furlong = 201.168 m\nshow 2 furlong -> m", TIGHT)
    assert entries[1].message == "2 furlong = 402.336 m"


def test_builtin_names_cannot_be_redefined():
    entries = run_source("m = 3 kg", TIGHT)
    assert entries[0].status == "error"
    assert "built-in unit" in entries[0].message


def test_constants_cannot_be_redefined():
    entries = run_source("c0 = 3 m/s", TIGHT)
    assert entries[0].status == "error"
    assert "already defined" in entries[0].message


def test_undefined_name_is_an_error():
    entries = run_source("x = y + 1 m", TIGHT)
    assert entries[0].status == "error"
    assert "unknown name 'y'" in entries[0].message


def test_show_rejects_wrong_target_dimension():
    entries = run_source("show 5 km -> s", TIGHT)
    assert entries[0].status == "error"
    assert "cannot convert" in entries[0].message


def test_example_file_is_clean():
    entries = run_source((EXAMPLES / "projectile.dim").read_text(encoding="utf-8"))
    assert {e.status for e in entries} == {"ok"}
    assert any(e.kind == "show" and e.message.startswith("ke = 36 J") for e in entries)


def test_bad_example_reports_each_problem_on_its_line():
    entries = run_source((EXAMPLES / "bad.dim").read_text(encoding="utf-8"))
    by_line = statuses(entries)
    assert [n for n, s in by_line.items() if s == "error"] == [9, 10, 11, 13]
    assert [n for n, s in by_line.items() if s == "fail"] == [6, 8]


def test_cli_eval_prints_canonical_unit(capsys):
    assert main(["eval", "9.80665 m/s^2"]) == 0
    assert capsys.readouterr().out.strip() == "9.80665 m/s^2"


def test_cli_convert_exact(capsys):
    assert main(["convert", "1 mi", "m", "--exact"]) == 0
    assert capsys.readouterr().out.strip() == "201168/125 m"


def test_cli_convert_rounded(capsys):
    assert main(["convert", "5 km", "mi"]) == 0
    assert capsys.readouterr().out.strip() == "3.10686 mi"


def test_cli_convert_dimension_error_returns_2(capsys):
    assert main(["convert", "1 m", "s"]) == 2
    assert "cannot convert" in capsys.readouterr().err


def test_cli_dim_reports_base_dimension(capsys):
    assert main(["dim", "mph"]) == 0
    assert "dimension: m/s" in capsys.readouterr().out


def test_cli_lint_exit_codes_and_line_output(capsys):
    assert main(["lint", str(EXAMPLES / "projectile.dim")]) == 0
    capsys.readouterr()
    assert main(["lint", str(EXAMPLES / "bad.dim")]) == 1
    out = capsys.readouterr().out
    assert "bad.dim:9: error:" in out
    assert "bad.dim:6: FAIL:" in out


def test_cli_run_json_report(capsys, tmp_path):
    formula = tmp_path / "ok.dim"
    formula.write_text("unit cubit = 0.45 m\nshow 2 cubit -> cm\n", encoding="utf-8")
    assert main(["run", str(formula), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["errors"] == 0
    assert report["results"][1]["message"] == "2 cubit = 90 cm"


def test_cli_missing_file_returns_2(capsys):
    assert main(["lint", str(EXAMPLES / "does-not-exist.dim")]) == 2
    assert "dimcheck: error:" in capsys.readouterr().err


def test_units_listing_filters_by_search(capsys):
    assert main(["units", "furlong"]) == 0
    assert capsys.readouterr().out == ""
    assert main(["units", "gal"]) == 0
    assert "gal" in capsys.readouterr().out


def test_derived_units_are_built_from_their_definitions():
    assert builtin_unit("gal").value == 231 * Fraction("0.0254") ** 3
    assert builtin_unit("lbf").value == builtin_unit("lb").value * Fraction("9.80665")
