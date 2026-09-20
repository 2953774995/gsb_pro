"""Allow `python3 -m datamask` as an alias for the CLI."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
