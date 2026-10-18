"""Exhume engine: Final Cut Pro 7 (.fcp) binary project -> importable XML.

Reads the binary project format directly (no Final Cut Pro required) and writes FCP7 XML
(xmeml v5) that DaVinci Resolve and Adobe Premiere Pro can import: specreader reads the
stream, keyg_specdoc builds the document tree and xmeml_emit writes the XML, all from the
specification in spec/.
"""

__version__ = "2.1.2"
