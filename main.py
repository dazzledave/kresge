"""Kresge entry point.

    python main.py

Launches the system-tray network monitor with its dashboard window.
"""
import sys

from kresge.ui.app import run

if __name__ == "__main__":
    sys.exit(run())
