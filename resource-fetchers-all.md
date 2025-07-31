# Resource Fetchers Package - All AWS service inventory modules

This file contains all the resource fetcher modules. Create a folder called `resource_fetchers` and save each module as a separate .py file as shown below:

## Directory Structure:
```
resource_fetchers/
├── __init__.py (empty file)
├── ec2.py
├── s3.py  
├── lambda_.py
├── rds.py
├── dynamodb.py
├── glue.py
├── eventbridge.py
├── stepfunctions.py
├── securityhub.py
└── config.py
```

---

## resource_fetchers/ec2.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["InstanceId", "NameTag", "State", "LaunchTime", "InstanceType", "VPC", "Region", "Arn"]

def collect(session, account_id, region):
    """Collect EC2 instance information"""
    rows = []
    try:
        ec2 = session.client("ec2", region_name=region)
        paginator = ec2.get_paginator("describe_instances")
        
        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    # Get Name tag
                    name_tag = ""
                    for tag in instance.get("Tags", []):
                        if tag.get("Key") == "Name":
                            name_tag = tag.get("Value", "")
                            break
                    
                    # Build ARN
                    arn = f"arn:aws:ec2:{region}:{account_id}:instance/{instance['InstanceId']}"
                    
                    rows.append([
                        instance["InstanceId"],
                        name_tag,
                        instance["State"]["Name"],
                        instance["LaunchTime"].strftime("%Y-%m-%d %H:%M:%S"),
                        instance.get("InstanceType", ""),
                        instance.get("VpcId", ""),
                        region,
                        arn
                    ])
                    
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"EC2 collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/s3.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["Bucket", "Region", "CreationDate", "Versioning", "PublicAccess", "Arn"]

def collect(session, account_id, region):
    """Collect S3 bucket information - region parameter ignored as S3 is global"""
    rows = []
    try:
        s3 = session.client("s3")
        
        # List all buckets
        response = s3.list_buckets()
        buckets = response.get("Buckets", [])
        
        for bucket in buckets:
            bucket_name = bucket["Name"]
            creation_date = bucket["CreationDate"].strftime("%Y-%m-%d")
            
            # Get bucket location
            try:
                location_response = s3.get_bucket_location(Bucket=bucket_name)
                bucket_region = location_response.get("LocationConstraint") or "us-east-1"
            except ClientError:
                bucket_region = "unknown"
            
            # Get versioning status
            try:
                versioning = s3.get_bucket_versioning(Bucket=bucket_name)
                versioning_status = versioning.get("Status", "Disabled")
            except ClientError:
                versioning_status = "unknown"
            
            # Check public access block
            try:
                public_access = s3.get_public_access_block(Bucket=bucket_name)
                is_public = "Blocked" if public_access.get("PublicAccessBlockConfiguration", {}).get("BlockPublicAcls") else "Open"
            except ClientError:
                is_public = "unknown"
            
            arn = f"arn:aws:s3:::{bucket_name}"
            
            rows.append([
                bucket_name,
                bucket_region,
                creation_date,
                versioning_status,
                is_public,
                arn
            ])
            
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"S3 collection error: {str(e)}")
    
    return rows
