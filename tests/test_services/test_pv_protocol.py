from app.services.pv_protocol import (
    has_protocol_prefix,
    is_unprefixed,
    parse_pv_name,
    strip_protocol_prefix,
)


def test_parse_pv_name_with_pva_prefix():
    protocol, stripped = parse_pv_name("pva://TEST:PV")
    assert protocol == "pva"
    assert stripped == "TEST:PV"


def test_parse_pv_name_with_ca_prefix():
    protocol, stripped = parse_pv_name("ca://TEST:PV")
    assert protocol == "ca"
    assert stripped == "TEST:PV"


def test_parse_pv_name_without_prefix_defaults_to_ca():
    protocol, stripped = parse_pv_name("TEST:PV")
    assert protocol == "ca"
    assert stripped == "TEST:PV"


def test_protocol_prefix_helpers():
    assert has_protocol_prefix("pva://TEST:PV")
    assert has_protocol_prefix("ca://TEST:PV")
    assert not has_protocol_prefix("TEST:PV")
    assert is_unprefixed("TEST:PV")
    assert not is_unprefixed("ca://TEST:PV")
    assert strip_protocol_prefix("pva://TEST:PV") == "TEST:PV"
    assert strip_protocol_prefix("ca://TEST:PV") == "TEST:PV"
