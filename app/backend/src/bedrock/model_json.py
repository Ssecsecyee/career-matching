"""Parse exactly one model JSON object; never scrape a fragment from prose."""
import json
from time import perf_counter


class ModelOutputFormatError(ValueError):
    def __init__(self, usage):
        super().__init__("Model response is not a valid JSON object")
        self.usage = usage


def parse_object(text, usage):
    value = text.lstrip("\ufeff").strip()
    if value.startswith("```"):
        lines = value.split("\n")
        if len(lines) < 3 or lines[0].strip().lower() not in {"```json", "```"} or lines[-1].strip() != "```":
            raise ModelOutputFormatError(usage)
        value = "\n".join(lines[1:-1]).strip()
    def unique_keys(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = item
        return result
    try:
        parsed = json.loads(value, object_pairs_hook=unique_keys,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid constant")))
        if not isinstance(parsed, dict):
            raise ValueError("Object required")
        return parsed
    except (ValueError, TypeError) as exc:
        raise ModelOutputFormatError(usage) from exc


def usage_metadata(response, *, model_id, region, prompt_version, started):
    usage = response.get("usage", {})
    return {"model_id": model_id, "region": region, "prompt_version": prompt_version,
            "input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens"),
            "cache_read_input_tokens": usage.get("cacheReadInputTokens"),
            "cache_write_input_tokens": usage.get("cacheWriteInputTokens"),
            "latency_ms": round((perf_counter() - started) * 1000),
            "provider_request_id": response.get("ResponseMetadata", {}).get("RequestId")}
