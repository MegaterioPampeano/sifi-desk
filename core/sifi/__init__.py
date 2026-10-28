"""siFi-Desk — port headless de si-Fi / siRNA-Finder v1.2.3.

Este paquete es una obra derivada de si-Fi21 (https://github.com/snowformatics/siFi21-),
licencia CC BY-NC-SA 2.0. Ver LICENSE-siFi.md.
"""
from .params import SifiParams, ToolPaths
from .pipeline import SifiPipeline, PipelineResult

__version__ = "0.1.0"
__all__ = ["SifiParams", "ToolPaths", "SifiPipeline", "PipelineResult", "__version__"]
