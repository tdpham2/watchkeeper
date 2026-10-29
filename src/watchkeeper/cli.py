"""Watchkeeper's command-line entry point."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from watchkeeper import __version__
from watchkeeper.campaign import init_campaign, load_campaign_directory
from watchkeeper.spec import CampaignConfigError


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
    for name, help_text in (
        ("init", "create a simulated campaign configuration"),
        ("validate", "validate campaign, target, and template configuration"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--campaign", type=Path, default=Path("."), metavar="DIR")
    args = parser.parse_args(argv)
    if args.command in ("init", "validate"):
        try:
            if args.command == "init":
                init_campaign(args.campaign)
            else:
                load_campaign_directory(args.campaign)
        except CampaignConfigError as exc:
            print(exc, file=sys.stderr)
            return 2
        if args.command == "init":
            print("Campaign configuration created. Campaign execution is not implemented.")
        else:
            print(
                "Campaign configuration valid (including target/templates). "
                "Configuration validation only; approval, credentials, "
                "and execution readiness are not checked."
            )
    else:
        parser.print_help()
    return 0
