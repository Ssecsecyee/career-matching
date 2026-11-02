// Stable application control IDs; display text never determines the action.
const controls = {
  assessment_stop: {action:'assessment_control', values:{control:'stop'}, label:'역량 확인 질문은 그만해줘'},
  assessment_resume: {action:'assessment_control', values:{control:'resume'}, label:'다시 역량 조건을 확인해줘'},
  assessment_preferred: {action:'assessment_control', values:{control:'preferred'}, label:'우대조건도 계속 확인해줘'},
  next_training: {action:'next_results', values:{target:'training'}, label:'다른 교육 추천해줘'},
  next_jobs: {action:'next_results', values:{target:'jobs'}, label:'다른 공고 추천해줘'},
  consult_gaps: {action:'consult', values:{task:'learning_plan', message:'현재 답변으로 보완 방향을 정리해줘.'}, label:'현재 답변으로 보완 방향을 정리해줘.'},
};
export function controlRequest(id) {
  if (!Object.hasOwn(controls,id)) throw new Error('Unknown application control');
  return {...controls[id], values:{...controls[id].values}};
}
