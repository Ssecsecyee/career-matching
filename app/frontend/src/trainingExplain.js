export function trainingExplainRequest(course) {
  return { action: 'explain_training', values: { source: course.source, source_id: course.source_id, source_version: String(course.source_version) },
    label: `${course.provider_name || ''} · ${course.title} 교육을 설명해줘.` };
}
