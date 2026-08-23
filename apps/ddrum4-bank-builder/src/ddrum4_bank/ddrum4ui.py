from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Sequence


@dataclass(frozen=True)
class ToolStatus:
    ddrum4ui: Path | None
    ddrum4edit: Path | None


def discover(root: Path | None = None) -> ToolStatus:
    candidates = []
    if root:
        candidates.append(root)
    candidates.extend([
        # This is the user's current installation and takes precedence over an
        # older installer left under Program Files.
        Path("D:/Studio/ddrum4ui"),
        Path.cwd() / "tools" / "ddrum4ui",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path("C:/Program Files/ddrum4UI"),
        Path("C:/Program Files (x86)/ddrum4UI"),
    ])
    ui = edit = None
    for folder in candidates:
        for name in ("ddrum4ui.exe", "ddrum4UI.exe"):
            candidate = folder / name
            if candidate.is_file() and ui is None:
                ui = candidate
        for name in ("ddrum4edit.exe", "ddrum4Edit.exe"):
            candidate = folder / name
            if candidate.is_file() and edit is None:
                edit = candidate
    if root and ":" in str(root) and ui is None and edit is None:
        # WSL/Linux cannot always see a Windows tool root while the repository
        # is being prepared for a later Windows run.  Surface the declared
        # executable names for planning/discovery without making live backend
        # commands pretend the tools are runnable.
        ui = root / "ddrum4ui.exe"
        edit = root / "ddrum4edit.exe"
    return ToolStatus(ui, edit)


def command_help(executable: Path) -> subprocess.CompletedProcess[str]:
    return run_edit(executable, ["-h"])


def run_edit(executable: Path, arguments: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the user-installed backend without shell interpolation.

    The option set below is the documented ddrum4edit interface.  The toolkit
    never redistributes the proprietary executable and never fabricates an
    encoded sound format itself.
    """
    return subprocess.run([str(executable), *arguments], text=True, capture_output=True,
                          check=False, cwd=cwd)


def launch_ui(executable: Path) -> None:
    """Launch the visual editor on explicit request; it is not GUI-automated."""
    subprocess.Popen([str(executable)])


def encoded_block_count(output: str) -> int | None:
    """Extract the module's encoded block count from `ddrum4edit -p` output."""
    match = re.search(r"Total Blocks Count\s*:\s*[0-9A-F ]+\((\d+)\)", output)
    return int(match.group(1)) if match else None
