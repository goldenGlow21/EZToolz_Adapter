"""EZToolz Adapter: one window to download forensic tools and run them on evidence.

The adapter recognises artifact files (registry hives, event logs, prefetch,
$MFT and many more) in an evidence folder, offers the tools that parse each
one, and runs them on copies so the evidence itself is never modified.
"""

__version__ = "1.0.0"
