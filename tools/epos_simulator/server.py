#!/usr/bin/env python3
"""Minimal Epson ePOS receiver for development and staging only."""

import base64
import hashlib
import html
import json
import os
import secrets
import struct
import threading
import urllib.parse
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree


DATA_DIR = Path(os.environ.get("EPOS_DATA_DIR", "/data"))
TOKEN = os.environ["EPOS_REVIEW_TOKEN"]
MAX_BODY_BYTES = int(os.environ.get("EPOS_MAX_BODY_BYTES", str(12 * 1024 * 1024)))
MAX_JOBS = int(os.environ.get("EPOS_MAX_JOBS", "200"))
LOCK = threading.Lock()


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _png_chunk(kind, payload):
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def raster_to_png(encoded, width, height):
    packed = base64.b64decode("".join(encoded.split()), validate=True)
    pixel_count = width * height
    if width <= 0 or height <= 0 or pixel_count > 12_000_000:
        raise ValueError("invalid image dimensions")
    if len(packed) != (pixel_count + 7) // 8:
        raise ValueError("raster length does not match dimensions")

    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            bit_index = y * width + x
            black = (packed[bit_index // 8] >> (7 - bit_index % 8)) & 1
            row.append(0 if black else 255)
        rows.append(bytes(row))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


def _authorized(query):
    supplied = urllib.parse.parse_qs(query).get("token", [""])[0]
    return secrets.compare_digest(supplied, TOKEN)


def _jobs():
    jobs = []
    for path in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return jobs


def _rotate():
    jobs = sorted(DATA_DIR.glob("*.json"), reverse=True)
    for metadata_path in jobs[MAX_JOBS:]:
        stem = metadata_path.stem
        for suffix in (".json", ".png", ".xml"):
            (DATA_DIR / f"{stem}{suffix}").unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "Epson-ePOS-Staging-Simulator/1.0"

    def log_message(self, fmt, *args):
        print(
            json.dumps(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "remote": self.client_address[0],
                    "message": fmt % args,
                }
            ),
            flush=True,
        )

    def _headers(self, status, content_type="text/plain; charset=utf-8", length=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def do_OPTIONS(self):
        self._headers(204, length=0)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/healthz":
            body = b"ok\n"
            self._headers(200, length=len(body))
            self.wfile.write(body)
            return

        if parsed.path == "/review":
            if not _authorized(parsed.query):
                self._headers(403, length=0)
                return
            rows = []
            for job in _jobs():
                job_id = html.escape(job["id"])
                image_url = (
                    f"/jobs/{urllib.parse.quote(job['id'])}.png"
                    f"?token={urllib.parse.quote(TOKEN)}"
                )
                rows.append(
                    f"<article><h2>{html.escape(job['received_at'])}</h2>"
                    f"<p>ID <code>{job_id}</code> · {job['width']}×{job['height']} "
                    f"· {job['body_bytes']} bytes</p>"
                    f"<img src='{html.escape(image_url)}' alt='Comanda {job_id}'></article>"
                )
            body = (
                "<!doctype html><meta charset=utf-8><title>Comandas virtuales</title>"
                "<style>body{font:16px system-ui;margin:2rem;max-width:960px}"
                "article{border-top:1px solid #ccc;padding:1rem 0}"
                "img{max-width:100%;background:white;border:1px solid #ddd}"
                "code{font-size:.85em}</style>"
                "<h1>Comandas Epson ePOS — STAGING</h1>"
                "<p>Últimas comandas recibidas; las más recientes aparecen primero.</p>"
                + ("".join(rows) if rows else "<p>Aún no se recibió ninguna comanda.</p>")
            ).encode("utf-8")
            self._headers(200, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return

        if parsed.path.startswith("/jobs/") and parsed.path.endswith(".png"):
            if not _authorized(parsed.query):
                self._headers(403, length=0)
                return
            name = Path(urllib.parse.unquote(parsed.path)).name
            if not name.endswith(".png") or any(
                char not in "0123456789T-Zabcdef.png" for char in name
            ):
                self._headers(404, length=0)
                return
            path = DATA_DIR / name
            if not path.is_file():
                self._headers(404, length=0)
                return
            body = path.read_bytes()
            self._headers(200, "image/png", len(body))
            self.wfile.write(body)
            return

        self._headers(404, length=0)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if (
            parsed.path != "/cgi-bin/epos/service.cgi"
            or query.get("devid") != ["local_printer"]
        ):
            self._headers(404, length=0)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY_BYTES:
            self._headers(413, length=0)
            return

        body = self.rfile.read(length)
        try:
            root = ElementTree.fromstring(body)
            images = [node for node in root.iter() if _local_name(node.tag) == "image"]
            if len(images) != 1:
                raise ValueError("expected exactly one image")
            image = images[0]
            width = int(image.attrib["width"])
            height = int(image.attrib["height"])
            png = raster_to_png(image.text or "", width, height)
        except (ElementTree.ParseError, KeyError, ValueError, TypeError) as exc:
            response = b'<?xml version="1.0"?><response success="false" code="EPTR_FORMAT"/>'
            self._headers(200, "application/xml; charset=utf-8", len(response))
            self.wfile.write(response)
            self.log_message("invalid print job: %s", type(exc).__name__)
            return

        now = datetime.now(timezone.utc)
        body_hash = hashlib.sha256(body).hexdigest()
        job_id = now.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + body_hash[:12]
        metadata = {
            "id": job_id,
            "received_at": now.isoformat(),
            "body_bytes": len(body),
            "sha256": body_hash,
            "width": width,
            "height": height,
        }
        with LOCK:
            (DATA_DIR / f"{job_id}.xml").write_bytes(body)
            (DATA_DIR / f"{job_id}.png").write_bytes(png)
            (DATA_DIR / f"{job_id}.json").write_text(
                json.dumps(metadata, sort_keys=True), encoding="utf-8"
            )
            for suffix in (".xml", ".png", ".json"):
                os.chmod(DATA_DIR / f"{job_id}{suffix}", 0o600)
            _rotate()

        response = b'<?xml version="1.0"?><response success="true" code=""/>'
        self._headers(200, "application/xml; charset=utf-8", len(response))
        self.wfile.write(response)
        self.log_message("stored job %s", job_id)


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    address = ("0.0.0.0", int(os.environ.get("EPOS_PORT", "9000")))
    ThreadingHTTPServer(address, Handler).serve_forever()
