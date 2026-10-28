-- DBeaver: select the career_matching database, then run one query with Ctrl+Enter.
SELECT offering_id, provider_name, title, cohort_name, delivery_mode,
       tuition, currency, recruitment_status, source_url
FROM training_offerings
WHERE source = 'boottent'
ORDER BY offering_id;

-- Dates without a verified time are preserved here, not invented as midnight.
SELECT offering_id, title,
       JSON_EXTRACT(additional_sections, '$.date_precision') AS dates,
       JSON_EXTRACT(additional_sections, '$.collection_metadata') AS provenance,
       JSON_EXTRACT(additional_sections, '$.recommendation_eligible') AS recommendation_eligible
FROM training_offerings
WHERE source = 'boottent';

-- Topic lookup for structural verification, including historical courses.
SELECT offering_id, title, learning_topics
FROM training_offerings
WHERE source = 'boottent'
  AND JSON_CONTAINS(learning_topics, JSON_QUOTE('React'));

-- These are pending future search-index events, not proof of an active search engine.
SELECT entity_id, source_version, operation, processed_at
FROM search_outbox
WHERE entity_type = 'training'
ORDER BY event_id DESC
LIMIT 20;
