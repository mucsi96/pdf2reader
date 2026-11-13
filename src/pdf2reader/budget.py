"""Process-shared request pacing and persistent token cost accounting."""

import json
import sys
import time

from .checkpoints import save_checkpoint

# Standard USD / million tokens, verified 2026-11-13:
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
# Medium is the API's default reasoning effort; reasoning is included in output.
TOKEN_PRICES = (2.0, 0.10, 10.0)  # input, cached input, output


class RequestBudget:
    """Process-shared pacing, cooldown and durable usage accounting."""

    def __init__(self, manager, directory, rpm, prices=TOKEN_PRICES):
        self.lock = manager.Lock()
        self.state = manager.dict(next_request=0.0)
        self.interval = 60 / rpm
        self.prices = tuple(default if price is None else price
                            for price, default in zip(prices, TOKEN_PRICES))
        self.path = directory / "usage.json"
        if self.path.is_symlink():
            raise ValueError("usage checkpoint must not be a symlink")
        self.usage = manager.dict(input=0, cached=0, output=0, unknown=0)
        # Integer weighted units preserve cache-write and per-request long-context
        # billing across resumes, without rounding money after each response.
        self.usage.update(input_quarters=0, cached_weighted=0, output_halves=0)
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if not isinstance(saved, dict) or any(type(v) is not int or v < 0 for v in saved.values()):
                raise ValueError("invalid usage checkpoint")
            if set(saved) == {"input", "cached", "output", "unknown"}:
                # Older checkpoints did not retain cache writes or context size.
                saved.update(input_quarters=4 * (saved["input"] - saved["cached"]),
                             cached_weighted=saved["cached"], output_halves=2 * saved["output"])
            if set(saved) != set(self.usage) or any(type(v) is not int or v < 0 for v in saved.values()):
                raise ValueError("invalid usage checkpoint")
            self.usage.update(saved)

    def wait(self):
        while True:
            with self.lock:
                delay = self.state["next_request"] - time.monotonic()
                if delay <= 0:
                    self.state["next_request"] = time.monotonic() + self.interval
                    return
            time.sleep(delay)

    def cooldown(self, seconds):
        with self.lock:
            self.state["next_request"] = max(self.state["next_request"], time.monotonic() + seconds)

    def report(self):
        u = dict(self.usage)
        total = sum(tokens * price for tokens, price in zip(
            (u["input_quarters"] / 4, u["cached_weighted"], u["output_halves"] / 2),
            self.prices)) / 1_000_000
        label = f"estimated total ${total:.6f} USD"
        print(f"OpenAI: {label}; input {u['input']:,} (cached {u['cached']:,}), "
              f"output {u['output']:,}; responses without usage {u['unknown']} "
              "[includes previous runs in this checkpoint]", file=sys.stderr, flush=True)

    def record(self, usage):
        with self.lock:
            if usage is None:
                self.usage["unknown"] += 1
            else:
                details = usage.input_tokens_details
                cached = getattr(details, "cached_tokens", 0)
                written = getattr(details, "cache_write_tokens", 0)
                write_details = getattr(details, "cache_write_tokens_details", None)
                # Our requests use the default 30m TTL when no split is supplied.
                write12 = getattr(write_details, "ttl_12h_tokens", 0)
                write30 = written - write12
                ordinary = usage.input_tokens - cached - written
                long_context = usage.input_tokens > 272_000
                self.usage["input_quarters"] += (ordinary * 4 + write30 * 5 + write12 * 10) * (2 if long_context else 1)
                self.usage["cached_weighted"] += cached * (2 if long_context else 1)
                self.usage["output_halves"] += usage.output_tokens * (3 if long_context else 2)
                self.usage["input"] += usage.input_tokens
                self.usage["cached"] += cached
                self.usage["output"] += usage.output_tokens
            save_checkpoint(self.path, dict(self.usage))
            self.report()
