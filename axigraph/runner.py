"""Axigraph CLI entry point."""

import sys

import uvicorn


def main() -> None:
    """Run the Axigraph API server."""
    uvicorn.run(
        "axigraph.main:app",
        host="0.0.0.0",
        port=8000,
        reload="--reload" in sys.argv,
    )


if __name__ == "__main__":
    main()
