// These labels originate from application buttons, never from free-text input.
export function controlRequest(label) {
  const controls = {
    '역량 확인 질문은 그만해줘': 'stop',
    '다시 역량 조건을 확인해줘': 'resume',
    '우대조건도 계속 확인해줘': 'preferred',
  };
  if (controls[label]) return {action: 'assessment_control', values: {control: controls[label]}};
  if (label === '다른 교육 추천해줘') return {action: 'next_results', values: {target: 'training'}};
  if (label === '다른 공고 추천해줘') return {action: 'next_results', values: {target: 'jobs'}};
  if (label === '현재 답변으로 보완 방향을 정리해줘.') return {action: 'consult', values: {task: 'learning_plan', message: label}};
  throw new Error('Unknown application control');
}
