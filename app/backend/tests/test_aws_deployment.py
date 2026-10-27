"""Offline deployment wiring tests; never creates SDK clients or calls AWS."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from src.handlers.bootstrap import sql_statements
from src.handlers.cloud import lambda_handler, inspect_handler
from src.repositories.mysql_connection import connect_mysql
from src.repositories.aws_secrets import read_secret, _cache

class AwsDeploymentTests(unittest.TestCase):
    def test_health_and_unknown_routes_do_not_load_secrets_or_call_model(self):
        with patch('src.handlers.cloud.configure_chat') as configure:
            event={'requestContext':{'http':{'method':'GET','path':'/api/health'}}}
            self.assertEqual(lambda_handler(event,None)['statusCode'],200)
            event['requestContext']['http']['path']='/api/unknown'
            self.assertEqual(lambda_handler(event,None)['statusCode'],404)
            configure.assert_not_called()

    def test_chat_configures_secret_then_uses_authenticated_handler(self):
        event={'requestContext':{'http':{'method':'POST','path':'/api/chat'}}}
        with patch('src.handlers.cloud.configure_chat') as configure, patch('src.handlers.cloud.dialogue_handler',return_value={'statusCode':401}) as dialogue:
            self.assertEqual(lambda_handler(event,None)['statusCode'],401)
            configure.assert_called_once()
            dialogue.assert_called_once_with(event,None)

    def test_inspection_rejects_arbitrary_sql(self):
        with patch('src.handlers.cloud.connect_mysql') as connection:
            self.assertEqual(inspect_handler({'action':'query','sql':'SELECT secret'},None)['status'],'invalid_inspection_request')
            connection.assert_not_called()

    def test_sql_parser_preserves_semicolons_and_escaped_quotes_inside_literals(self):
        rows=list(sql_statements("-- ignored;\nCREATE TABLE x(a TEXT COMMENT 'AND;OR'); INSERT INTO x VALUES('a;\\\'b');"))
        self.assertEqual(len(rows),2)
        self.assertIn("COMMENT 'AND;OR'",rows[0])
        self.assertIn("'a;\\\'b'",rows[1])

    def test_secret_cache_reuses_successful_read_without_exposing_values(self):
        _cache.clear()
        with patch('src.repositories.aws_secrets.secrets_client') as factory:
            factory.return_value.get_secret_value.return_value={'SecretString':json.dumps({'username':'fixture','password':'fixture-only'})}
            self.assertEqual(read_secret('test-only')['username'],'fixture')
            read_secret('test-only')
            self.assertEqual(factory.return_value.get_secret_value.call_count,1)
        _cache.clear()

    def test_remote_mysql_requires_identity_verification_and_secret_credentials(self):
        env={'MYSQL_HOST':'example.rds.amazonaws.com','MYSQL_DATABASE':'career_matching','MYSQL_SSL_CA':'/var/task/certs/rds-global.pem','MYSQL_SECRET_ARN':'test-only'}
        with patch.dict(os.environ,env), patch('src.repositories.aws_secrets.read_secret',return_value={'username':'fixture','password':'fixture-only'}), patch('pymysql.connect') as connection:
            connect_mysql()
            options=connection.call_args.kwargs
            self.assertTrue(options['ssl_verify_identity'])
            self.assertTrue(options['ssl_verify_cert'])
            self.assertEqual(options['user'],'fixture')

    def test_template_keeps_database_private_secrets_outside_code_and_api_uncached(self):
        root=Path(__file__).resolve().parents[3]
        spec=importlib.util.spec_from_file_location('template_generator',root/'infra/generate_template.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        t=module.template()
        resources=t['Resources']
        self.assertFalse(resources['Database']['Properties']['PubliclyAccessible'])
        self.assertTrue(resources['Database']['Properties']['StorageEncrypted'])
        self.assertEqual(resources['Database']['DeletionPolicy'],'Retain')
        self.assertNotIn('MYSQL_PASSWORD',resources['ApiFunction']['Properties']['Environment']['Variables'])
        self.assertEqual(resources['BootstrapFunction']['Condition'],'WithBootstrap')
        behavior=resources['Distribution']['Properties']['DistributionConfig']['CacheBehaviors'][0]
        self.assertEqual(behavior['CachePolicyId'],'4135ea2d-6df8-44a3-9df3-4b5a84be39ad')
        self.assertFalse(any(r['Type']=='AWS::EC2::NatGateway' for r in resources.values()))
