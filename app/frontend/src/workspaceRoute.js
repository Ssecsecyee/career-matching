export function workspaceRoute(hash) {
  if (hash === '#admin') return {mode:'admin',page:'admin'};
  if (hash === '#admin-chat') return {mode:'admin-chat',page:'chat'};
  return {mode:'user',page:hash === '#jobs' ? 'jobs' : hash === '#training' ? 'training' : 'chat'};
}

export function latestSearchResults(messages, target) {
  for (let i=messages.length-1;i>=0;i--) {
    const data=messages[i].role==='assistant' && messages[i].data;
    if(!data)continue;
    if(target==='jobs' && data.stage==='choose_job')return {items:data.candidate_jobs || [],total:data.total};
    if(target==='training' && data.learning_search && !['training_search_review','training_no_results'].includes(data.stage))
      return {items:data.learning_opportunities || []};
  }
  return {items:[]};
}
