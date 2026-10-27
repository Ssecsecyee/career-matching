"""Load local project settings without evaluation, interpolation or credential output."""
import os
from pathlib import Path
import re


def load_local_settings(path=None):
    # Lambda uses its execution role and configured environment, never local profiles/files.
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return
    path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / ".env"
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError("Invalid local environment file format")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    # Existing process variables win so a CMD safety override remains effective.
    if os.getenv("AWS_REGION"):
        os.environ.setdefault("AWS_DEFAULT_REGION", os.environ["AWS_REGION"])
        os.environ.setdefault("BEDROCK_REGION", os.environ["AWS_REGION"])
    if os.getenv("MODEL_ID"):
        os.environ.setdefault("BEDROCK_MODEL_ID", os.environ["MODEL_ID"])
    if "BEDROCK_MOCK" in os.environ:
        mock = os.environ["BEDROCK_MOCK"].strip()
        if mock not in {"0", "1"}:
            raise ValueError("BEDROCK_MOCK must be 0 or 1")
        os.environ.setdefault("ENABLE_LIVE_BEDROCK", "true" if mock == "0" else "false")

