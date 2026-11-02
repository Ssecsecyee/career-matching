-- Quarantined derived extraction. No source writes or ES events on insert.
CREATE TABLE IF NOT EXISTS job_condition_review_drafts (
 draft_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 job_id BIGINT UNSIGNED NOT NULL,
 source_version BIGINT UNSIGNED NOT NULL,
 condition_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 candidate_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 source_snapshot JSON NOT NULL,
 classification JSON NOT NULL,
 model_usage JSON NOT NULL,
 validation_report JSON NULL,
 status ENUM('pending','verified','published','rejected') NOT NULL DEFAULT 'pending',
 review_id BIGINT UNSIGNED NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY uq_condition_draft (job_id,condition_hash,candidate_hash),
 CONSTRAINT fk_condition_draft_job FOREIGN KEY (job_id) REFERENCES job_postings(job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
