"""Safe error metadata, without service error messages or user content."""
RETRYABLE = {"ServiceUnavailableException", "ServiceUnavailable", "InternalServerException",
             "InternalFailure", "ModelTimeoutException", "ModelNotReadyException",
             "ThrottlingException", "ReadTimeoutError", "ConnectTimeoutError",
             "EndpointConnectionError"}


def error_code(error):
    value = getattr(error, "response", {})
    code = value.get("Error", {}).get("Code") if isinstance(value, dict) else None
    return code if isinstance(code, str) and len(code) <= 128 else type(error).__name__


def dependency_error(error):
    code = error_code(error)
    retryable = code in RETRYABLE
    status = 429 if code == "ThrottlingException" else (503 if retryable else 502)
    return status, {"status": "model_temporarily_unavailable" if retryable else "dialogue_dependency_failed",
                    "error_type": type(error).__name__, "error_code": code, "retryable": retryable,
                    "retry_after_seconds": 10 if retryable else None,
                    "message": "Bedrock이 일시적으로 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요."
                    if retryable else "외부 의존 기능이 실패했습니다. 오류 코드를 확인하세요."}
