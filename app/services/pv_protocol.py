from __future__ import annotations

PVA_PREFIX = "pva://"


def parse_pv_name(pv_name: str) -> tuple[str, str]:
    """
    Parse PV name and return (protocol, stripped_name).

    Protocols:
    - "pva": prefixed with pva://
    - "ca": default (no prefix)
    """
    if pv_name.startswith(PVA_PREFIX):
        return "pva", pv_name[len(PVA_PREFIX) :]
    return "ca", pv_name


def is_pva(pv_name: str) -> bool:
    """Return True if PV uses the PVA prefix."""
    return pv_name.startswith(PVA_PREFIX)


def strip_pva_prefix(pv_name: str) -> str:
    """Strip the PVA prefix if present."""
    return pv_name[len(PVA_PREFIX) :] if pv_name.startswith(PVA_PREFIX) else pv_name
