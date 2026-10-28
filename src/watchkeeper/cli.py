"""Watchkeeper's initial command-line entry point."""

import argparse
from collections.abc import Sequence

from watchkeeper import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watchkeeper",
        description="Experimental supervisor for budgeted, multi-day HPC campaigns.",
        epilog="Only help and version are available. Campaign execution is not implemented.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
