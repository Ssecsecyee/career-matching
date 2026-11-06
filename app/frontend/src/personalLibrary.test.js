import test from 'node:test';
import assert from 'node:assert/strict';
import {readLibrary,writeLibrary,emptyLibrary,addRecent,toggleSaved,withResume} from './personalLibrary.js';
import {filterItems,pageItems} from './browseFilters.js';
test('recent items deduplicate, cap history, and survive storage reload',()=>{
 let library=emptyLibrary();for(let n=0;n<110;n++)library=addRecent(library,{source:'jumpit',source_id:String(n),title:'Job'},'jobs');
 library=addRecent(library,{source:'jumpit',source_id:'109',title:'Updated'},'jobs');
 assert.equal(library.recent.length,100);assert.equal(library.recent[0].title,'Updated');
 let data;const storage={getItem:()=>data,setItem:(k,v)=>data=v};writeLibrary(storage,library);assert.deepEqual(readLibrary(storage),library);
 assert.deepEqual(readLibrary({getItem:()=>'{broken'}),emptyLibrary());
});
test('scraps keep source identities separate and toggling removes them',()=>{
 let library=toggleSaved(emptyLibrary(),{source:'jumpit',source_id:'1'},'jobs');
 library=toggleSaved(library,{source:'training',source_id:'1'},'training');assert.equal(library.saved.length,2);
 library=toggleSaved(library,{source:'jumpit',source_id:'1'},'jobs');assert.equal(library.saved.length,1);
});
test('resume is sent only after explicit opt-in and cleared resume is never sent',()=>{
 const library={...emptyLibrary(),resume:'PRIVATE CV'};
 assert.equal(withResume('hello',library),'hello');assert.match(withResume('hello',{...library,useResume:true}),/PRIVATE CV/);
 assert.equal(withResume('hello',{...library,resume:'',useResume:true}),'hello');
 assert.ok(withResume('x'.repeat(3500),{...library,resume:'y'.repeat(1000),useResume:true}).length<=4000);
});
test('filters distinguish teaching modes and skills; numbered pages never duplicate items',()=>{
 const jobs=Array.from({length:43},(_,i)=>({source_id:String(i),title:'Developer',tech_stacks:[i%2?'Python':'React'],addresses:['서울 강남구']}));
 assert.equal(filterItems(jobs,{extra:'react'}).length,22);assert.equal(pageItems(jobs,1).length,20);assert.equal(pageItems(jobs,3).length,3);
 assert.equal(new Set([...pageItems(jobs,1),...pageItems(jobs,2)].map(x=>x.source_id)).size,40);
 assert.equal(filterItems([{delivery_mode:'online'},{delivery_mode:'offline'},{}],{jobs:false,extra:'unknown'}).length,1);
});
