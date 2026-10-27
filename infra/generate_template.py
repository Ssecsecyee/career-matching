"""Generate a reviewable CloudFormation JSON template; never calls AWS."""
import json
from pathlib import Path

def ref(name): return {'Ref': name}
def sub(text): return {'Fn::Sub': text}
def att(name, key): return {'Fn::GetAtt': [name, key]}

def template():
    resources = {}
    def add(name, kind, props, why, retain=False, **extra):
        resources[name] = {'Type': kind, 'Properties': props,
            'Metadata': {'com.aws.cloudformation.Context': {'why': why, 'must': ['No embedded credentials; team test deployment.']}}, **extra}
        if retain: resources[name].update(DeletionPolicy='Retain', UpdateReplacePolicy='Retain')
    add('Vpc','AWS::EC2::VPC',{'CidrBlock':'10.82.0.0/16','EnableDnsSupport':True,'EnableDnsHostnames':True},'Private database and Lambda network.')
    for suffix, cidr, az in [('A','10.82.1.0/24',0),('B','10.82.2.0/24',1)]:
        add('Subnet'+suffix,'AWS::EC2::Subnet',{'VpcId':ref('Vpc'),'CidrBlock':cidr,'MapPublicIpOnLaunch':False,
            'AvailabilityZone':{'Fn::Select':[az,{'Fn::GetAZs':''}]}},'Two AZs required by RDS subnet group; no public routes.')
    add('Routes','AWS::EC2::RouteTable',{'VpcId':ref('Vpc')},'Local routes plus S3 gateway; no NAT gateway.')
    for suffix in ['A','B']:
        add('Route'+suffix,'AWS::EC2::SubnetRouteTableAssociation',{'SubnetId':ref('Subnet'+suffix),'RouteTableId':ref('Routes')},'Private subnet routing.')
    for name, why in [('AppSecurity','Lambda clients'),('DbSecurity','Private MySQL'),('EndpointSecurity','Private service endpoints')]:
        add(name,'AWS::EC2::SecurityGroup',{'GroupDescription':why,'VpcId':ref('Vpc')},why)
    add('DbIngress','AWS::EC2::SecurityGroupIngress',{'GroupId':ref('DbSecurity'),'IpProtocol':'tcp','FromPort':3306,'ToPort':3306,'SourceSecurityGroupId':ref('AppSecurity')},'Only application functions reach MySQL.')
    add('EndpointIngress','AWS::EC2::SecurityGroupIngress',{'GroupId':ref('EndpointSecurity'),'IpProtocol':'tcp','FromPort':443,'ToPort':443,'SourceSecurityGroupId':ref('AppSecurity')},'TLS to private AWS service endpoints.')
    for name, service in [('BedrockEndpoint','bedrock-runtime'),('SecretsEndpoint','secretsmanager')]:
        add(name,'AWS::EC2::VPCEndpoint',{'VpcId':ref('Vpc'),'VpcEndpointType':'Interface','PrivateDnsEnabled':True,
            'ServiceName':sub('com.amazonaws.${AWS::Region}.'+service),'SubnetIds':[ref('SubnetA'),ref('SubnetB')],
            'SecurityGroupIds':[ref('EndpointSecurity')]},'Private service access without NAT; interface ENIs incur hourly charges.')
    add('S3Endpoint','AWS::EC2::VPCEndpoint',{'VpcId':ref('Vpc'),'VpcEndpointType':'Gateway',
        'ServiceName':sub('com.amazonaws.${AWS::Region}.s3'),'RouteTableIds':[ref('Routes')]},'Bootstrap reads its fixed S3 artifacts privately.')
    add('DbSubnets','AWS::RDS::DBSubnetGroup',{'DBSubnetGroupDescription':'Career private subnets','SubnetIds':[ref('SubnetA'),ref('SubnetB')]},'Private RDS subnet group.')
    add('DbParameters','AWS::RDS::DBParameterGroup',{'Description':'MySQL TLS required','Family':'mysql8.4','Parameters':{'require_secure_transport':'1'}},'Require TLS server-side as well as client identity checks.')
    add('Database','AWS::RDS::DBInstance',{'Engine':'mysql','EngineVersion':ref('DbEngineVersion'),'EngineLifecycleSupport':'open-source-rds-extended-support-disabled',
        'DBInstanceClass':'db.t4g.micro','AllocatedStorage':'20','StorageType':'gp3','StorageEncrypted':True,'MultiAZ':False,
        'PubliclyAccessible':False,'DBName':'career_matching','MasterUsername':'career_admin','ManageMasterUserPassword':True,
        'DBSubnetGroupName':ref('DbSubnets'),'DBParameterGroupName':ref('DbParameters'),'VPCSecurityGroups':[ref('DbSecurity')],
        'BackupRetentionPeriod':1,'DeletionProtection':True,'AutoMinorVersionUpgrade':True,'CopyTagsToSnapshot':True},
        'Small Single-AZ team-test database; fixed ongoing cost; retain data on stack deletion.',True)
    for name, username in [('RuntimeSecret','career_runtime'),('AuthSecret',None)]:
        generate={'PasswordLength':48,'ExcludePunctuation':True}
        if username: generate.update(SecretStringTemplate=json.dumps({'username':username}),GenerateStringKey='password')
        else: generate.update(SecretStringTemplate='{}',GenerateStringKey='token')
        add(name,'AWS::SecretsManager::Secret',{'Description':'Career team-test '+name,'GenerateSecretString':generate},'Generated secrets never copied from local .env.',True)
    def role(name, statements, bootstrap=False):
        add(name,'AWS::IAM::Role',{'AssumeRolePolicyDocument':{'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'lambda.amazonaws.com'},'Action':'sts:AssumeRole'}]},
            'ManagedPolicyArns':[sub('arn:${AWS::Partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole')],
            'Policies':[{'PolicyName':'AppAccess','PolicyDocument':{'Version':'2012-10-17','Statement':statements}}]},
            'Function-specific data permissions; ENI permissions required by VPC Lambda.',**({'Condition':'WithBootstrap'} if bootstrap else {}))
    def allow(actions, targets): return {'Effect':'Allow','Action':actions,'Resource':targets}
    secret_access=allow(['secretsmanager:GetSecretValue'],[ref('RuntimeSecret'),ref('AuthSecret')])
    bedrock_access=allow(['bedrock:InvokeModel'],[sub('arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:inference-profile/${ModelId}'),
                                              sub('arn:${AWS::Partition}:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6')])
    role('ApiRole',[secret_access,bedrock_access])
    role('InspectRole',[secret_access])
    role('BootstrapRole',[allow(['secretsmanager:GetSecretValue'],[att('Database','MasterUserSecret.SecretArn'),ref('RuntimeSecret')]),
        allow(['s3:GetObject'],[sub('arn:${AWS::Partition}:s3:::${ArtifactBucket}/${SchemaKey}'),sub('arn:${AWS::Partition}:s3:::${ArtifactBucket}/${DataKey}')])],True)
    common={'MYSQL_HOST':att('Database','Endpoint.Address'),'MYSQL_PORT':'3306','MYSQL_DATABASE':'career_matching',
            'MYSQL_SECRET_ARN':ref('RuntimeSecret'),'CHAT_SECRET_ARN':ref('AuthSecret'),'MYSQL_SSL_CA':'/var/task/certs/rds-global.pem',
            'CHAT_RETENTION_HOURS':'24','CHAT_INCLUDE_UNVERIFIED':'true','CHAT_RUNTIME_ENABLED':'true',
            'ENABLE_LIVE_BEDROCK':'true','MODEL_ID':ref('ModelId'),'BEDROCK_REGION':ref('AWS::Region')}
    def function(name, handler, iam, env, timeout, bootstrap=False):
        add(name,'AWS::Lambda::Function',{'Runtime':'python3.11','Architectures':['x86_64'],'Handler':handler,
            'Code':{'S3Bucket':ref('ArtifactBucket'),'S3Key':ref('CodeKey')},'Role':att(iam,'Arn'),'MemorySize':512,
            'Timeout':timeout,'ReservedConcurrentExecutions':1 if bootstrap else 3,
            'VpcConfig':{'SubnetIds':[ref('SubnetA'),ref('SubnetB')],'SecurityGroupIds':[ref('AppSecurity')]},
            'Environment':{'Variables':env}},'Packaged source only; no .env, local credentials or source snapshots.',
            **({'Condition':'WithBootstrap'} if bootstrap else {}))
        add(name+'Logs','AWS::Logs::LogGroup',{'LogGroupName':sub('/aws/lambda/${'+name+'}'),'RetentionInDays':7},
            'Short metadata-only logs; do not log request or secret bodies.',**({'Condition':'WithBootstrap'} if bootstrap else {}))
    function('ApiFunction','src.handlers.cloud.lambda_handler','ApiRole',common,28)
    function('InspectFunction','src.handlers.cloud.inspect_handler','InspectRole',common,25)
    function('BootstrapFunction','src.handlers.bootstrap.lambda_handler','BootstrapRole',{
        **{k:v for k,v in common.items() if k.startswith('MYSQL_')},'ADMIN_SECRET_ARN':att('Database','MasterUserSecret.SecretArn'),
        'ARTIFACT_BUCKET':ref('ArtifactBucket'),'SCHEMA_KEY':ref('SchemaKey'),'DATA_KEY':ref('DataKey'),
        'SCHEMA_SHA256':ref('SchemaHash'),'DATA_SHA256':ref('DataHash'),'EXPECTED_JOBS':ref('ExpectedJobs')},300,True)
    add('Api','AWS::ApiGatewayV2::Api',{'Name':sub('${AWS::StackName}-api'),'ProtocolType':'HTTP'},'Same-origin CloudFront API; application-level team token authentication.')
    add('Integration','AWS::ApiGatewayV2::Integration',{'ApiId':ref('Api'),'IntegrationType':'AWS_PROXY','IntegrationUri':att('ApiFunction','Arn'),
        'PayloadFormatVersion':'2.0','TimeoutInMillis':29000},'28-second Lambda fits the HTTP API 30-second limit.')
    for name, route in [('ChatRoute','POST /api/chat'),('HealthRoute','GET /api/health')]:
        add(name,'AWS::ApiGatewayV2::Route',{'ApiId':ref('Api'),'RouteKey':route,'Target':{'Fn::Join':['',['integrations/',ref('Integration')]]}},'Only explicit chat and health routes.')
    add('Stage','AWS::ApiGatewayV2::Stage',{'ApiId':ref('Api'),'StageName':'$default','AutoDeploy':True,
        'DefaultRouteSettings':{'ThrottlingBurstLimit':5,'ThrottlingRateLimit':2}},'Conservative team-test API throttling.')
    add('InvokePermission','AWS::Lambda::Permission',{'FunctionName':ref('ApiFunction'),'Action':'lambda:InvokeFunction','Principal':'apigateway.amazonaws.com',
        'SourceAccount':ref('AWS::AccountId'),'SourceArn':sub('arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${Api}/*')},'Only this account API can invoke the HTTP function.')
    add('WebBucket','AWS::S3::Bucket',{'PublicAccessBlockConfiguration':{'BlockPublicAcls':True,'BlockPublicPolicy':True,'IgnorePublicAcls':True,'RestrictPublicBuckets':True},
        'BucketEncryption':{'ServerSideEncryptionConfiguration':[{'ServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]},
        'VersioningConfiguration':{'Status':'Enabled'},'OwnershipControls':{'Rules':[{'ObjectOwnership':'BucketOwnerEnforced'}]}},'Private static website artifacts; CloudFront OAC access only.',True)
    add('Oac','AWS::CloudFront::OriginAccessControl',{'OriginAccessControlConfig':{'Name':sub('${AWS::StackName}-web'),
        'OriginAccessControlOriginType':'s3','SigningBehavior':'always','SigningProtocol':'sigv4'}},'Signed HTTPS access to private S3 origin.')
    add('SecurityHeaders','AWS::CloudFront::ResponseHeadersPolicy',{'ResponseHeadersPolicyConfig':{'Name':sub('${AWS::StackName}-security'),
        'SecurityHeadersConfig':{'ContentTypeOptions':{'Override':True},'FrameOptions':{'FrameOption':'DENY','Override':True},
        'ReferrerPolicy':{'ReferrerPolicy':'strict-origin-when-cross-origin','Override':True},
        'StrictTransportSecurity':{'AccessControlMaxAgeSec':31536000,'Override':True},
        'ContentSecurityPolicy':{'ContentSecurityPolicy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'",'Override':True}}}},'Browser security headers; no third-party script dependency.')
    add('Distribution','AWS::CloudFront::Distribution',{'DistributionConfig':{'Enabled':True,'DefaultRootObject':'index.html','HttpVersion':'http2','PriceClass':'PriceClass_200',
        'ViewerCertificate':{'CloudFrontDefaultCertificate':True},'Origins':[
            {'Id':'web','DomainName':att('WebBucket','RegionalDomainName'),'S3OriginConfig':{'OriginAccessIdentity':''},'OriginAccessControlId':ref('Oac')},
            {'Id':'api','DomainName':{'Fn::Select':[2,{'Fn::Split':['/',att('Api','ApiEndpoint')]}]},'CustomOriginConfig':{'OriginProtocolPolicy':'https-only','OriginSSLProtocols':['TLSv1.2']}}],
        'DefaultCacheBehavior':{'TargetOriginId':'web','ViewerProtocolPolicy':'redirect-to-https','AllowedMethods':['GET','HEAD'],'CachedMethods':['GET','HEAD'],
            'Compress':True,'CachePolicyId':'658327ea-f89d-4fab-a63d-7e88639e58f6','ResponseHeadersPolicyId':ref('SecurityHeaders')},
        'CacheBehaviors':[{'PathPattern':'/api/*','TargetOriginId':'api','ViewerProtocolPolicy':'https-only',
            'AllowedMethods':['GET','HEAD','OPTIONS','PUT','PATCH','POST','DELETE'],'CachedMethods':['GET','HEAD'],
            'CachePolicyId':'4135ea2d-6df8-44a3-9df3-4b5a84be39ad','OriginRequestPolicyId':'b689b0a8-53d0-40ab-baf2-68738e2966ac',
            'ResponseHeadersPolicyId':ref('SecurityHeaders')}]}},'Static assets cached; API authorization/client headers forwarded and API responses never cached.')
    add('WebPolicy','AWS::S3::BucketPolicy',{'Bucket':ref('WebBucket'),'PolicyDocument':{'Version':'2012-10-17','Statement':[
        {'Effect':'Allow','Principal':{'Service':'cloudfront.amazonaws.com'},'Action':'s3:GetObject','Resource':sub('${WebBucket.Arn}/*'),
         'Condition':{'StringEquals':{'AWS:SourceArn':sub('arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${Distribution}')}}},
        {'Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[att('WebBucket','Arn'),sub('${WebBucket.Arn}/*')],
         'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}},'Only this distribution reads website files; reject non-TLS S3 requests.')
    add('Budget','AWS::Budgets::Budget',{'Budget':{'BudgetName':sub('${AWS::StackName}-monthly'),
        'BudgetType':'COST','TimeUnit':'MONTHLY','BudgetLimit':{'Amount':ref('MonthlyBudgetUsd'),'Unit':'USD'}},
        'NotificationsWithSubscribers':[{'Notification':{'NotificationType':'ACTUAL','ComparisonOperator':'GREATER_THAN','Threshold':80,'ThresholdType':'PERCENTAGE'},
            'Subscribers':[{'SubscriptionType':'EMAIL','Address':ref('BudgetEmail')}]}]},'Account-wide spend alert, not a hard spending stop.')
    add('Dashboard','AWS::CloudWatch::Dashboard',{'DashboardName':sub('${AWS::StackName}-usage'),
        'DashboardBody':{'Fn::Sub':json.dumps({'widgets':[{'type':'metric','x':0,'y':0,'width':24,'height':6,'properties':{
            'title':'Bedrock invocation and token usage (account/region view)','region':'${AWS::Region}','period':300,'stat':'Sum',
            'metrics':[['AWS/Bedrock','Invocations'],['AWS/Bedrock','InputTokenCount'],['AWS/Bedrock','OutputTokenCount'],['AWS/Bedrock','InvocationServerErrors']]}}]})}},
        'Provider aggregate metrics; exact application usage also stored in model_invocations.')
    for name in ('Vpc','SubnetA','SubnetB','DbSecurity','DbSubnets','DbParameters'):
        resources[name].update(DeletionPolicy='Retain',UpdateReplacePolicy='Retain')
    params={name:{'Type':'String'} for name in ['ArtifactBucket','CodeKey','SchemaKey','DataKey','SchemaHash','DataHash','DbEngineVersion','BudgetEmail']}
    params.update(ModelId={'Type':'String','Default':'global.anthropic.claude-sonnet-4-6','AllowedValues':['global.anthropic.claude-sonnet-4-6']},
        ExpectedJobs={'Type':'Number','MinValue':1},MonthlyBudgetUsd={'Type':'Number','MinValue':1,'MaxValue':10000},
        EnableBootstrap={'Type':'String','Default':'false','AllowedValues':['true','false']})
    params['DbEngineVersion']['AllowedPattern']=r'8\.4\.\d+'
    outputs={name:{'Value':value} for name,value in {'WebsiteUrl':sub('https://${Distribution.DomainName}'),
        'WebBucket':ref('WebBucket'),'DistributionId':ref('Distribution'),'DbEndpoint':att('Database','Endpoint.Address'),
        'DbIdentifier':ref('Database'),'ApiFunction':ref('ApiFunction'),'InspectFunction':ref('InspectFunction'),
        'AuthSecretArn':ref('AuthSecret'),'RuntimeSecretArn':ref('RuntimeSecret'),'DashboardName':ref('Dashboard')}.items()}
    outputs['BootstrapFunction']={'Condition':'WithBootstrap','Value':ref('BootstrapFunction')}
    return {'AWSTemplateFormatVersion':'2010-09-09','Description':'Career matching team test: private RDS MySQL, Sonnet Lambda, S3/CloudFront. Deploy manually after cost review.',
        'Metadata':{'AWSToolsMetrics':{'AWSAgentToolkit':'aws-cloudformation@3'}},'Parameters':params,
        'Conditions':{'WithBootstrap':{'Fn::Equals':[ref('EnableBootstrap'),'true']}},'Resources':resources,'Outputs':outputs}

if __name__ == '__main__':
    target=Path(__file__).with_name('template.json')
    target.write_text(json.dumps(template(),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Generated {target.name}; no AWS operations.')
