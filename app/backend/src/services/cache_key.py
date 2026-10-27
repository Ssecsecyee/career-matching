import hashlib
import json


def response_cache_key(*, owner_scope, session_id, state_version, profile_version,
                       request, selected_job_ids, stage, model_id, prompt_version,
                       policy_version, data_generation, dependency_versions):
    if not owner_scope or not session_id:
        raise ValueError("Personalized cache requires owner and session")
    payload = dict(owner_scope=owner_scope, session_id=session_id,
                   state_version=state_version, profile_version=profile_version,
                   request=request, selected_job_ids=selected_job_ids, stage=stage,
                   model_id=model_id, prompt_version=prompt_version,
                   policy_version=policy_version, data_generation=data_generation,
                   dependency_versions=dependency_versions)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
