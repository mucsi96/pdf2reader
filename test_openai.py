import base64
import json
import os
import pathlib
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import fitz
from openai import OpenAI

from pdf2reader import llm, meta_from


class OpenAIIntegrationTests(unittest.TestCase):
    """Exercise the real SDK against a local Responses API stub."""

    def setUp(self):
        self.requests = []
        self.status = 200
        self.response = {
            "id": "resp_test", "object": "response", "created_at": 0,
            "model": "gpt-6.1-sol", "status": "completed",
            "output": [{"type": "message", "id": "msg_test", "role": "assistant",
                        "status": "completed", "content": [
                            {"type": "output_text", "text": "# A book", "annotations": []}]}],
        }
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                case.requests.append((self.path, self.headers.get("Authorization"),
                                      json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps(case.response).encode()
                self.send_response(case.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.env = patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
        })
        self.env.start()
        def local_client(**kwargs):
            self.assertEqual(kwargs.pop("base_url"), "https://api.openai.com/v1")
            return OpenAI(base_url=os.environ["OPENAI_BASE_URL"], **kwargs)
        self.client_patch = patch("openai.OpenAI", side_effect=local_client)
        self.client_patch.start()

    def tearDown(self):
        self.client_patch.stop()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_page_image_and_default_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = pathlib.Path(tmp) / "page.png"
            with fitz.open() as doc:
                doc.new_page().get_pixmap().save(image)
            result = llm("Convert this page", img=image)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "# A book")
            path, auth, body = self.requests[0]
            self.assertEqual(path, "/v1/responses")
            self.assertEqual(auth, "Bearer test-key")
            self.assertEqual(body["model"], "gpt-6.1-sol")
            self.assertNotIn("reasoning", body)
            self.assertFalse(body["store"])
            content = body["input"][0]["content"]
            self.assertEqual(content[0]["text"], "Convert this page")
            self.assertEqual(base64.b64decode(content[1]["image_url"].split(",", 1)[1]), image.read_bytes())

    def test_metadata_uses_text_only(self):
        self.response["output"][0]["content"][0]["text"] = '{"title":"A book","author":"Writer","date":""}'
        self.assertEqual(meta_from("A book by Writer")["author"], "Writer")
        content = self.requests[0][2]["input"][0]["content"]
        self.assertEqual([part["type"] for part in content], ["input_text"])

    def test_incomplete_output_is_not_accepted(self):
        self.response.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        result = llm("Convert")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("max_output_tokens", result.stderr)

    def test_api_error_is_reported(self):
        self.status = 401
        self.response = {"error": {"message": "Invalid API key", "type": "invalid_request_error"}}
        result = llm("Convert")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid API key", result.stderr)


if __name__ == "__main__":
    unittest.main()
