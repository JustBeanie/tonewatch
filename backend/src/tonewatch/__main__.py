"""Command-line entry point for ToneWatch."""

import argparse

from tonewatch import __version__


def main() -> None:
    """Run the ToneWatch command-line interface."""
    parser = argparse.ArgumentParser(prog="tonewatch")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args()


if __name__ == "__main__":
    main()
