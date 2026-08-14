import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

from webapp.server import Handler


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.shutdown_token = "test-token"
        port = self.server.server_address[1]
        self.server.allowed_hosts = {f"127.0.0.1:{port}"}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.connection.close()

    def request(self, method, path, headers=None):
        self.connection.request(method, path, headers=headers or {})
        return self.connection.getresponse()

    def test_static_index_is_served(self):
        response = self.request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"FCP7 Export Tool", response.read())

    def test_session_exposes_per_launch_shutdown_token(self):
        response = self.request("GET", "/api/session")
        self.assertEqual(response.status, 200)
        self.assertIn(b"test-token", response.read())

    def test_shutdown_rejects_missing_token(self):
        response = self.request("POST", "/api/shutdown", headers={"X-FCP": "1"})
        self.assertEqual(response.status, 403)
        response.read()

    def test_shutdown_accepts_same_origin_token(self):
        response = self.request(
            "POST",
            "/api/shutdown",
            headers={"X-FCP": "1", "X-FCP-Shutdown": "test-token"},
        )
        self.assertEqual(response.status, 200)
        response.read()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
