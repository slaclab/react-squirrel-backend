from __future__ import annotations

PVA_PREFIX = "pva://"
CA_PREFIX = "ca://"


def parse_pv_name(pv_name: str) -> tuple[str, str]:
    """
    Parse PV name and return (protocol, stripped_name).

    Protocols:
    - "pva": prefixed with pva://
    - "ca": prefixed with ca://
    - "ca": default for unprefixed names
    """
    if pv_name.startswith(PVA_PREFIX):
        return "pva", pv_name[len(PVA_PREFIX) :]
    if pv_name.startswith(CA_PREFIX):
        return "ca", pv_name[len(CA_PREFIX) :]
    return "ca", pv_name


def is_pva(pv_name: str) -> bool:
    """Return True if PV uses the PVA prefix."""
    return pv_name.startswith(PVA_PREFIX)


def is_ca(pv_name: str) -> bool:
    """Return True if PV uses the CA prefix."""
    return pv_name.startswith(CA_PREFIX)


def has_protocol_prefix(pv_name: str) -> bool:
    """Return True if PV name has any known protocol prefix."""
    return is_pva(pv_name) or is_ca(pv_name)


def is_unprefixed(pv_name: str) -> bool:
    """Return True if PV name has no known protocol prefix."""
    return not has_protocol_prefix(pv_name)


def strip_protocol_prefix(pv_name: str) -> str:
    """Strip known protocol prefixes if present."""
    if pv_name.startswith(PVA_PREFIX):
        return pv_name[len(PVA_PREFIX) :]
    if pv_name.startswith(CA_PREFIX):
        return pv_name[len(CA_PREFIX) :]
    return pv_name
