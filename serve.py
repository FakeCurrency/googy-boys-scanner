"""Tiny static server with no-cache headers (for local development/preview).

    python serve.py [port] [directory]

Sends Cache-Control: no-store so edits to JS/CSS show up on reload without a
hard refresh. For normal use the launchers' `python -m http.server` is fine.
"""

import functools
import http.server
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
DIRECTORY = sys.argv[2] if len(sys.argv) > 2 else "public"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


def main() -> None:
    handler = functools.partial(NoCacheHandler, directory=DIRECTORY)
    # ThreadingHTTPServer so keep-alive connections don't block one another.
    with http.server.ThreadingHTTPServer(("", PORT), handler) as httpd:
        print(f"Serving {DIRECTORY} at http://localhost:{PORT} (no-cache)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
