-- Selected-job question presentation cache. No ES projection or user assessment.
CREATE TABLE IF NOT EXISTS job_condition_question_cache (
 cache_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 job_id BIGINT UNSIGNED NOT NULL,
 source_version BIGINT UNSIGNED NOT NULL,
 condition_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 review_policy VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 source_snapshot JSON NOT NULL,
 classification JSON NOT NULL,
 model_usage JSON NOT NULL,
 validation_level VARCHAR(40) NOT NULL DEFAULT 'source_contract_only',
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uq_condition_question_cache (job_id,condition_hash,review_policy),
 CONSTRAINT fk_condition_question_cache_job FOREIGN KEY (job_id) REFERENCES job_postings(job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
