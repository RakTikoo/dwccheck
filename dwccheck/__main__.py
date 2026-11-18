"""Allow `python -m dwccheck` as well as the `dwccheck` console script."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
