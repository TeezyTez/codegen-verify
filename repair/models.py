"""A replay adapter and an opt-in existing-provider adapter; no credentials in logs."""
import json
import time


class Replay:
    kind = "scripted_replay"
    def __init__(self, actions):
        self.actions = list(actions)
        self.index = 0

    def generate(self, prompt, max_tokens, timeout):
        if self.index >= len(self.actions):
            text = json.dumps({"action": "stop"})
        else:
            text = json.dumps(self.actions[self.index])
        self.index += 1
        return {"text": text, "input_tokens": None, "output_tokens": None,
                "cost_usd": 0.0, "seconds": 0.0, "usage_source": "not_applicable_replay"}


class Provider:
    kind = "live_model"
    def __init__(self, input_price=None, output_price=None):
        from .verifier import config
        from llm_client import LLMClient
        self.client = LLMClient(config.CODE_PROVIDER, config.CODE_MODEL, role="verification_repair")
        self.input_price, self.output_price = input_price, output_price

    def generate(self, prompt, max_tokens, timeout):
        from .verifier import config
        from llm_client import get_usage_metrics
        before = get_usage_metrics()["calls"]
        started = time.monotonic()
        old_retries = config.LLM_RETRIES
        config.LLM_RETRIES = 0  # retries are explicit, budgeted runner steps
        previous = self.client.client
        self.client.client = previous.with_options(timeout=max(1, timeout), max_retries=0)
        try:
            text = self.client.chat(system=SYSTEM, user=prompt, temperature=0.2, max_tokens=max_tokens)
        finally:
            self.client.client = previous
            config.LLM_RETRIES = old_retries
        usage = get_usage_metrics(before)
        # The legacy adapter records absent provider usage as zero. A nonempty
        # request cannot have zero prompt tokens: retain an explicit unknown.
        known = usage['successful_calls'] == 1 and usage['prompt_tokens'] > 0
        cost = None
        if known and self.input_price is not None and self.output_price is not None:
            cost = (usage["prompt_tokens"] * self.input_price + usage["completion_tokens"] * self.output_price) / 1e6
        return {"text": text, "input_tokens": usage["prompt_tokens"] if known else None,
                "output_tokens": usage["completion_tokens"] if known else None, "cost_usd": cost,
                "seconds": time.monotonic() - started,
                "usage_source": "provider_reported" if known else "unknown"}


SYSTEM = """Repair verification failures under the frozen task boundaries. A failed
verification obligation is not necessarily an implementation bug. Return JSON only:
{"action":"patch","replacements":{"region_id":"complete replacement text"}}
or {"action":"read","symbol":"name"}, {"action":"verify"}, {"action":"stop"}.
Every condition has the same tools. All patches affect only declared regions.
Never modify target contracts, introduce assumptions/axioms, or skip verification.
Proof regions support single-line invariants or assert expressions as declared.
Implementation regions support balanced Dafny statements. No comments, strings,
attributes, new declarations, nondeterminism or nonterminating loops. Use the
full-file verifier feedback to choose an edit. Final acceptance rechecks the file."""
