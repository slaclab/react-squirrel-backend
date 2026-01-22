"""
Protocol detection and PV address parsing.

This module handles parsing of PV addresses to detect protocol prefixes
(ca:// or pva://) and applies default protocols for unprefixed addresses.
"""

from functools import lru_cache
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedAddress:
    """
    Parsed PV address with protocol information.

    Attributes:
        protocol: Protocol type ("ca" or "pva")
        pv_name: PV name with protocol prefix stripped
        original: Original address string as provided
    """

    protocol: str
    pv_name: str
    original: str


@lru_cache(maxsize=10000)
def parse_pv_address(address: str, default_protocol: str = "ca") -> ParsedAddress:
    """
    Parse PV address and extract protocol information.

    Supports explicit protocol prefixes (ca:// or pva://) and applies
    default protocol for unprefixed addresses.

    Examples:
        >>> parse_pv_address("pva://MY:PV:NAME")
        ParsedAddress(protocol='pva', pv_name='MY:PV:NAME', original='pva://MY:PV:NAME')

        >>> parse_pv_address("ca://MY:PV:NAME")
        ParsedAddress(protocol='ca', pv_name='MY:PV:NAME', original='ca://MY:PV:NAME')

        >>> parse_pv_address("MY:PV:NAME", default_protocol="ca")
        ParsedAddress(protocol='ca', pv_name='MY:PV:NAME', original='MY:PV:NAME')

    Args:
        address: PV address string (with or without protocol prefix)
        default_protocol: Protocol to use when no prefix is present (default: "ca")

    Returns:
        ParsedAddress object with protocol, stripped name, and original address

    Raises:
        ValueError: If protocol prefix is not "ca" or "pva"
    """
    if not address:
        raise ValueError("PV address cannot be empty")

    # Check for explicit protocol prefix
    if "://" in address:
        protocol, pv_name = address.split("://", 1)
        if protocol not in ("ca", "pva"):
            raise ValueError(f"Unsupported protocol '{protocol}'. Must be 'ca' or 'pva'")
        if not pv_name:
            raise ValueError("PV name cannot be empty after protocol prefix")
        return ParsedAddress(protocol=protocol, pv_name=pv_name, original=address)

    # No prefix - use default protocol
    if default_protocol not in ("ca", "pva"):
        raise ValueError(f"Invalid default protocol '{default_protocol}'. Must be 'ca' or 'pva'")

    return ParsedAddress(protocol=default_protocol, pv_name=address, original=address)


def normalize_addresses(addresses: list[str], default_protocol: str = "ca") -> dict[str, ParsedAddress]:
    """
    Parse multiple PV addresses and return mapping of original to parsed.

    Args:
        addresses: List of PV address strings
        default_protocol: Default protocol for unprefixed addresses

    Returns:
        Dictionary mapping original address to ParsedAddress

    Raises:
        ValueError: If any address has invalid protocol or format
    """
    return {addr: parse_pv_address(addr, default_protocol) for addr in addresses}


def group_by_protocol(addresses: list[str], default_protocol: str = "ca") -> dict[str, list[tuple[str, str]]]:
    """
    Group PV addresses by protocol for efficient batch operations.

    Args:
        addresses: List of PV address strings
        default_protocol: Default protocol for unprefixed addresses

    Returns:
        Dictionary mapping protocol ("ca" or "pva") to list of
        (original_address, stripped_pv_name) tuples

    Example:
        >>> group_by_protocol(["ca://PV1", "pva://PV2", "PV3"], default_protocol="ca")
        {
            "ca": [("ca://PV1", "PV1"), ("PV3", "PV3")],
            "pva": [("pva://PV2", "PV2")]
        }
    """
    grouped: dict[str, list[tuple[str, str]]] = {}

    for addr in addresses:
        parsed = parse_pv_address(addr, default_protocol)
        if parsed.protocol not in grouped:
            grouped[parsed.protocol] = []
        grouped[parsed.protocol].append((parsed.original, parsed.pv_name))

    return grouped


def strip_protocol_prefix(address: str) -> str:
    """
    Strip protocol prefix from address if present.

    Args:
        address: PV address string

    Returns:
        Address with protocol prefix removed

    Example:
        >>> strip_protocol_prefix("pva://MY:PV")
        "MY:PV"
        >>> strip_protocol_prefix("MY:PV")
        "MY:PV"
    """
    if "://" in address:
        _, pv_name = address.split("://", 1)
        return pv_name
    return address
