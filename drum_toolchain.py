"""Installed workspace entry point for the offline rig compiler."""
from __future__ import annotations


def main() -> int:
    """Delegate to the separately installable project compiler package."""
    try:
        from rig_compiler.cli import main as compiler_main
    except ImportError as error:
        raise RuntimeError(
            "rig-compiler is not installed; run the documented workspace install"
        ) from error
    return compiler_main()


if __name__ == "__main__":
    raise SystemExit(main())
