import test from 'node:test';import assert from 'node:assert/strict';
import {categoryValues,categoryRequest} from './categoryState.js';
test('category changes preserve AI role and owned skills without a model message',()=>{
 const base={schema_version:2,roles:['프론트엔드'],owned_skills:['React'],regions:['서울'],career:{levels:['entry']}};
 const value=categoryValues(base);value.regions=['경기'];value.keyword='플랫폼';
 const r=categoryRequest(value,base);
 assert.deepEqual(r.values.search_plan.roles,['프론트엔드']);assert.deepEqual(r.values.search_plan.owned_skills,['React']);
 assert.deepEqual(r.values.search_plan.regions,['경기']);assert.equal(r.values.search_plan.text_query,'플랫폼');
 assert.deepEqual(r.values.search_plan.career.levels,['entry']);assert.equal(r.values.message,undefined);
 value.regions=[];value.entry=false;
 assert.deepEqual(categoryRequest(value,base).values.search_plan.regions,[]);
 assert.deepEqual(categoryRequest(value,base).values.search_plan.career.levels,[]);
});

test('keyword form uses AI interpretation while category changes remain direct',async()=>{
 const {categoryTextRequest}=await import('./categoryState.js');
 const value=categoryValues({schema_version:2,regions:['경기'],required_skills:['Git']});value.keyword='경기도 깃';
 const r=categoryTextRequest(value);
 assert.equal(r.values.message,'경기도 깃');assert.equal(r.values.search_plan,undefined);
 assert.deepEqual(r.values.catalog_plan.regions,['경기']);
 assert.deepEqual(r.values.catalog_plan.required_skills,['Git']);
});
