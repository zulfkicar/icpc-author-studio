"""Compatibility entry point for existing MCP stdio configurations."""

import sys

from author_studio import mcp_server

if __name__ == "__main__":
    raise SystemExit(mcp_server.main())
else:
    sys.modules[__name__] = mcp_server
