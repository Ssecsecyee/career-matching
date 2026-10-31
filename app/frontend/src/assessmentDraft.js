export const assessmentLabels = {met:'충족해요',unmet:'미충족이에요',unknown:'아직 모르겠어요'};
const hasAnswer = value => Object.hasOwn(assessmentLabels,value);

export function createAssessmentDraft(questions) {
 const ids=questions.map(q=>q.question_id);
 if(!ids.length||new Set(ids).size!==ids.length||ids.some(id=>typeof id!=='string'||!id))throw new Error('Invalid question group');
 return {ids,index:0,answers:{},details:{}};
}
export function chooseAssessment(draft,id,value) {
 if(!draft.ids.includes(id)||!hasAnswer(value))throw new Error('Invalid answer');
 return {...draft,answers:{...draft.answers,[id]:value}};
}
export function explainAssessment(draft,id,text) {
 if(!draft.ids.includes(id)||typeof text!=='string'||text.length>300)throw new Error('Invalid explanation');
 return {...draft,details:{...draft.details,[id]:text}};
}
export function moveAssessment(draft,direction) {
 if(direction!==1&&direction!==-1)throw new Error('Invalid navigation');
 if(direction===1&&!hasAnswer(draft.answers[draft.ids[draft.index]]))return draft;
 return {...draft,index:Math.max(0,Math.min(draft.ids.length-1,draft.index+direction))};
}
export function assessmentReady(draft){return draft.ids.every(id=>hasAnswer(draft.answers[id]));}
export function assessmentPayload(draft){
 if(!assessmentReady(draft))throw new Error('Finish the group before submitting');
 return draft.ids.map(question_id=>({question_id,assessment:draft.answers[question_id],detail:draft.details[question_id]||''}));
}
