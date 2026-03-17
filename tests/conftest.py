"""
conftest.py — mock heavy dependencies so that bot.py constants and pure
functions can be tested without GPU/ML/Telegram/crypto deps.
"""
import sys
from unittest.mock import MagicMock

# Mock all heavy modules before bot.py is imported
_MOCKED = [
    "torch", "torch.nn", "torch.nn.functional",
    "torchvision", "torchvision.transforms", "torchvision.models",
    "PIL", "PIL.Image",
    "cryptography", "cryptography.hazmat",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.asymmetric.padding",
    "telegram", "telegram.ext", "telegram.constants",
    "inference",
]

for mod in _MOCKED:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Ensure telegram.Update and BotCommand are accessible as attributes
import telegram as _tg
_tg.Update = MagicMock()
_tg.BotCommand = MagicMock()
