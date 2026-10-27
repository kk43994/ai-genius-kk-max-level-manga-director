"""Frozen background server entry, launched by the tiny native macOS app."""
import os
import sys
import certifi

if getattr(sys, "frozen", False):
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from local_client.launch import main

if __name__ == "__main__":
    raise SystemExit(main())
