"""
Unit tests for protocol parser.
"""

import pytest

from app.services.protocol_parser import (
    parse_pv_address,
    group_by_protocol,
    normalize_addresses,
    strip_protocol_prefix,
)


class TestParseAddress:
    """Tests for parse_pv_address function."""

    def test_parse_ca_prefix(self):
        """Should parse CA protocol prefix correctly."""
        result = parse_pv_address("ca://MY:PV:NAME")
        assert result.protocol == "ca"
        assert result.pv_name == "MY:PV:NAME"
        assert result.original == "ca://MY:PV:NAME"

    def test_parse_pva_prefix(self):
        """Should parse PVA protocol prefix correctly."""
        result = parse_pv_address("pva://MY:PV:NAME")
        assert result.protocol == "pva"
        assert result.pv_name == "MY:PV:NAME"
        assert result.original == "pva://MY:PV:NAME"

    def test_parse_no_prefix_default_ca(self):
        """Should use CA as default protocol when no prefix."""
        result = parse_pv_address("MY:PV:NAME", default_protocol="ca")
        assert result.protocol == "ca"
        assert result.pv_name == "MY:PV:NAME"
        assert result.original == "MY:PV:NAME"

    def test_parse_no_prefix_default_pva(self):
        """Should use PVA as default protocol when configured."""
        result = parse_pv_address("MY:PV:NAME", default_protocol="pva")
        assert result.protocol == "pva"
        assert result.pv_name == "MY:PV:NAME"
        assert result.original == "MY:PV:NAME"

    def test_parse_invalid_protocol(self):
        """Should raise ValueError for unsupported protocol."""
        with pytest.raises(ValueError, match="Unsupported protocol 'http'"):
            parse_pv_address("http://MY:PV:NAME")

    def test_parse_invalid_default_protocol(self):
        """Should raise ValueError for invalid default protocol."""
        with pytest.raises(ValueError, match="Invalid default protocol"):
            parse_pv_address("MY:PV:NAME", default_protocol="invalid")

    def test_parse_empty_address(self):
        """Should raise ValueError for empty address."""
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_pv_address("")

    def test_parse_empty_pv_name_after_prefix(self):
        """Should raise ValueError for empty PV name after prefix."""
        with pytest.raises(ValueError, match="PV name cannot be empty"):
            parse_pv_address("ca://")

    def test_parse_complex_pv_name(self):
        """Should handle complex PV names with special characters."""
        result = parse_pv_address("pva://LINAC:TEMP:1:SETPOINT")
        assert result.protocol == "pva"
        assert result.pv_name == "LINAC:TEMP:1:SETPOINT"

    def test_cache_effectiveness(self):
        """Should cache results for repeated calls."""
        addr = "MY:PV:NAME"
        result1 = parse_pv_address(addr)
        result2 = parse_pv_address(addr)
        # Should return same object due to caching
        assert result1 is result2


class TestNormalizeAddresses:
    """Tests for normalize_addresses function."""

    def test_normalize_mixed_protocols(self):
        """Should normalize list of mixed protocol addresses."""
        addresses = ["ca://PV1", "pva://PV2", "PV3"]
        result = normalize_addresses(addresses, default_protocol="ca")

        assert len(result) == 3
        assert result["ca://PV1"].protocol == "ca"
        assert result["ca://PV1"].pv_name == "PV1"
        assert result["pva://PV2"].protocol == "pva"
        assert result["pva://PV2"].pv_name == "PV2"
        assert result["PV3"].protocol == "ca"
        assert result["PV3"].pv_name == "PV3"

    def test_normalize_empty_list(self):
        """Should handle empty address list."""
        result = normalize_addresses([])
        assert result == {}

    def test_normalize_propagates_errors(self):
        """Should propagate errors from parse_pv_address."""
        with pytest.raises(ValueError):
            normalize_addresses(["invalid://PV"])


class TestGroupByProtocol:
    """Tests for group_by_protocol function."""

    def test_group_mixed_protocols(self):
        """Should group addresses by protocol."""
        addresses = ["ca://PV1", "pva://PV2", "PV3", "pva://PV4"]
        result = group_by_protocol(addresses, default_protocol="ca")

        assert "ca" in result
        assert "pva" in result
        assert len(result["ca"]) == 2
        assert len(result["pva"]) == 2
        assert ("ca://PV1", "PV1") in result["ca"]
        assert ("PV3", "PV3") in result["ca"]
        assert ("pva://PV2", "PV2") in result["pva"]
        assert ("pva://PV4", "PV4") in result["pva"]

    def test_group_single_protocol(self):
        """Should handle all addresses with same protocol."""
        addresses = ["pva://PV1", "pva://PV2", "pva://PV3"]
        result = group_by_protocol(addresses)

        assert "pva" in result
        assert "ca" not in result
        assert len(result["pva"]) == 3

    def test_group_preserves_order(self):
        """Should preserve order within protocol groups."""
        addresses = ["pva://PV1", "pva://PV2", "pva://PV3"]
        result = group_by_protocol(addresses)

        assert result["pva"][0] == ("pva://PV1", "PV1")
        assert result["pva"][1] == ("pva://PV2", "PV2")
        assert result["pva"][2] == ("pva://PV3", "PV3")

    def test_group_empty_list(self):
        """Should handle empty address list."""
        result = group_by_protocol([])
        assert result == {}


class TestStripProtocolPrefix:
    """Tests for strip_protocol_prefix function."""

    def test_strip_ca_prefix(self):
        """Should strip CA prefix."""
        result = strip_protocol_prefix("ca://MY:PV")
        assert result == "MY:PV"

    def test_strip_pva_prefix(self):
        """Should strip PVA prefix."""
        result = strip_protocol_prefix("pva://MY:PV")
        assert result == "MY:PV"

    def test_strip_no_prefix(self):
        """Should return address unchanged if no prefix."""
        result = strip_protocol_prefix("MY:PV")
        assert result == "MY:PV"

    def test_strip_handles_multiple_colons(self):
        """Should only strip protocol prefix, not PV name parts."""
        result = strip_protocol_prefix("pva://MY:SUB:PV:NAME")
        assert result == "MY:SUB:PV:NAME"
