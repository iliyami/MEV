"""Per-protocol launchers for the v2 harness.

Each launcher translates a v2 V2Config into the call shape its target protocol
already understands and invokes existing v1 entrypoints. **No launcher modifies
protocol core logic** (see CLAUDE.md). They are pure shims.
"""

from .bullshark import BullsharkLauncher
from .sui import SuiLauncher

__all__ = ["BullsharkLauncher", "SuiLauncher"]
