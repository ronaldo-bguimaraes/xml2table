from __future__ import annotations

from .backend.duckdb import BackendError
from .config import ConfigError, Xml2RelError
from .converter import ConversionError
from .engine import RunStats, TableStats, XMLExtractor
from .parser import ExtractionError

__version__ = "0.1.0"

__all__ = [
    "XMLExtractor",
    "RunStats",
    "TableStats",
    "Xml2RelError",
    "ConfigError",
    "ExtractionError",
    "ConversionError",
    "BackendError",
    "__version__",
]
