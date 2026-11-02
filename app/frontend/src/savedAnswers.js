const assessments = new Set(['met','unmet','unknown']);
export function savedAnswersRequest(offset=0) {
  if (!Number.isInteger(offset) || offset < 0 || offset > 1000 || offset % 10) throw new Error('답변 페이지를 다시 선택해 주세요.');
  return {action:'review_answers',values:{offset}};
}
export function reviseSavedAnswer(item, assessment, detail, review) {
  if (!item?.editable || !item.condition_id || !assessments.has(assessment) || typeof detail !== 'string' || detail.length > 2000 || !/^[a-f0-9]{64}$/.test(review?.review_version)) throw new Error('저장한 답변을 새로 조회한 뒤 수정해 주세요.');
  savedAnswersRequest(review.offset);
  return {action:'revise_answer',values:{condition_id:item.condition_id,assessment,detail,review_version:review.review_version,offset:review.offset}};
}
