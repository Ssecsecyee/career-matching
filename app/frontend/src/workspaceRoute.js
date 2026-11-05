export function workspaceRoute(hash) {
  if (hash === '#admin') return {mode:'admin',page:'admin'};
  if (hash === '#admin-chat') return {mode:'admin-chat',page:'chat'};
  return {mode:'user',page:hash === '#jobs' ? 'jobs' : hash === '#training' ? 'training' : 'chat'};
}

export function latestSearchResults(messages, target) {
  if(target==='jobs'){
    let list={items:[],total:0,hasMore:false};
    for(const message of messages){
      const d=message.role==='assistant' && message.data;if(!d)continue;
      if(d.stage==='no_results' && d.search_summary){list={items:[],total:0,hasMore:false,summary:d.search_summary};continue;}
      if(d.stage==='choose_job' || d.search_continuation){
        const cards=d.candidate_jobs || [];
        const items=d.search_continuation?[...list.items,...cards]:cards;
        list={items:[...new Map(items.map(c=>[`${c.source || 'jumpit'}:${c.source_id}`,c])).values()],total:d.search_continuation?list.total:d.total,summary:d.search_summary || list.summary,hasMore:cards.length>0 && d.total>cards.length};
      }
    }
    return list;
  }
  for (let i=messages.length-1;i>=0;i--) {
    const data=messages[i].role==='assistant' && messages[i].data;
    if(!data)continue;
    if(target==='jobs' && data.stage==='no_results' && data.search_summary)return {items:[],total:0,summary:data.search_summary};
    if(target==='jobs' && data.stage==='choose_job')return {items:data.candidate_jobs || [],total:data.total,summary:data.search_summary,continuation:data.search_continuation};
    if(target==='training' && data.learning_search && !['training_search_review','training_no_results'].includes(data.stage))
      return {items:data.learning_opportunities || []};
  }
  return {items:[]};
}
