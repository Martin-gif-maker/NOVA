# platform_utils.py — the one door to everything NOVA asks of the operating system.
#
# The work is done in plat_mac.py (macOS) or plat_windows.py (Windows); both offer the same names. This file
# only picks one, so the rest of the app keeps writing `import platform_utils as plat`.
#
# The chosen module is put in this module's place (not copied name by name) on purpose: the tests replace
# functions such as `plat._press_cmd` with harmless stand-ins, and that must reach the code that would
# really press the keys.
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:                          # for the type checker only: the names (both sides offer the same ones)
    from plat_mac import *  # noqa: F403
else:
    if sys.platform == "win32":
        import plat_windows as _impl
    else:
        import plat_mac as _impl
    sys.modules[__name__] = _impl
