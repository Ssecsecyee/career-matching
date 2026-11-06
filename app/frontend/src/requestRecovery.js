export function needsStepRecovery(data){return data?.error_code==='ModelOutputFormatError' || data?.status==='model_response_needs_clarification';}
export function recoveryMessage(original,step){
 const context=String(original || '').slice(0,3400);
 const instruction=step==='assessment'?'먼저 내 역량을 확인하는 단계부터 도와줘. 필요한 경험 정보를 한 번에 하나씩 물어봐 줘.':'먼저 교육을 찾는 단계부터 도와줘. 검색에 필요한 분야가 불명확하면 한 번에 하나씩 확인해줘.';
 return `이전 요청: ${context}\n이번에는 한 단계만 진행할게. ${instruction}`;
}