```

---

## resource_fetchers/lambda_.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["FunctionName", "Runtime", "LastModified", "CodeSize", "Timeout", "MemorySize", "Region", "Arn"]

def collect(session, account_id, region):
    """Collect Lambda function information"""
    rows = []
    try:
        lambda_client = session.client("lambda", region_name=region)
        paginator = lambda_client.get_paginator("list_functions")
        
        for page in paginator.paginate():
            for function in page.get("Functions", []):
                rows.append([
                    function["FunctionName"],
                    function.get("Runtime", ""),
                    function["LastModified"].split("T")[0],  # Date only
                    function.get("CodeSize", 0),
                    function.get("Timeout", 0),
                    function.get("MemorySize", 0),
                    region,
                    function["FunctionArn"]
                ])
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"Lambda collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/rds.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["DBInstanceId", "DBName", "Engine", "EngineVersion", "Status", "InstanceClass", "AllocatedStorage", "Region", "Arn", "CreatedTime"]

def collect(session, account_id, region):
    """Collect RDS database instance information"""
    rows = []
    try:
        rds = session.client("rds", region_name=region)
        paginator = rds.get_paginator("describe_db_instances")
        
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                rows.append([
                    db["DBInstanceIdentifier"],
                    db.get("DBName", ""),
                    db["Engine"],
                    db.get("EngineVersion", ""),
                    db["DBInstanceStatus"],
                    db.get("DBInstanceClass", ""),
                    db.get("AllocatedStorage", 0),
                    region,
                    db["DBInstanceArn"],
                    db["InstanceCreateTime"].strftime("%Y-%m-%d %H:%M:%S")
                ])
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"RDS collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/dynamodb.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["TableName", "Status", "ItemCount", "TableSize", "BillingMode", "Region", "Arn", "CreationDate"]

def collect(session, account_id, region):
    """Collect DynamoDB table information"""
    rows = []
    try:
        dynamodb = session.client("dynamodb", region_name=region)
        paginator = dynamodb.get_paginator("list_tables")
        
        for page in paginator.paginate():
            for table_name in page.get("TableNames", []):
                try:
                    # Get detailed table information
                    response = dynamodb.describe_table(TableName=table_name)
                    table = response["Table"]
                    
                    rows.append([
                        table["TableName"],
                        table["TableStatus"],
                        table.get("ItemCount", 0),
                        table.get("TableSizeBytes", 0),
                        table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
                        region,
                        table["TableArn"],
                        table["CreationDateTime"].strftime("%Y-%m-%d %H:%M:%S")
                    ])
                except ClientError as e:
                    if e.response['Error']['Code'] not in ['ResourceNotFoundException']:
                        continue
                        
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"DynamoDB collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/glue.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["JobName", "JobType", "GlueVersion", "Role", "MaxCapacity", "CreatedOn", "Region", "Description"]

def collect(session, account_id, region):
    """Collect AWS Glue job information"""
    rows = []
    try:
        glue = session.client("glue", region_name=region)
        paginator = glue.get_paginator("get_jobs")
        
        for page in paginator.paginate():
            for job in page.get("Jobs", []):
                rows.append([
                    job["Name"],
                    job.get("Role", "").split("/")[-1] if job.get("Role") else "",  # Job type from role
                    job.get("GlueVersion", ""),
                    job.get("Role", ""),
                    job.get("MaxCapacity", 0),
                    job["CreatedOn"].strftime("%Y-%m-%d %H:%M:%S"),
                    region,
                    job.get("Description", "")
                ])
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"Glue collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/eventbridge.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["RuleName", "State", "Description", "ScheduleExpression", "EventPattern", "Region", "Arn"]

def collect(session, account_id, region):
    """Collect EventBridge rules information"""
    rows = []
    try:
        events = session.client("events", region_name=region)
        paginator = events.get_paginator("list_rules")
        
        for page in paginator.paginate():
            for rule in page.get("Rules", []):
                rows.append([
                    rule["Name"],
                    rule["State"],
                    rule.get("Description", ""),
                    rule.get("ScheduleExpression", ""),
                    rule.get("EventPattern", ""),
                    region,
                    rule["Arn"]
                ])
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"EventBridge collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/stepfunctions.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["StateMachineName", "Type", "Status", "RoleArn", "CreationDate", "Region", "Arn"]

def collect(session, account_id, region):
    """Collect Step Functions state machine information"""
    rows = []
    try:
        sfn = session.client("stepfunctions", region_name=region)
        paginator = sfn.get_paginator("list_state_machines")
        
        for page in paginator.paginate():
            for state_machine in page.get("stateMachines", []):
                rows.append([
                    state_machine["name"],
                    state_machine["type"],
                    "ACTIVE",  # State machines in list are active
                    state_machine.get("roleArn", ""),
                    state_machine["creationDate"].strftime("%Y-%m-%d %H:%M:%S"),
                    region,
                    state_machine["stateMachineArn"]
                ])
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"Step Functions collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/securityhub.py
```python
import boto3
from botocore.exceptions import ClientError

