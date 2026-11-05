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
