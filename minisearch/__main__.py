"""Allow ``python -m minisearch <docs_dir>`` as an alias of minisearch-cli."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
