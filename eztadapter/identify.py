"""Decide which artifact type a file is, from its name and first bytes.

Identification never trusts the extension alone. Collection tools keep the
original names ($MFT, NTUSER.DAT), but analysts rename copies (SYSTEM_dc01,
evidence.pf), so most types are recognised by a byte signature, and registry
hives by the name Windows writes inside the hive itself.
"""

from __future__ import annotations

import struct
from fnmatch import fnmatchcase

from .catalog import Artifact, Catalog, Rule

# Enough for every signature in the catalog and for the registry base block.
HEADER_SIZE = 4096

REGF_SIGNATURE = b"regf"
# The base block stores the last 31 UTF-16 characters of the hive's own path,
# for example "\??\C:\Users\eric\ntuser.dat" or "emRoot\System32\Config\SOFTWARE".
_HIVE_NAME_SLICE = slice(0x30, 0x70)


def classify(catalog: Catalog, name: str, header: bytes) -> Artifact | None:
    """Return the first artifact type whose rules match, or None if none does."""
    embedded = hive_embedded_name(header)
    for artifact in catalog.artifacts:
        if any(_rule_matches(rule, name, header, embedded) for rule in artifact.rules):
            return artifact
    return None


def hive_embedded_name(header: bytes) -> str | None:
    """The file name a registry hive records for itself, or None if not a hive."""
    if not header.startswith(REGF_SIGNATURE) or len(header) < _HIVE_NAME_SLICE.stop:
        return None
    raw = header[_HIVE_NAME_SLICE].decode("utf-16-le", errors="replace").split("\x00", 1)[0]
    leaf = raw.replace("/", "\\").rsplit("\\", 1)[-1]
    return leaf or None


def hive_is_dirty(header: bytes) -> bool:
    """True when a hive was not cleanly flushed and its transaction logs hold newer data.

    Windows increments the primary sequence number before writing and copies
    it to the secondary one when done, so unequal numbers mean an interrupted
    or pending write.
    """
    if not header.startswith(REGF_SIGNATURE) or len(header) < 12:
        return False
    primary, secondary = struct.unpack_from("<II", header, 4)
    return primary != secondary


def _rule_matches(rule: Rule, name: str, header: bytes, embedded: str | None) -> bool:
    if rule.names and not _glob_any(name, rule.names):
        return False
    if rule.magic and not any(
        header[magic.offset : magic.offset + len(magic.signature)] == magic.signature for magic in rule.magic
    ):
        return False
    if rule.hive:
        candidates = [name] + ([embedded] if embedded else [])
        if not any(_glob_any(candidate, rule.hive) for candidate in candidates):
            return False
    return True


def _glob_any(name: str, patterns: tuple[str, ...]) -> bool:
    folded = name.casefold()
    return any(fnmatchcase(folded, pattern.casefold()) for pattern in patterns)
