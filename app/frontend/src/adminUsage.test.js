import test from 'node:test';
import assert from 'node:assert/strict';
import {summarizeUsage,usageRow} from './adminUsage.js';
const model_id='global.anthropic.claude-sonnet-4-6';
test('weighted average includes failed attempts and uses the call count denominator',()=>{
 const v=summarizeUsage([{model_id,status:'succeeded',calls:111,input_tokens:254343,output_tokens:17911},{model_id,status:'failed',calls:11,input_tokens:36509,output_tokens:5056}]);
 assert.equal(v.calls,122);assert.equal(v.total,313819);assert.equal(v.input,290852);assert.equal(v.output,22967);
 assert.equal(v.averageTokens,313819/122);assert.ok(Math.abs(v.estimatedCost-1.217061)<1e-10);assert.ok(Math.abs(v.averageCost-1.217061/122)<1e-10);
 assert.equal(v.succeeded,111);assert.equal(v.failed,11);
});
test('empty history never divides by zero',()=>{const v=summarizeUsage();assert.equal(v.averageTokens,null);assert.equal(v.averageCost,null);});
test('unknown model and cache price are not silently estimated',()=>{
 assert.equal(usageRow({model_id:'different',calls:1,input_tokens:10}).estimatedCost,null);
 assert.equal(usageRow({model_id,calls:1,input_tokens:10,cache_write_input_tokens:10}).estimatedCost,null);
 assert.equal(summarizeUsage([{model_id,calls:1,input_tokens:10},{model_id:'different',calls:1}]).estimatedCost,null);
});
test('numeric SQL strings are converted and missing usage stays a recorded-only total',()=>{
 const v=usageRow({model_id,calls:'2',input_tokens:'100',output_tokens:null});assert.equal(v.averageTokens,50);assert.equal(v.calls,2);
});
