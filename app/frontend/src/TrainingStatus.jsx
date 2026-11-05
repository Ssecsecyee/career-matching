import React from 'react';

export function TrainingStatus({ course }) {
  return <span className="pill">{course.schedule_label || '일정 미확인'} · {course.recruitment_label || '모집 여부 미확인'}</span>;
}
