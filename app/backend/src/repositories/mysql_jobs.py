"""Read-only DB-API adapter for the prepared job_postings schema."""
import json


JSON_FIELDS = {"tech_stacks", "addresses", "original_categories", "field_status"}
SUMMARY_FIELDS = ("job_id", "source", "source_id", "source_url", "title", "company_name",
                  "tech_stacks", "addresses", "recruitment_status", "source_version", "last_seen_at")
DETAIL_FIELDS = SUMMARY_FIELDS + ("responsibilities", "qualifications", "preferred_requirements",
                                  "benefits", "hiring_process", "application_notes", "service_info",
                                  "original_categories", "field_status", "deadline_at", "deadline_type")


def literal_like(value):
    return "%" + value.replace("=", "==").replace("%", "=%").replace("_", "=_") + "%"


def decode_row(row):
    row = dict(row)
    for name in JSON_FIELDS:
        if isinstance(row.get(name), (str, bytes)):
            row[name] = json.loads(row[name])
    for name in ("last_seen_at",):
        value = row.get(name)
        if hasattr(value, "isoformat"):
            # MySQL DATETIME stores UTC by application convention.
            row[name] = value.isoformat() + "Z"
    row["status_basis"] = "stored_database_snapshot"
    return row


class MySQLJobRepository:
    def __init__(self, connection_factory, *, include_unverified=False):
        self.connection_factory = connection_factory
        self.include_unverified = include_unverified

    def search(self, plan):
        conditions = ["source=%s", "recruitment_status IN (%s" + (",%s" if self.include_unverified else "") + ")",
                      "(deadline_type='always_open' OR deadline_at IS NULL OR deadline_at>UTC_TIMESTAMP(6))"]
        parameters = ["jumpit", "active"] + (["unknown"] if self.include_unverified else [])
        if plan.keyword:
            conditions.append("LOWER(CONCAT_WS(' ',title,company_name,responsibilities,qualifications,preferred_requirements,CAST(COALESCE(tech_stacks,JSON_ARRAY()) AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci)) LIKE LOWER(%s) ESCAPE '='")
            parameters.append(literal_like(plan.keyword))
        if plan.region:
            conditions.append("CONCAT_WS(' ',CAST(addresses AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci,location_text) LIKE %s ESCAPE '='")
            parameters.append(literal_like(plan.region))
        for skill in plan.skills:
            conditions.append("JSON_CONTAINS(LOWER(CAST(COALESCE(tech_stacks,JSON_ARRAY()) AS CHAR CHARACTER SET utf8mb4)),JSON_QUOTE(LOWER(%s)))")
            parameters.append(skill)
        where = " AND ".join(conditions)
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM job_postings WHERE " + where, parameters)
                total = int(cursor.fetchone()["total"])
                cursor.execute("SELECT " + ",".join(SUMMARY_FIELDS) + " FROM job_postings WHERE " + where +
                               " ORDER BY published_at DESC,job_id DESC LIMIT %s", parameters + [plan.limit])
                rows = [decode_row(row) for row in cursor.fetchall()]
            return total, rows
        finally:
            connection.close()

    def search_details(self, source_ids):
        """Read current selectable rows in bounded batches, no DB writes."""
        if len(source_ids)>1000 or any(not isinstance(i,str) or not i.isdigit() or len(i)>128 for i in source_ids):
            raise ValueError('invalid_candidate_ids')
        if not source_ids:return {}
        connection=self.connection_factory()
        rows={}
        try:
            with connection.cursor() as cursor:
                for start in range(0,len(source_ids),100):
                    identities=source_ids[start:start+100]
                    statuses=['active','unknown'] if self.include_unverified else ['active']
                    sql=('SELECT '+','.join(DETAIL_FIELDS)+' FROM job_postings WHERE source=%s AND source_id IN ('+
                         ','.join(['%s']*len(identities))+') AND recruitment_status IN ('+','.join(['%s']*len(statuses))+') '+
                         "AND (deadline_type='always_open' OR deadline_at IS NULL OR deadline_at>UTC_TIMESTAMP(6))")
                    cursor.execute(sql,['jumpit']+identities+statuses)
                    for row in cursor.fetchall():
                        row=decode_row(row)
                        rows[row['source_id']]=row
            return rows
        finally:connection.close()

    def get(self, source_id):
        if not isinstance(source_id, str) or not source_id.isdigit() or len(source_id) > 128:
            raise ValueError("Invalid source ID")
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT " + ",".join(DETAIL_FIELDS) +
                               " FROM job_postings WHERE source=%s AND source_id=%s", ("jumpit", source_id))
                row = cursor.fetchone()
            return decode_row(row) if row else None
        finally:
            connection.close()



