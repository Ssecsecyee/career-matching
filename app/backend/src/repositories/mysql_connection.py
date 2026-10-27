"""DB connections require explicit settings; no credentials are embedded."""
import os


def connect_mysql(*, credentials=None):
    import pymysql
    host = os.getenv("MYSQL_HOST")
    from src.repositories.aws_secrets import database_credentials
    user, password = credentials if credentials is not None else database_credentials()
    database = os.getenv("MYSQL_DATABASE")
    if not all((host, user, password, database)):
        raise RuntimeError("Configure MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
    options = {}
    if host not in {"localhost", "127.0.0.1", "::1"}:
        ca = os.getenv("MYSQL_SSL_CA")
        if not ca:
            raise RuntimeError("Remote MySQL requires MYSQL_SSL_CA")
        options.update(ssl_ca=ca, ssl_verify_cert=True, ssl_verify_identity=True)
    return pymysql.connect(host=host, port=int(os.getenv("MYSQL_PORT", "3306")),
                           user=user, password=password, database=database,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=5, read_timeout=10, write_timeout=10,
                           autocommit=True, init_command="SET time_zone='+00:00'", **options)
