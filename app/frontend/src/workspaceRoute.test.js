import assert from 'node:assert/strict';
import test from 'node:test';
import {workspaceRoute,latestSearchResults} from './workspaceRoute.js';
test('user tabs share state identity and admin modes remain separate',()=>{
 for(const hash of ['','#chat','#jobs','#training','#unknown'])assert.equal(workspaceRoute(hash).mode,'user');
 assert.equal(workspaceRoute('#jobs').page,'jobs');assert.equal(workspaceRoute('#admin').mode,'admin');assert.equal(workspaceRoute('#admin-chat').mode,'admin-chat');
});
test('only confirmed results appear and empty latest results do not resurrect earlier cards',()=>{
 const m=[{role:'assistant',data:{stage:'choose_job',candidate_jobs:[{source_id:'1'}]}},{role:'assistant',data:{stage:'training_search_review',learning_search:{status:'review_pending'},learning_opportunities:[{source_id:'hidden'}]}}];
 assert.equal(latestSearchResults(m,'jobs').items[0].source_id,'1');assert.deepEqual(latestSearchResults(m,'training').items,[]);
 m.push({role:'assistant',data:{stage:'conversation',learning_search:{status:'found'},learning_opportunities:[{source_id:'2'}]}});assert.equal(latestSearchResults(m,'training').items[0].source_id,'2');
 m.push({role:'assistant',data:{stage:'conversation',learning_search:{status:'no_match'},learning_opportunities:[]}});assert.deepEqual(latestSearchResults(m,'training').items,[]);
});

test('scroll pages append unique jobs and exhausted results stop loading',()=>{
 const m=[{role:'assistant',data:{stage:'choose_job',total:3,candidate_jobs:[{source_id:'1'}]}},{role:'assistant',data:{stage:'choose_job',search_continuation:true,total:2,candidate_jobs:[{source_id:'1'},{source_id:'2'}]}}];
 let r=latestSearchResults(m,'jobs');assert.deepEqual(r.items.map(c=>c.source_id),['1','2']);assert.equal(r.total,3);
 m.push({role:'assistant',data:{stage:'conversation',search_continuation:true,total:0,candidate_jobs:[]}});
 r=latestSearchResults(m,'jobs');assert.equal(r.hasMore,false);assert.equal(r.items.length,2);
 m.push({role:'assistant',data:{stage:'choose_job',total:1,candidate_jobs:[{source_id:'9'}]}});
 assert.deepEqual(latestSearchResults(m,'jobs').items.map(c=>c.source_id),['9']);
});

test('education scroll accumulates groups and stops on exhausted page',()=>{
 const m=[{role:'assistant',data:{learning_search:{status:'found'},learning_opportunities:[{source:'work24',source_id:'1'}],training_has_more:true}},{role:'assistant',data:{learning_search:{status:'found'},learning_opportunities:[{source:'work24',source_id:'2'}],training_continuation:true,training_has_more:true}}];
 assert.equal(latestSearchResults(m,'training').items.length,2);
 m.push({role:'assistant',data:{learning_search:{status:'no_match'},learning_opportunities:[],training_continuation:true,training_has_more:false}});
 assert.equal(latestSearchResults(m,'training').items.length,2);assert.equal(latestSearchResults(m,'training').hasMore,false);
});

test('education total stays at the original candidate count across scroll pages',()=>{
 const m=[{role:'assistant',data:{learning_search:{status:'found'},learning_opportunities:[{source:'w',source_id:'1'}],training_candidate_total:2500,training_continuation:false}}];
 m.push({role:'assistant',data:{learning_search:{status:'found'},learning_opportunities:[{source:'w',source_id:'2'}],training_candidate_total:2400,training_continuation:true}});
 assert.equal(latestSearchResults(m,'training').total,2500);
 m.push({role:'assistant',data:{learning_search:{status:'found'},learning_opportunities:[],training_candidate_total:42,training_continuation:false}});
 assert.equal(latestSearchResults(m,'training').total,42);
});
