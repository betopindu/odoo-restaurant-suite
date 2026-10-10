import base64
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOKEN = "test-review-token"


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(url, data=None):
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/xml")
    return urllib.request.urlopen(request, timeout=3)


def _job(bits=b"\xaa"):
    image = base64.b64encode(bits).decode("ascii")
    return (
        '<?xml version="1.0"?>'
        '<epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">'
        f'<image width="8" height="{len(bits)}">{image}</image>'
        '<cut type="feed"/></epos-print>'
    ).encode("utf-8")


class EpsonSimulatorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.port = _free_port()
        environment = os.environ.copy()
        environment.update(
            {
                "EPOS_DATA_DIR": self.temp_dir.name,
                "EPOS_REVIEW_TOKEN": TOKEN,
                "EPOS_MAX_JOBS": "2",
                "EPOS_PORT": str(self.port),
            }
        )
        self.process = subprocess.Popen(
            ["python3", str(ROOT / "server.py")],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.base_url = f"http://127.0.0.1:{self.port}"
        for _ in range(30):
            try:
                if _request(f"{self.base_url}/healthz").read() == b"ok\n":
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        else:
            self.fail("simulator did not become ready")

    def tearDown(self):
        self.process.terminate()
        self.process.wait(timeout=3)
        self.temp_dir.cleanup()

    def _post(self, body):
        return _request(
            f"{self.base_url}/cgi-bin/epos/service.cgi?devid=local_printer",
            data=body,
        ).read()

    def test_valid_epos_job_is_rendered_and_review_is_protected(self):
        response = self._post(_job())
        self.assertIn(b'success="true"', response)
        metadata_files = list(Path(self.temp_dir.name).glob("*.json"))
        self.assertEqual(len(metadata_files), 1)
        metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
        self.assertEqual((metadata["width"], metadata["height"]), (8, 1))
        png = metadata_files[0].with_suffix(".png").read_bytes()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            _request(f"{self.base_url}/review")
        self.assertEqual(unauthorized.exception.code, 403)
        review = _request(f"{self.base_url}/review?token={TOKEN}").read()
        self.assertIn(metadata["id"].encode(), review)

    def test_invalid_job_fails_without_persisting_content(self):
        response = self._post(b"<not-epos/>")
        self.assertIn(b'success="false"', response)
        self.assertEqual(list(Path(self.temp_dir.name).iterdir()), [])

    def test_retention_keeps_only_configured_number_of_jobs(self):
        for byte in (b"\x80", b"\x40", b"\x20"):
            self.assertIn(b'success="true"', self._post(_job(byte)))
            time.sleep(0.002)
        files = list(Path(self.temp_dir.name).iterdir())
        self.assertEqual(len(list(Path(self.temp_dir.name).glob("*.json"))), 2)
        self.assertEqual(len(files), 6)


if __name__ == "__main__":
    unittest.main()
