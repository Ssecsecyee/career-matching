-- Derived AI classification only. Run after backup with an authorized DDL account.
CREATE TABLE IF NOT EXISTS job_condition_reviews (
  review_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id BIGINT UNSIGNED NOT NULL,
  source_version BIGINT UNSIGNED NOT NULL,
  condition_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  policy_version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  parser_version VARCHAR(40) NOT NULL,
  model_id VARCHAR(256) NOT NULL,
  region VARCHAR(60) NOT NULL,
  classification JSON NOT NULL,
  model_usage JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (review_id),
  UNIQUE KEY uq_condition_review (job_id,condition_hash,policy_version),
  CONSTRAINT fk_condition_review_job FOREIGN KEY (job_id) REFERENCES job_postings(job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
