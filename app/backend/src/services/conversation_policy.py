"""Application-owned search focus and revocable assessment preferences."""
import re


def preferences(state):
    return state.setdefault('profile', {}).setdefault('assistant_preferences', {'ask_assessment': True})


def respect_preferences(reply, state):
    if preferences(state)['ask_assessment']:
        return reply
    # Final enforcement as well as prompt guidance. Do not expose streamed
    # ability questions before this check when assessment is disabled.
    parts = re.split(r'(?<=[?？])\s*|\n+', reply)
    kept = [part for part in parts if not (
        re.search(r'역량|자격|경력|경험|실력|스킬|기술|보유|사용.*툴', part)
        and re.search(r'[?？]|알려\s*주|말씀해\s*주|궁금|여쭤|물어|있으신가', part))]
    return '\n'.join(kept).strip() or '추가 역량 질문 없이 이미 말씀하신 내용으로 안내하겠습니다.'
