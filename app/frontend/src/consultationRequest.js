const tasks = new Set(['prepare', 'interview', 'learning_plan', 'explain_unknown', 'defer']);
export function summaryActionRequest(action, summaryId) {
  if (!action || typeof action.message !== 'string' || !action.message.trim()) throw new Error('Invalid summary action');
  if (action.id === 'similar_jobs') return { action: 'next_results', values: { target: 'jobs' } };
  if (!tasks.has(action.id) || !/^[a-f0-9]{64}$/.test(summaryId)) throw new Error('Invalid consultation reference');
  return { action: 'consult', values: { task: action.id, message: action.message, summary_id: summaryId } };
}
