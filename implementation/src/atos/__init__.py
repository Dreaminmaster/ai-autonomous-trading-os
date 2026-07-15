"""AI Autonomous Trading OS standard package."""

__version__ = "0.2.0"

# Apply the explicit OKX 5m startup-candle contract before any ATOS C0C
# module is used. This keeps direct imports, tests, and the authoritative
# runner on the same exchange-reproducible value.
from .c0c_okx_startup import apply_okx_startup_contract

apply_okx_startup_contract()
