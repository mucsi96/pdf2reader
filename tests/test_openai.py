import base64
import json
import os
import pathlib
import tempfile
import threading
import unittest
import io
import multiprocessing
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pymupdf as fitz
from openai import OpenAI

from pdf2reader.budget import RequestBudget
from pdf2reader.openai_client import llm, meta_from, retry_delay


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
            self.assertEqual(body["service_tier"], "default")
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

    def test_rate_limit_retries_are_bounded_and_shared(self):
        self.status = 429
        self.response = {"error": {"message": "Slow down", "type": "rate_limit_error"}}
        from unittest.mock import Mock
        budget = Mock()
        result = llm("Convert", budget=budget)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(budget.wait.call_count, 3)
        self.assertEqual(budget.cooldown.call_count, 3)
        budget.record.assert_not_called()

    def test_usage_is_reported_even_for_incomplete_response(self):
        from unittest.mock import Mock
        self.response.update(status="incomplete", usage={
            "input_tokens": 100, "input_tokens_details": {"cached_tokens": 20},
            "output_tokens": 50, "output_tokens_details": {"reasoning_tokens": 10},
            "total_tokens": 150})
        budget = Mock()
        result = llm("Convert", budget=budget)
        self.assertNotEqual(result.returncode, 0)
        usage = budget.record.call_args.args[0]
        self.assertEqual(usage.output_tokens, 50)
        self.assertEqual(usage.input_tokens_details.cached_tokens, 20)


class BudgetTests(unittest.TestCase):
    def test_default_prices_cache_writes_and_long_context(self):
        from openai.types.responses import ResponseUsage
        with tempfile.TemporaryDirectory() as tmp, multiprocessing.Manager() as manager:
            budget = RequestBudget(manager, pathlib.Path(tmp), 10)
            def usage(count):
                return ResponseUsage.model_validate({
                    "input_tokens": count, "output_tokens": 1000, "total_tokens": count + 1000,
                    "input_tokens_details": {"cached_tokens": 4000, "cache_write_tokens": 7000,
                        "cache_write_tokens_details": {"ttl_30m_tokens": 3000, "ttl_12h_tokens": 4000}},
                    "output_tokens_details": {"reasoning_tokens": 800}})
            with patch("sys.stderr", new_callable=io.StringIO) as output:
                budget.record(usage(12000))
                # 1000*2 + 4000*.1 + 3000*2.5 + 4000*5 + 1000*10.
                self.assertIn("$0.039900 USD", output.getvalue())
            with patch("sys.stderr", new_callable=io.StringIO) as output:
                budget.record(usage(300000))
                # Long request: input/cache doubled, output 1.5x, then prior total.
                self.assertIn("$1.266700 USD", output.getvalue())
            resumed = RequestBudget(manager, pathlib.Path(tmp), 10)
            self.assertEqual(dict(resumed.usage), dict(budget.usage))

    def test_old_usage_checkpoint_gets_default_pricing(self):
        with tempfile.TemporaryDirectory() as tmp, multiprocessing.Manager() as manager:
            pathlib.Path(tmp, "usage.json").write_text(json.dumps(
                {"input": 1000, "cached": 200, "output": 100, "unknown": 0}))
            budget = RequestBudget(manager, pathlib.Path(tmp), 10, (None, None, None))
            with patch("sys.stderr", new_callable=io.StringIO) as output:
                budget.report()
                self.assertIn("$0.002620 USD", output.getvalue())

    def test_shared_pacing_cooldown_and_resumed_cost(self):
        with tempfile.TemporaryDirectory() as tmp, multiprocessing.Manager() as manager:
            budget = RequestBudget(manager, pathlib.Path(tmp), 10, (2, 1, 8))
            clock = [100.0]
            def sleep(seconds):
                clock[0] += seconds
            with patch("pdf2reader.budget.time.monotonic", side_effect=lambda: clock[0]), \
                    patch("pdf2reader.budget.time.sleep", side_effect=sleep):
                budget.wait()
                budget.wait()
                self.assertEqual(clock[0], 106)
                budget.cooldown(30)
                budget.wait()
                self.assertEqual(clock[0], 136)
            usage = SimpleNamespace(input_tokens=1000, output_tokens=100,
                                    input_tokens_details=SimpleNamespace(cached_tokens=200))
            with patch("sys.stderr", new_callable=io.StringIO) as output:
                budget.record(usage)
                self.assertIn("$0.002600 USD", output.getvalue())
            resumed = RequestBudget(manager, pathlib.Path(tmp), 10, (2, 1, 8))
            self.assertEqual(dict(resumed.usage), dict(budget.usage))

    def test_retry_after_is_respected(self):
        error = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "120"}))
        self.assertGreaterEqual(retry_delay(error, 0), 120)


if __name__ == "__main__":
    unittest.main()
