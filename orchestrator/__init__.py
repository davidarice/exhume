"""Final Crack Pro engine: Final Cut Pro 7 (.fcp) binary project -> importable XML.

Reads the binary project format directly (no Final Cut Pro required) and emits FCP7
XML (xmeml v5) that DaVinci Resolve and Adobe Premiere Pro can import. Driven by the
local web app in ../webapp; start everything with `python3 run.py`.
"""

__version__ = "1.0.0"
