"""Keep Windows native PlatformIO test runners independent of PATH DLL order."""

import sys

Import("env")

if sys.platform == "win32" and env["PIOENV"] == "native":
    env.Append(LINKFLAGS=["-static-libgcc", "-static-libstdc++"])
