CREATE TABLE IF NOT EXISTS admin_audit (
 audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id CHAR(36) NOT NULL,
 actor_scope CHAR(64) NOT NULL,
 fingerprint CHAR(64) NOT NULL,
 action VARCHAR(40) NOT NULL,
 entity_id BIGINT UNSIGNED NOT NULL,
 reason VARCHAR(500) NOT NULL,
 before_value JSON NOT NULL,
 after_value JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uq_admin_request(request_id),
 KEY ix_admin_entity(entity_id,audit_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
