export function workspaceRoute(hash) {
  if (hash === '#admin') return {mode:'admin',page:'admin'};
  if (hash === '#admin-chat') return {mode:'admin-chat',page:'chat'};
  return {mode:'user',page:hash === '#jobs' ? 'jobs' : hash === '#training' ? 'training' : 'jobs'};
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
  let list={items:[],hasMore:false};
  for(const message of messages){
    const d=message.role==='assistant' && message.data;if(!d)continue;
    if(d.stage==='training_no_results'){list={items:[],total:d.search_summary?.candidate_total,hasMore:false,summary:d.search_summary};continue;}
    if(d.learning_search && !['training_search_review','training_no_results'].includes(d.stage)){
      const cards=d.learning_opportunities || [];
      const items=d.training_continuation?[...list.items,...cards]:cards;
      list={items:[...new Map(items.map(c=>[`${c.source}:${c.source_id}`,c])).values()],total:d.training_continuation?list.total:(d.training_candidate_total ?? d.search_summary?.candidate_total),hasMore:d.training_has_more ?? cards.length>0,summary:d.search_summary || (d.training_continuation?list.summary:undefined)};
    }
  }
  return list;
}
