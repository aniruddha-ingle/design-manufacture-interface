from dmi.render import fmt
from dmi.spec.models import Length, Position


def test_values_never_round_to_zero():
    assert fmt.value(0.8) == '0.8 mm / 0.03"'
    assert fmt.value(75) == '7.5 cm / 3"'
    assert fmt.length(Length(mm=1.6, tol_mm=0.2), True) == '1.6 mm / 0.06" ±0.2 mm'
    assert fmt.length(Length(mm=75, tol_mm=2), True) == '7.5 cm / 3" ±2 mm'
    assert fmt.length(Length(mm=230, tol_mm=30), True) == '23.0 cm / 9" ±3 cm'


def test_ranges_have_inches():
    r = fmt.length(Length(min_mm=540, max_mm=600))
    assert r == '54.0 cm–60.0 cm / 21 1/4"–23 5/8" (adjustable)'


def test_positions_say_direction():
    p = Position(anchor="centre-back", to="centre", dx_mm=-40, dy_mm=35)
    assert fmt.position(p) == (
        'centre 4.0 cm / 1 5/8" to the viewer\'s left, 3.5 cm / 1 3/8" up from centre back'
    )
    assert "centred, 2.5 cm" in fmt.position(Position(anchor="a", to="centre", dx_mm=0, dy_mm=25))
    assert fmt.position(Position(anchor="a", to="centre", dx_mm=0)) is None
