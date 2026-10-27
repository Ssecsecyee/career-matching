import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4

from src.handlers.queued import handle,job_response
import worker

class Store:
    def __init__(self):self.rows={}
    def create(self,row):
        if row['job_id'] in self.rows:return False
        self.rows[row['job_id']]=copy.deepcopy(row)
        return True
    def get(self,identity):return copy.deepcopy(self.rows.get(identity))
    def complete(self,identity,result):
        self.rows[identity].update(state='done',response_json=json.dumps(result))

class QueuedTests(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.queue=MagicMock()
        self.auth=('owner-one','client-token-one')
        self.payload={'action':'search','request_id':str(uuid4()),'search_plan':{'skills':['Python']}}
        self.env=patch.dict(os.environ,{'WORK_QUEUE_URL':'test-only','CHAT_API_TOKEN':'fixture-secret'})
        self.env.start()
    def tearDown(self):self.env.stop()
    def request(self,payload=None,path='/api/chat',method='POST',owner=None):
        event={'requestContext':{'http':{'method':method,'path':path}},'body':json.dumps(payload or self.payload)}
        return handle(event,store=self.store,queue=self.queue,auth=owner or self.auth)
    def test_duplicates_do_not_enqueue_or_call_model_twice(self):
        first=self.request()
        self.assertEqual(first['statusCode'],202)
        self.assertEqual(self.request()['statusCode'],202)
        self.assertEqual(self.queue.send_message.call_count,1)
        self.assertNotIn('fixture-secret',self.queue.send_message.call_args.kwargs['MessageBody'])
        identity=json.loads(first['body'])['job_id']
        handler=MagicMock(return_value={'statusCode':200,'headers':{},'body':'{"stage":"choose_job"}'})
        msg={'Body':json.dumps({'job_id':identity})}
        worker.process(msg,self.store,handler=handler)
        worker.process(msg,self.store,handler=handler)
        handler.assert_called_once()
        result=self.request(path='/api/jobs/'+identity,method='GET')
        self.assertEqual(json.loads(result['body'])['stage'],'choose_job')
    def test_polling_is_scoped_to_original_client_owner(self):
        identity=json.loads(self.request()['body'])['job_id']
        result=self.request(path='/api/jobs/'+identity,method='GET',owner=('another-owner','another-token'))
        self.assertEqual(result['statusCode'],404)
    def test_request_id_cannot_be_reused_for_different_content(self):
        self.request()
        changed=dict(self.payload,search_plan={'skills':['Java']})
        self.assertEqual(self.request(changed)['statusCode'],409)
        self.assertEqual(self.queue.send_message.call_count,1)
    def test_expired_jobs_cannot_be_read(self):
        identity=json.loads(self.request()['body'])['job_id']
        row=self.store.rows[identity]
        row['expires_at']=int(time.time())-1
        self.assertEqual(job_response(row,self.auth[0])['statusCode'],410)
    def test_failed_submission_does_not_remain_permanently_queued(self):
        self.queue.send_message.side_effect=RuntimeError('fixture failure')
        self.assertEqual(self.request()['statusCode'],503)
        self.assertEqual(next(iter(self.store.rows.values()))['state'],'done')
    def test_invalid_payload_and_unknown_routes_are_rejected(self):
        self.assertEqual(self.request(dict(self.payload,action='arbitrary'))['statusCode'],400)
        self.assertEqual(self.request(path='/api/jobs/not-a-valid-id',method='GET')['statusCode'],404)
        self.queue.send_message.assert_not_called()
    def test_existing_lease_does_not_drop_or_complete_work(self):
        identity=json.loads(self.request()['body'])['job_id']
        handler=MagicMock(return_value={'statusCode':409,'headers':{},'body':'{"status":"session_busy_retry_later"}'})
        with self.assertRaises(RuntimeError):worker.process({'Body':json.dumps({'job_id':identity})},self.store,handler=handler)
        self.assertEqual(self.store.rows[identity]['state'],'queued')

class BackendTemplateTests(unittest.TestCase):
    def load(self,name):
        root=Path(__file__).resolve().parents[3]/'infra'
        with patch.object(sys,'path',[str(root)]+sys.path):
            spec=importlib.util.spec_from_file_location(name,root/(name+'.py'))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    def test_worker_has_no_inbound_ports_and_preserves_database_disk(self):
        t=self.load('backend_template').backend_template()
        types={r['Type'] for r in t['Resources'].values()}
        self.assertFalse(types & {'AWS::RDS::DBInstance','AWS::EC2::NatGateway','AWS::EC2::VPCEndpoint'})
        security=t['Resources']['WorkerSecurity']['Properties']
        self.assertEqual(security['SecurityGroupIngress'],[])
        launch=t['Resources']['LaunchTemplate']['Properties']['LaunchTemplateData']
        self.assertTrue(launch['BlockDeviceMappings'][0]['Ebs']['Encrypted'])
        self.assertFalse(launch['BlockDeviceMappings'][0]['Ebs']['DeleteOnTermination'])
        self.assertEqual(launch['MetadataOptions']['HttpTokens'],'required')
        self.assertEqual(t['Resources']['Worker']['DeletionPolicy'],'Retain')
    def test_connected_hosting_forwards_headers_and_never_caches_api(self):
        module=self.load('hosting')
        t=module.hosting_template('https://example.execute-api.ap-northeast-2.amazonaws.com')
        cfg=t['Resources']['Distribution']['Properties']['DistributionConfig']
        self.assertEqual(len(cfg['Origins']),2)
        self.assertEqual(cfg['CacheBehaviors'][0]['CachePolicyId'],'4135ea2d-6df8-44a3-9df3-4b5a84be39ad')
        with self.assertRaises(ValueError):module.validate_origin('http://127.0.0.1:8020')
        with self.assertRaises(ValueError):module.validate_origin('https://attacker.example')

    def test_each_sqs_resource_policy_targets_exactly_its_attached_queue(self):
        t=self.load('backend_template').backend_template()
        policies=[r['Properties'] for r in t['Resources'].values() if r['Type']=='AWS::SQS::QueuePolicy']
        self.assertEqual(len(policies),2)
        targets=set()
        for policy in policies:
            self.assertEqual(len(policy['Queues']),1)
            target=policy['Queues'][0]['Ref']
            targets.add(target)
            for statement in policy['PolicyDocument']['Statement']:
                self.assertEqual(statement['Resource'],{'Fn::GetAtt':[target,'Arn']})
                self.assertEqual(statement['Effect'],'Deny')
                self.assertEqual(statement['Condition'],{'Bool':{'aws:SecureTransport':'false'}})
        self.assertEqual(targets,{'WorkQueue','DeadLetters'})
