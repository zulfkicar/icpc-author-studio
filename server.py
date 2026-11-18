"""Compatibility entry point for the local Author Studio server."""

import sys

from author_studio import server

if __name__ == "__main__":
    server.main()
else:
    sys.modules[__name__] = server
