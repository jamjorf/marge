"""marge: a risk-based (stress-test) portfolio margin calculator."""

__version__ = "0.1.0"

from .config import load_params  # noqa: E402
from .engine import Result, compute, max_scale, run  # noqa: E402
from .model import InputError, Model, build_model  # noqa: E402

__all__ = ["InputError", "Model", "Result", "build_model", "compute", "load_params", "max_scale", "run",
           "__version__"]
