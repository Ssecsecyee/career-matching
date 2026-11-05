import React from 'react';
export function TrainingExplainButton({ course, active, busy, onExplain }) {
  return <button disabled={!active || busy} onClick={()=>onExplain(course)}>이 교육 설명해줘</button>;
}
