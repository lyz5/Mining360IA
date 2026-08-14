from __future__ import annotations

import argparse
import http.client
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream_host = "127.0.0.1"
    upstream_port = 8001
    public_host = ""

    def _proxy(self):
        body_length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(body_length) if body_length else None
        headers = {
            key: value for key, value in self.headers.items()
            if key.casefold() not in HOP_BY_HOP and key.casefold() != "host"
        }
        headers.update({
            "Host": self.public_host,
            "X-Forwarded-Host": self.public_host,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Port": "443",
        })
        connection = http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=120)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.casefold() not in HOP_BY_HOP and key.casefold() != "content-length":
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        finally:
            connection.close()
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _proxy

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--upstream-port", type=int, default=8001)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    ProxyHandler.public_host = args.host
    ProxyHandler.upstream_port = args.upstream_port
    server = ThreadingHTTPServer((args.listen, args.port), ProxyHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.certificate, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Mining360 Dev HTTPS listening on https://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