HEADERS = ["FindingId", "ProductArn", "SeverityLabel", "ResourceType", "ResourceId", "Title", "WorkflowStatus", "Region", "CreatedAt", "UpdatedAt"]

def collect(session, account_id, region):
    """Collect Security Hub findings information"""
    rows = []
    try:
        securityhub = session.client("securityhub", region_name=region)
        
        # Check if Security Hub is enabled
        try:
            securityhub.describe_hub()
        except ClientError as e:
            if e.response['Error']['Code'] in ['InvalidAccessException', 'BadRequestException']:
                return rows  # Security Hub not enabled, return empty
            raise
        
        paginator = securityhub.get_paginator("get_findings")
        
        # Get only ACTIVE findings to reduce volume
        filters = {
            "RecordState": [{"Value": "ACTIVE", "Comparison": "EQUALS"}]
        }
        
        for page in paginator.paginate(
            Filters=filters,
            PaginationConfig={"PageSize": 100}
        ):
            for finding in page.get("Findings", []):
                # Get primary resource (first one)
                primary_resource = finding.get("Resources", [{}])[0]
                
                rows.append([
                    finding["Id"],
                    finding["ProductArn"],
                    finding["Severity"]["Label"],
                    primary_resource.get("Type", ""),
                    primary_resource.get("Id", ""),
                    finding["Title"],
                    finding.get("Workflow", {}).get("Status", "NEW"),
                    region,
                    finding["CreatedAt"][:19],  # Remove timezone info
                    finding["UpdatedAt"][:19]   # Remove timezone info
                ])
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied', 'InvalidAccessException']:
            raise
    except Exception as e:
        raise Exception(f"Security Hub collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/config.py
```python
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

HEADERS = ["ResourceType", "ResourceId", "ResourceName", "AvailabilityZone", "Region", "ConfigurationItemStatus", "DiscoveredTime"]

# Common resource types to discover - add more as needed
RESOURCE_TYPES = [
    "AWS::EC2::Instance",
    "AWS::EC2::VPC", 
    "AWS::EC2::SecurityGroup",
    "AWS::S3::Bucket",
    "AWS::RDS::DBInstance",
    "AWS::Lambda::Function"
]

def collect(session, account_id, region):
    """Collect AWS Config discovered resources information"""
    rows = []
    try:
        config = session.client("config", region_name=region)
        
        # Check if Config is enabled
        try:
            config.describe_configuration_recorders()
        except ClientError as e:
            if e.response['Error']['Code'] in ['NoSuchConfigurationRecorderException']:
                return rows  # Config not enabled, return empty
            raise
        
        for resource_type in RESOURCE_TYPES:
            try:
                paginator = config.get_paginator("list_discovered_resources")
                for page in paginator.paginate(
                    resourceType=resource_type,
                    limit=1000
                ):
                    for resource in page.get("resourceIdentifiers", []):
                        rows.append([
                            resource["resourceType"],
                            resource["resourceId"],
                            resource.get("resourceName", ""),
                            resource.get("availabilityZone", ""),
                            region,
                            "ResourceDiscovered",
                            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                        ])
            except ClientError as e:
                # Skip resource types that aren't supported in this region
                if e.response['Error']['Code'] in ['ValidationException']:
                    continue
                raise
                
    except ClientError as e:
        if e.response['Error']['Code'] not in ['UnauthorizedOperation', 'AccessDenied']:
            raise
    except Exception as e:
        raise Exception(f"Config collection error in {region}: {str(e)}")
    
    return rows
```

---

## resource_fetchers/__init__.py
```python
# Empty file to make this directory a Python package
```

---

## Quick Setup Script
Save this as `setup_fetchers.py` and run it to create all the files:

```python
import os

# Create resource_fetchers directory
os.makedirs("resource_fetchers", exist_ok=True)

# Create __init__.py
with open("resource_fetchers/__init__.py", "w") as f:
    f.write("# Empty file to make this directory a Python package\n")

print("Created resource_fetchers package structure")
print("Now copy each module's code from above into separate .py files")
```