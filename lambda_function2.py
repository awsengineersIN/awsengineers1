import os
import csv
import json
import importlib
import tempfile
import zipfile
import logging
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.mime.text import MIMEText

from util import assume, account_id_from_name, ou_id_from_name, accounts_in_ou

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGIONS = os.getenv("REGIONS", "us-east-1").split(",")
SENDER = os.getenv("SENDER", None)
MEMBER_ROLE = os.getenv("MEMBER_READ_ROLE", "ResourceReadRole")

# Import your custom send_email function
from your_utils import send_email  # Replace with your actual import

RES_MAP = {
    "EC2": "ec2", "S3": "s3", "Lambda": "lambda_", "RDS": "rds",
    "DynamoDB": "dynamodb", "Glue": "glue", "Eventbridge": "eventbridge",
    "StepFunctions": "stepfunctions", "SecurityHub": "securityhub", "Config": "config"
}

def write_csv(rows, headers, path):
    """Write CSV file with proper error handling"""
    try:
        with open(path, "w", newline="", encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            writer.writerows(rows)
        logger.info(f"CSV written successfully: {path}")
    except Exception as e:
        logger.error(f"Failed to write CSV {path}: {e}")
        raise

def create_zip_archive(file_paths, zip_path):
    """Create ZIP archive from list of file paths"""
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            for file_path in file_paths:
                if os.path.exists(file_path):
                    zipf.write(file_path, Path(file_path).name)
        logger.info(f"ZIP archive created: {zip_path}")
        return os.path.getsize(zip_path)
    except Exception as e:
        logger.error(f"Failed to create ZIP archive: {e}")
        raise

def lambda_handler(event, context):
    """
    Main Lambda handler with enhanced error handling
    """
    logger.info(f"Lambda invoked with event: {json.dumps(event)}")
    
    # Input validation
    required_fields = ['scope', 'target', 'resources', 'email']
    for field in required_fields:
        if field not in event or not event[field]:
            error_msg = f"Missing or empty required field: {field}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    scope = event["scope"]
    target = event["target"]
    resources = event["resources"]
    recipient = event["email"]
    
    if not SENDER:
        error_msg = "Missing SENDER environment variable"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    logger.info(f"Processing inventory: scope={scope}, target={target}, resources={resources}")
    
    csv_files = []
    tmpdir = Path(tempfile.gettempdir())
    
    try:
        # Resolve accounts based on scope
        if scope == "Account":
            accounts = [account_id_from_name(target)]
        elif scope == "OU":
            ou_id = ou_id_from_name(target)
            accounts = accounts_in_ou(ou_id)
        else:
            raise ValueError(f"Invalid scope: {scope}")
        
        logger.info(f"Resolved {len(accounts)} accounts: {accounts}")
        
        # Collect data for each account and resource
        for acct in accounts:
            role_arn = f"arn:aws:iam::{acct}:role/{MEMBER_ROLE}"
            logger.info(f"Processing account: {acct}")
            
            try:
                session = assume(role_arn, "inventory-run")
                logger.info(f"Successfully assumed role for account: {acct}")
            except Exception as e:
                logger.error(f"Failed to assume role for account {acct}: {e}")
                continue
            
            for res in resources:
                mod_name = RES_MAP.get(res)
                if not mod_name:
                    logger.warning(f"Unknown resource type: {res}")
                    continue
                
                try:
                    mod = importlib.import_module(f"resource_fetchers.{mod_name}")
                    logger.info(f"Loaded module for resource: {res}")
                except ImportError as e:
                    logger.error(f"Failed to import module for {res}: {e}")
                    continue
                
                try:
                    rows = []
                    regions = ["us-east-1"] if res == "S3" else REGIONS
                    
                    for region in regions:
                        region_rows = mod.collect(session, acct, region)
                        rows.extend(region_rows)
                        logger.info(f"Collected {len(region_rows)} rows for {res} in {region}")
                    
                    if not rows:
                        logger.info(f"No data found for {res} in account {acct}")
                        continue
                    
                    # Write CSV
                    csv_name = f"{acct}_{res}.csv"
                    csv_path = tmpdir / csv_name
                    write_csv(rows, mod.HEADERS, csv_path)
                    csv_files.append(str(csv_path))
                    
                except Exception as e:
                    logger.error(f"Error collecting {res} for account {acct}: {e}")
                    continue
        
        if not csv_files:
            logger.info("No data collected - sending notification email")
            try:
                send_email(
                    sender=SENDER,
                    recipient=recipient,
                    subject="AWS Inventory - No Data Found",
                    message="No resources were found matching your criteria.",
                    attachment=None
                )
                return {"message": "No data found - notification sent"}
            except Exception as e:
                logger.error(f"Failed to send no-data notification: {e}")
                raise
        
        # Create ZIP archive
        from datetime import datetime
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        zip_filename = f"aws-inventory-{timestamp}.zip"
        zip_path = tmpdir / zip_filename
        
        zip_size = create_zip_archive(csv_files, zip_path)
        logger.info(f"Created ZIP archive with {len(csv_files)} files, size: {zip_size} bytes")
        
        # Send email with ZIP attachment
        subject = f"AWS Resource Inventory - {len(csv_files)} files"
        message = f"Please find attached AWS resource inventory containing {len(csv_files)} CSV files."
        
        try:
            send_email(
                sender=SENDER,
                recipient=recipient,
                subject=subject,
                message=message,
                attachment=str(zip_path)
            )
            logger.info(f"Successfully sent inventory email to {recipient}")
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise
        
        return {
            "message": f"Successfully sent AWS inventory with {len(csv_files)} files to {recipient}",
            "accounts_processed": len(accounts),
            "files_created": len(csv_files),
            "zip_size_bytes": zip_size
        }
    
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}")
        raise
    
    finally:
        # Cleanup temporary files
        try:
            for file_path in csv_files:
                if os.path.exists(file_path):
                    os.remove(file_path)
            if 'zip_path' in locals() and os.path.exists(zip_path):
                os.remove(zip_path)
            logger.info("Temporary files cleaned up")
        except Exception as e:
            logger.warning(f"Failed to cleanup temporary files: {e}")
