import test from 'node:test';
import assert from 'node:assert/strict';
import {createAssessmentDraft,chooseAssessment,explainAssessment,moveAssessment,assessmentReady,assessmentPayload} from './assessmentDraft.js';
const questions=[{question_id:'required:1'},{question_id:'required:2'},{question_id:'required:3'}];
test('unanswered conditions are not silently assessed and cannot be submitted',()=>{
 const v=createAssessmentDraft(questions);assert.equal(moveAssessment(v,1),v);assert.equal(assessmentReady(v),false);assert.throws(()=>assessmentPayload(v));
});
test('previous/next keep answers and explanation, and edits replace the same condition',()=>{
 let v=chooseAssessment(createAssessmentDraft(questions),'required:1','met');v=explainAssessment(v,'required:1','개인 프로젝트 경험');v=moveAssessment(v,1);v=chooseAssessment(v,'required:2','unknown');v=moveAssessment(v,-1);assert.equal(v.index,0);assert.equal(v.details['required:1'],'개인 프로젝트 경험');v=chooseAssessment(v,'required:1','unmet');assert.equal(v.answers['required:1'],'unmet');assert.equal(v.answers['required:2'],'unknown');
});
test('batch payload preserves source order and explicit unknown at the final submit',()=>{
 let v=createAssessmentDraft(questions);v=chooseAssessment(v,'required:3','unknown');v=chooseAssessment(v,'required:1','met');v=chooseAssessment(v,'required:2','unmet');v=explainAssessment(v,'required:2','실무 경력 없음');assert.equal(assessmentReady(v),true);assert.deepEqual(assessmentPayload(v),[{question_id:'required:1',assessment:'met',detail:''},{question_id:'required:2',assessment:'unmet',detail:'실무 경력 없음'},{question_id:'required:3',assessment:'unknown',detail:''}]);
});
test('new question group has a fresh draft and invalid ids or answers are rejected',()=>{
 const a=chooseAssessment(createAssessmentDraft(questions),'required:1','met');const b=createAssessmentDraft([{question_id:'preferred:1'}]);assert.deepEqual(b.answers,{});assert.throws(()=>chooseAssessment(a,'preferred:1','met'));assert.throws(()=>chooseAssessment(a,'required:1','yes'));assert.throws(()=>explainAssessment(a,'required:1','x'.repeat(301)));assert.throws(()=>createAssessmentDraft([questions[0],questions[0]]));
});
test('navigation stays inside a single condition group including one-item groups',()=>{
 const a=chooseAssessment(createAssessmentDraft([{question_id:'one'}]),'one','unknown');assert.equal(moveAssessment(a,1).index,0);assert.equal(moveAssessment(a,-1).index,0);assert.equal(assessmentPayload(a).length,1);
});
