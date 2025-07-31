# lambda_function.py - Simplified AWS Inventory Lambda with built-in fault tolerance

import os
import csv
import json
import importlib
import tempfile
import zipfile
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from util import assume, account_id_from_name, ou_id_from_name, accounts_in_ou

# Configure simple logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
if logger.handlers:
    for handler in logger.handlers:
        logger.removeHandler(handler)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Environment variables
REGIONS = os.getenv("REGIONS", "us-east-1").split(",")
SENDER = os.getenv("SENDER", None)
MEMBER_ROLE = os.getenv("MEMBER_READ_ROLE", "ResourceReadRole")
MAX_ZIP_SIZE_MB = int(os.getenv("MAX_ZIP_SIZE_MB", "35"))  # Leave buffer for SES 40MB limit

# Import your custom send_email function
# from your_utils import send_email  # Uncomment and adjust import path

# Resource mapping
RES_MAP = {
    "EC2": "ec2",
    "S3": "s3", 
    "Lambda": "lambda_",
    "RDS": "rds",
    "DynamoDB": "dynamodb",
    "Glue": "glue",
    "Eventbridge": "eventbridge",
    "StepFunctions": "stepfunctions",
    "SecurityHub": "securityhub",
    "Config": "config"
}

def retry_with_backoff(func, max_retries=3, backoff_factor=1.5):
    """Simple retry mechanism with exponential backoff"""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries:
                raise e
            wait_time = backoff_factor ** attempt
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time:.1f}s: {str(e)[:100]}")
            time.sleep(wait_time)

