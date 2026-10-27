"""Low-cost team-test backend: no inbound server ports, no NAT/interface endpoints."""
import json
from generate_template import ref, sub, att

def backend_template():
    r={}
    def add(name,kind,props,why,retain=False,**extra):
        r[name]={'Type':kind,'Properties':props,'Metadata':{'com.aws.cloudformation.Context':{'why':why,'must':['Team-test only; no hardcoded credentials or public DB.']}},**extra}
        if retain:r[name].update(DeletionPolicy='Retain',UpdateReplacePolicy='Retain')
    add('Vpc','AWS::EC2::VPC',{'CidrBlock':'10.83.0.0/16','EnableDnsSupport':True,'EnableDnsHostnames':True},'Isolated test network.',True)
    add('Subnet','AWS::EC2::Subnet',{'VpcId':ref('Vpc'),'CidrBlock':'10.83.1.0/24','MapPublicIpOnLaunch':True,
        'AvailabilityZone':{'Fn::Select':[0,{'Fn::GetAZs':''}]}},'Single-AZ outbound worker; public IP used only for outbound AWS/package access.',True)
    add('Gateway','AWS::EC2::InternetGateway',{},'Outbound internet access without a NAT gateway.')
    add('GatewayAttachment','AWS::EC2::VPCGatewayAttachment',{'VpcId':ref('Vpc'),'InternetGatewayId':ref('Gateway')},'Attach outbound path.')
    add('Routes','AWS::EC2::RouteTable',{'VpcId':ref('Vpc')},'Public outbound routing.')
    add('PublicRoute','AWS::EC2::Route',{'RouteTableId':ref('Routes'),'DestinationCidrBlock':'0.0.0.0/0','GatewayId':ref('Gateway')},'Outbound HTTPS only is enforced by worker security group.',DependsOn='GatewayAttachment')
    add('RouteAssociation','AWS::EC2::SubnetRouteTableAssociation',{'SubnetId':ref('Subnet'),'RouteTableId':ref('Routes')},'Worker subnet route.')
    add('WorkerSecurity','AWS::EC2::SecurityGroup',{'VpcId':ref('Vpc'),'GroupDescription':'No inbound; outbound TLS only',
        'SecurityGroupIngress':[],'SecurityGroupEgress':[{'IpProtocol':'tcp','FromPort':443,'ToPort':443,'CidrIp':'0.0.0.0/0','Description':'AWS APIs and package registries over TLS'}]},
        'No SSH, HTTP, MySQL or Elasticsearch inbound ports.',True)
    for name,field,base in [('AuthSecret','token',{}),('DbSecret','password',{'username':'career_runtime'})]:
        add(name,'AWS::SecretsManager::Secret',{'Description':'Career worker '+name,'GenerateSecretString':{
            'SecretStringTemplate':json.dumps(base),'GenerateStringKey':field,'PasswordLength':48,'ExcludePunctuation':True}},'Generated credentials read using roles.',True)
    add('Jobs','AWS::DynamoDB::Table',{'BillingMode':'PAY_PER_REQUEST','AttributeDefinitions':[{'AttributeName':'job_id','AttributeType':'S'}],
        'KeySchema':[{'AttributeName':'job_id','KeyType':'HASH'}],'TimeToLiveSpecification':{'AttributeName':'expires_at','Enabled':True},
        'SSESpecification':{'SSEEnabled':True}},'Owner-scoped temporary jobs only; primary career data stays in MySQL.',True)
    add('DeadLetters','AWS::SQS::Queue',{'SqsManagedSseEnabled':True,'MessageRetentionPeriod':86400},'Bounded retry failures; messages contain job IDs only.')
    add('WorkQueue','AWS::SQS::Queue',{'SqsManagedSseEnabled':True,'VisibilityTimeout':180,'ReceiveMessageWaitTimeSeconds':20,
        'MessageRetentionPeriod':86400,'RedrivePolicy':{'deadLetterTargetArn':att('DeadLetters','Arn'),'maxReceiveCount':3}},'Worker pulls requests, so no inbound EC2 API is exposed.')
    for queue_name in ('WorkQueue','DeadLetters'):
        add(queue_name+'Policy','AWS::SQS::QueuePolicy',{'Queues':[ref(queue_name)],'PolicyDocument':{'Version':'2012-10-17','Statement':[
            {'Effect':'Deny','Principal':'*','Action':'sqs:*','Resource':att(queue_name,'Arn'),
             'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}},'One queue per resource policy; reject non-TLS calls.')
    def allow(actions,resource):return {'Effect':'Allow','Action':actions,'Resource':resource}
    def role(name,service,managed,statements):
        add(name,'AWS::IAM::Role',{'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':service},'Action':'sts:AssumeRole'}]},
            'ManagedPolicyArns':[sub('arn:${AWS::Partition}:iam::aws:policy/'+m) for m in managed],
            'Policies':[{'PolicyName':'CareerAccess','PolicyDocument':{'Version':'2012-10-17','Statement':statements}}]},'Scoped service permissions and role credentials.')
    role('ApiRole','lambda.amazonaws.com',['service-role/AWSLambdaBasicExecutionRole'],[
        allow(['secretsmanager:GetSecretValue'],[ref('AuthSecret')]),allow(['dynamodb:GetItem','dynamodb:PutItem','dynamodb:UpdateItem'],att('Jobs','Arn')),
        allow(['sqs:SendMessage'],att('WorkQueue','Arn'))])
    role('WorkerRole','ec2.amazonaws.com',['AmazonSSMManagedInstanceCore'],[
        allow(['secretsmanager:GetSecretValue'],[ref('AuthSecret'),ref('DbSecret')]),
        allow(['dynamodb:GetItem','dynamodb:UpdateItem'],att('Jobs','Arn')),
        allow(['sqs:ReceiveMessage','sqs:DeleteMessage','sqs:ChangeMessageVisibility'],att('WorkQueue','Arn')),
        allow(['s3:GetObject'],[sub('arn:${AWS::Partition}:s3:::${ArtifactBucket}/${WorkerKey}')]),
        allow(['bedrock:InvokeModel'],[sub('arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:inference-profile/global.anthropic.claude-sonnet-4-6'),
            sub('arn:${AWS::Partition}:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6')])])
    add('Profile','AWS::IAM::InstanceProfile',{'Roles':[ref('WorkerRole')]},'Host role for SSM and Bedrock; containers do not need IMDS.')
    config={'AWS_REGION':'${AWS::Region}','CHAT_SECRET_ARN':'${AuthSecret}','MYSQL_SECRET_ARN':'${DbSecret}',
            'JOBS_TABLE':'${Jobs}','WORK_QUEUE_URL':'${WorkQueue}','EXPECTED_JOBS':'${ExpectedJobs}'}
    user_data='''#!/bin/bash
set -eu
dnf install -y docker python3.11 python3.11-pip
systemctl enable --now docker
install -d -m 755 /opt/career /opt/career/app
python3.11 -m venv /opt/career/venv
/opt/career/venv/bin/pip install 'boto3>=1.36,<2' 'PyMySQL[rsa]>=1.1.1,<2'
cat > /opt/career/config.json <<'CONFIG'
'''+json.dumps(config)+'''
CONFIG
chmod 600 /opt/career/config.json
/opt/career/venv/bin/python - <<'PY'
import boto3,hashlib,io,zipfile
client=boto3.Session(region_name='${AWS::Region}').client('s3')
body=client.get_object(Bucket='${ArtifactBucket}',Key='${WorkerKey}')['Body']
try: data=body.read(40*1024*1024+1)
finally: body.close()
if len(data)>40*1024*1024 or hashlib.sha256(data).hexdigest()!='${WorkerHash}': raise ValueError('Worker artifact mismatch')
with zipfile.ZipFile(io.BytesIO(data)) as archive:
 for name in archive.namelist():
  if name.startswith('/') or '..' in name.split('/'): raise ValueError('Invalid artifact path')
 archive.extractall('/opt/career/app')
PY
cd /opt/career/app
/opt/career/venv/bin/python install_worker.py
'''
    add('LaunchTemplate','AWS::EC2::LaunchTemplate',{'LaunchTemplateData':{'ImageId':ref('AmiId'),'InstanceType':'t4g.small',
        'IamInstanceProfile':{'Name':ref('Profile')},'CreditSpecification':{'CpuCredits':'standard'},
        'MetadataOptions':{'HttpTokens':'required','HttpEndpoint':'enabled','HttpPutResponseHopLimit':1},
        'BlockDeviceMappings':[{'DeviceName':'/dev/xvda','Ebs':{'VolumeSize':30,'VolumeType':'gp3','Encrypted':True,'DeleteOnTermination':False}}],
        'NetworkInterfaces':[{'DeviceIndex':0,'AssociatePublicIpAddress':True,'SubnetId':ref('Subnet'),'Groups':[ref('WorkerSecurity')]}],
        'UserData':{'Fn::Base64':sub(user_data)}}},'2GB ARM host for MySQL and Python worker; no Elasticsearch in initial memory budget.')
    add('Worker','AWS::EC2::Instance',{'LaunchTemplate':{'LaunchTemplateId':ref('LaunchTemplate'),'Version':att('LaunchTemplate','LatestVersionNumber')},
        'DisableApiTermination':True,'Tags':[{'Key':'Name','Value':sub('${AWS::StackName}-worker')}]},
        'Encrypted durable root disk; retain instance on rollback/deletion to avoid destroying conversations.',True,DependsOn=['PublicRoute','RouteAssociation'])
    add('ApiFunction','AWS::Lambda::Function',{'Runtime':'python3.11','Architectures':['x86_64'],'Handler':'src.handlers.queued.lambda_handler',
        'Role':att('ApiRole','Arn'),'Code':{'S3Bucket':ref('ArtifactBucket'),'S3Key':ref('ApiKey')},'Timeout':20,'MemorySize':256,'ReservedConcurrentExecutions':3,
        'Environment':{'Variables':{'CHAT_SECRET_ARN':ref('AuthSecret'),'JOBS_TABLE':ref('Jobs'),'WORK_QUEUE_URL':ref('WorkQueue')}}},'No VPC attachment; enqueues work instead of waiting for a long model response.')
    add('ApiLogs','AWS::Logs::LogGroup',{'LogGroupName':sub('/aws/lambda/${ApiFunction}'),'RetentionInDays':7},'Metadata-only short retention logs.')
    add('Api','AWS::ApiGatewayV2::Api',{'Name':sub('${AWS::StackName}-api'),'ProtocolType':'HTTP'},'HTTPS same-origin API when connected to existing CloudFront.')
    add('Integration','AWS::ApiGatewayV2::Integration',{'ApiId':ref('Api'),'IntegrationType':'AWS_PROXY','IntegrationUri':att('ApiFunction','Arn'),
        'PayloadFormatVersion':'2.0','TimeoutInMillis':25000},'Short async admission/status operations.')
    for name,route in [('Chat','POST /api/chat'),('Job','GET /api/jobs/{job_id}'),('Health','GET /api/health')]:
        add(name+'Route','AWS::ApiGatewayV2::Route',{'ApiId':ref('Api'),'RouteKey':route,'Target':{'Fn::Join':['',['integrations/',ref('Integration')]]}},'Explicit routes only; chat/jobs require owner-scoped token.')
    add('Stage','AWS::ApiGatewayV2::Stage',{'ApiId':ref('Api'),'StageName':'$default','AutoDeploy':True,
        'DefaultRouteSettings':{'ThrottlingBurstLimit':5,'ThrottlingRateLimit':2}},'Low team-test admission rate; API polling uses this budget too.')
    add('Permission','AWS::Lambda::Permission',{'FunctionName':ref('ApiFunction'),'Action':'lambda:InvokeFunction','Principal':'apigateway.amazonaws.com',
        'SourceAccount':ref('AWS::AccountId'),'SourceArn':sub('arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${Api}/*')},'Only this account API invokes the queue handler.')
    params={name:{'Type':'String'} for name in ['ArtifactBucket','WorkerKey','WorkerHash','ApiKey']}
    params.update(AmiId={'Type':'AWS::EC2::Image::Id'},ExpectedJobs={'Type':'Number','MinValue':1})
    return {'AWSTemplateFormatVersion':'2010-09-09','Description':'Low-cost career team-test backend. One outbound-only EC2 worker with MySQL; HTTPS Lambda queue API. No Elasticsearch, RDS, NAT or private endpoints.',
        'Metadata':{'AWSToolsMetrics':{'AWSAgentToolkit':'aws-cloudformation@3'}},'Parameters':params,'Resources':r,
        'Outputs':{name:{'Value':value} for name,value in {'ApiEndpoint':att('Api','ApiEndpoint'),'WorkerInstanceId':ref('Worker'),
        'AuthSecretArn':ref('AuthSecret'),'DbSecretArn':ref('DbSecret'),'JobsTable':ref('Jobs'),'WorkQueueUrl':ref('WorkQueue'),
        'DeadLetterQueue':ref('DeadLetters'),'ApiFunction':ref('ApiFunction')}.items()}}
