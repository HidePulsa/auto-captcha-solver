"""Auto-Captcha-Solver: AI vision-powered captcha solving, self-hosted."""
__version__ = "0.1.0"

from .core import Solver
from .vision import VisionClient

__all__ = ["Solver", "VisionClient", "__version__"]