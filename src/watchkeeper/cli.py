"""Watchkeeper's command-line entry point."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from watchkeeper import __version__
from watchkeeper.spec import CampaignConfigError, load_campaign


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watchkeeper",
        description="Experimental supervisor for budgeted, multi-day HPC campaigns.",
        epilog="Campaign execution is not implemented.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command")
    validate = commands.add_parser(
        "validate", help="validate campaign configuration only"
    )
    validate.add_argument("--campaign", type=Path, default=Path("."), metavar="DIR")
    args = parser.parse_args(argv)
    if args.command == "validate":
        try:
            load_campaign(args.campaign / "campaign.toml")
        except CampaignConfigError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(
            "Campaign configuration valid. Configuration validation only; "
            "templates, approval, credentials, and execution readiness are not checked."
        )
    else:
        parser.print_help()
    return 0