def write_csv(rows: List[List], headers: List[str], path: str) -> None:
    """Write CSV file with headers and data rows"""
    try:
        with open(path, "w", newline="", encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            writer.writerows(rows)
        logger.info(f"Created CSV: {Path(path).name} ({len(rows)} rows)")
    except Exception as e:
        logger.error(f"Failed to write CSV {path}: {e}")
        raise

def create_zip_archive(file_paths: List[str], zip_path: str) -> int:
    """Create ZIP archive from list of file paths, return ZIP size in bytes"""
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
            for file_path in file_paths:
                if Path(file_path).exists():
                    zipf.write(file_path, Path(file_path).name)
        
        zip_size = Path(zip_path).stat().st_size
        zip_size_mb = zip_size / (1024 * 1024)
        logger.info(f"Created ZIP: {Path(zip_path).name} ({zip_size_mb:.1f} MB)")
        
        if zip_size_mb > MAX_ZIP_SIZE_MB:
            logger.warning(f"ZIP size {zip_size_mb:.1f} MB exceeds recommended limit of {MAX_ZIP_SIZE_MB} MB")
        
        return zip_size
    except Exception as e:
        logger.error(f"Failed to create ZIP archive: {e}")
        raise

def collect_resource_data(session: boto3.Session, resource_type: str, account_id: str, regions: List[str]) -> List[List]:
    """Collect data for a specific resource type with built-in retry"""
    mod_name = RES_MAP.get(resource_type)
    if not mod_name:
        logger.warning(f"Unknown resource type: {resource_type}")
        return []
    
    try:
        mod = importlib.import_module(f"resource_fetchers.{mod_name}")
    except ImportError as e:
        logger.error(f"Failed to import module for {resource_type}: {e}")
        return []
    
    all_rows = []
    successful_regions = 0
    total_regions = len(regions)
    
    for region in regions:
        def collect_for_region():
            return mod.collect(session, account_id, region)
        
        try:
            rows = retry_with_backoff(collect_for_region)
            if rows:
                all_rows.extend(rows)
                successful_regions += 1
                logger.info(f"Collected {resource_type} from {region}: {len(rows)} items")
            else:
                logger.info(f"No {resource_type} found in {region}")
        except Exception as e:
            logger.error(f"Failed to collect {resource_type} from {region}: {str(e)[:200]}")
    
    if successful_regions < total_regions:
        logger.warning(f"{resource_type} collection: {successful_regions}/{total_regions} regions successful")
    
    return all_rows

def send_email_wrapper(sender: str, recipient: str, subject: str, message: str, attachment_path: str):
    """Wrapper for your custom send_email function with retry"""
    def send_attempt():
        # Replace this with your actual send_email function call
        # send_email(sender, recipient, subject, message, attachment_path)
        
        # Placeholder - replace with your actual implementation
        logger.info(f"PLACEHOLDER: Would send email to {recipient} with attachment {Path(attachment_path).name}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Message: {message}")
        # Remove this and uncomment your send_email call above
        
    try:
        retry_with_backoff(send_attempt, max_retries=2)
        logger.info(f"Email sent successfully to {recipient}")
    except Exception as e:
        logger.error(f"Failed to send email after retries: {e}")
        raise

def cleanup_temp_files(file_paths: List[str]) -> None:
    """Clean up temporary files"""
    for file_path in file_paths:
        try:
            if Path(file_path).exists():
                Path(file_path).unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup {file_path}: {e}")

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler
    Expected event format:
    {
        "scope": "Account" | "OU",
        "target": "AccountName" or "OUName", 
        "resources": ["EC2", "S3", "Lambda", ...],
        "email": "user@example.com"
    }
    """
    start_time = datetime.utcnow()
    
    # Validate environment
    if not SENDER:
        logger.error("Missing SENDER environment variable")
        raise ValueError("SENDER environment variable is required")
    
    # Validate input
    required_fields = ["scope", "target", "resources", "email"]
    missing_fields = [f for f in required_fields if not event.get(f)]
    if missing_fields:
        logger.error(f"Missing required fields: {missing_fields}")
        raise ValueError(f"Missing required event fields: {', '.join(missing_fields)}")
    
    scope = event["scope"]
    target = event["target"]
    resources = event["resources"]
    recipient = event["email"]
    
    logger.info(f"Starting inventory: scope={scope}, target={target}, resources={resources}, email={recipient}")
    
    # Resolve accounts
    try:
        def resolve_accounts():
            if scope == "Account":
                return [account_id_from_name(target)]
            elif scope == "OU":
                ou_id = ou_id_from_name(target)
                return accounts_in_ou(ou_id)
            else:
                raise ValueError(f"Invalid scope: {scope}")
        
        accounts = retry_with_backoff(resolve_accounts)
        logger.info(f"Resolved {len(accounts)} accounts: {accounts}")
        
    except Exception as e:
        logger.error(f"Failed to resolve accounts for {scope}={target}: {e}")
        raise
    
    # Collect inventory data
    tmp_dir = Path(tempfile.gettempdir())
    csv_files = []
    successful_collections = 0
    total_collections = len(accounts) * len(resources)
    
    try:
        for account_id in accounts:
            role_arn = f"arn:aws:iam::{account_id}:role/{MEMBER_ROLE}"
            
            # Assume role with retry
            try:
                def assume_role():
                    return assume(role_arn, "inventory-run")
                
                session = retry_with_backoff(assume_role)
                logger.info(f"Successfully assumed role for account {account_id}")
                
            except Exception as e:
                logger.error(f"Failed to assume role for account {account_id}: {e}")
                continue
            
            # Collect each resource type
            for resource_type in resources:
                try:
                    # Handle S3 special case (global service)
                    regions = ["us-east-1"] if resource_type == "S3" else REGIONS
                    
                    rows = collect_resource_data(session, resource_type, account_id, regions)
                    
                    if rows:
                        # Import headers from module
                        mod_name = RES_MAP.get(resource_type)
                        mod = importlib.import_module(f"resource_fetchers.{mod_name}")
                        
                        csv_filename = f"{account_id}_{resource_type}.csv"
                        csv_path = tmp_dir / csv_filename
                        
                        write_csv(rows, mod.HEADERS, str(csv_path))
                        csv_files.append(str(csv_path))
                        successful_collections += 1
                        
                    else:
                        logger.info(f"No data found for {resource_type} in account {account_id}")
                        
                except Exception as e:
                    logger.error(f"Failed to collect {resource_type} for account {account_id}: {e}")
                    continue
        
        logger.info(f"Collection complete: {successful_collections}/{total_collections} successful")
        
        if not csv_files:
            logger.warning("No data collected, sending notification email")
            send_email_wrapper(
                sender=SENDER,
                recipient=recipient,
                subject="AWS Inventory - No Data Found",
                message="No resources were found matching your criteria.",
                attachment_path=""  # No attachment
            )
            return {"message": "No data found, notification sent"}
        
        # Create ZIP archive
        timestamp = start_time.strftime('%Y%m%d-%H%M%S')
        zip_filename = f"aws-inventory-{timestamp}.zip"
        zip_path = tmp_dir / zip_filename
        
        zip_size = create_zip_archive(csv_files, str(zip_path))
        
        # Send email with ZIP attachment
        subject = f"AWS Inventory Report - {scope}: {target}"
        message = f"""AWS Resource Inventory Report

Scope: {scope}
Target: {target}
Resources: {', '.join(resources)}
Generated: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC

Summary:
- Accounts processed: {len(accounts)}
- Successful collections: {successful_collections}/{total_collections}
- ZIP file size: {zip_size / (1024*1024):.1f} MB

The attached ZIP file contains CSV files with detailed resource information.
"""
        
        send_email_wrapper(
            sender=SENDER,
            recipient=recipient,
            subject=subject,
            message=message,
            attachment_path=str(zip_path)
        )
        
        # Cleanup
        cleanup_temp_files(csv_files + [str(zip_path)])
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"Inventory completed successfully in {duration:.1f}s")
        
        return {
            "message": f"Inventory sent to {recipient}",
            "accounts_processed": len(accounts),
            "successful_collections": successful_collections,
            "total_collections": total_collections,
            "zip_size_mb": round(zip_size / (1024*1024), 1),
            "duration_seconds": round(duration, 1)
        }
        
    except Exception as e:
        logger.error(f"Inventory processing failed: {e}")
        cleanup_temp_files(csv_files)
        raise
    
    finally:
        # Final cleanup attempt
        cleanup_temp_files(csv_files)