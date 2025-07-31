# util.py - Simplified AWS Organizations and STS utilities with caching

import os
import boto3
import logging
from functools import lru_cache
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()

# Configure retry strategy for AWS clients
CONFIG_STD = Config(
    retries={
        "max_attempts": 5,
        "mode": "adaptive"
    },
    read_timeout=60,
    connect_timeout=10
)

# Initialize AWS clients
ORG = boto3.client("organizations", config=CONFIG_STD)
STS = boto3.client("sts", config=CONFIG_STD)
ROLE_NAME = os.environ.get("MEMBER_READ_ROLE", "ResourceReadRole")

def assume(role_arn: str, session_name: str = "inventory") -> boto3.Session:
    """
    Assume the given IAM role and return a boto3 Session with temporary credentials
    
    Args:
        role_arn: ARN of the IAM role to assume
        session_name: Name for the session (appears in CloudTrail)
    
    Returns:
        boto3.Session configured with temporary credentials
    
    Raises:
        Exception: If role assumption fails
    """
    try:
        logger.info(f"Assuming role: {role_arn}")
        response = STS.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            DurationSeconds=3600  # 1 hour
        )
        
        credentials = response["Credentials"]
        session = boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"]
        )
        
        logger.info(f"Successfully assumed role: {role_arn}")
        return session
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"Failed to assume role {role_arn}: {error_code} - {str(e)}")
        raise Exception(f"Role assumption failed: {error_code}")
    except Exception as e:
        logger.error(f"Unexpected error assuming role {role_arn}: {str(e)}")
        raise

@lru_cache(maxsize=128)
def account_id_from_name(account_name: str) -> str:
    """
    Get AWS account ID from account name using Organizations API
    Results are cached to reduce API calls
    
    Args:
        account_name: The friendly name of the AWS account
    
    Returns:
        str: The 12-digit AWS account ID
    
    Raises:
        ValueError: If account name is not found
    """
    try:
        logger.info(f"Looking up account ID for: {account_name}")
        paginator = ORG.get_paginator("list_accounts")
        
        for page in paginator.paginate():
            for account in page.get("Accounts", []):
                if account.get("Name") == account_name and account.get("Status") == "ACTIVE":
                    account_id = account["Id"]
                    logger.info(f"Found account {account_name}: {account_id}")
                    return account_id
        
        raise ValueError(f"Account '{account_name}' not found or not active")
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"AWS error looking up account {account_name}: {error_code}")
        raise Exception(f"Failed to lookup account: {error_code}")
    except Exception as e:
        logger.error(f"Error looking up account {account_name}: {str(e)}")
        raise

@lru_cache(maxsize=64)
def ou_id_from_name(ou_name: str, parent_id: str = None) -> str:
    """
    Get Organizational Unit ID from OU name
    Performs recursive search through the organization hierarchy
    Results are cached to reduce API calls
    
    Args:
        ou_name: Name of the Organizational Unit
        parent_id: Optional parent ID to search within (for recursion)
    
    Returns:
        str: The OU ID
    
    Raises:
        ValueError: If OU name is not found
    """
    try:
        logger.info(f"Looking up OU ID for: {ou_name}")
        
        # Get root IDs if no parent specified
        if not parent_id:
            roots = ORG.list_roots().get("Roots", [])
            parent_ids = [root["Id"] for root in roots]
        else:
            parent_ids = [parent_id]
        
        # Search in each parent
        for pid in parent_ids:
            try:
                paginator = ORG.get_paginator("list_organizational_units_for_parent")
                for page in paginator.paginate(ParentId=pid):
                    for ou in page.get("OrganizationalUnits", []):
                        if ou.get("Name") == ou_name:
                            ou_id = ou["Id"]
                            logger.info(f"Found OU {ou_name}: {ou_id}")
                            return ou_id
                        
                        # Recursive search in child OUs
                        try:
                            return ou_id_from_name(ou_name, ou["Id"])
                        except ValueError:
                            continue  # OU not in this branch, try next
                            
            except ClientError as e:
                # Skip this parent if we can't access it
                logger.warning(f"Cannot access parent {pid}: {e}")
                continue
        
        raise ValueError(f"OU '{ou_name}' not found")
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"AWS error looking up OU {ou_name}: {error_code}")
        raise Exception(f"Failed to lookup OU: {error_code}")
    except Exception as e:
        if "not found" in str(e):
            raise  # Re-raise ValueError from recursive calls
        logger.error(f"Error looking up OU {ou_name}: {str(e)}")
        raise

@lru_cache(maxsize=32)
def accounts_in_ou(ou_id: str) -> tuple:
    """
    Get all active account IDs within an Organizational Unit
    Includes accounts in child OUs (recursive)
    Results are cached and returned as tuple for hashability
    
    Args:
        ou_id: The Organizational Unit ID
    
    Returns:
        tuple: Tuple of account IDs (strings)
    
    Raises:
        Exception: If OU cannot be accessed or doesn't exist
    """
    try:
        logger.info(f"Getting accounts in OU: {ou_id}")
        account_ids = []
        
        # Get direct accounts in this OU
        try:
            paginator = ORG.get_paginator("list_accounts_for_parent")
            for page in paginator.paginate(ParentId=ou_id):
                for account in page.get("Accounts", []):
                    if account.get("Status") == "ACTIVE":
                        account_ids.append(account["Id"])
        except ClientError as e:
            logger.warning(f"Cannot list accounts for OU {ou_id}: {e}")
        
        # Get accounts from child OUs (recursive)
        try:
            paginator = ORG.get_paginator("list_organizational_units_for_parent") 
            for page in paginator.paginate(ParentId=ou_id):
                for child_ou in page.get("OrganizationalUnits", []):
                    child_accounts = accounts_in_ou(child_ou["Id"])
                    account_ids.extend(child_accounts)
        except ClientError as e:
            logger.warning(f"Cannot list child OUs for {ou_id}: {e}")
        
        # Remove duplicates and convert to tuple for caching
        unique_accounts = tuple(set(account_ids))
        logger.info(f"Found {len(unique_accounts)} accounts in OU {ou_id}")
        return unique_accounts
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"AWS error getting accounts in OU {ou_id}: {error_code}")
        raise Exception(f"Failed to get OU accounts: {error_code}")
    except Exception as e:
        logger.error(f"Error getting accounts in OU {ou_id}: {str(e)}")
        raise

def clear_cache():
    """Clear all LRU caches - useful for testing or if org structure changes"""
    account_id_from_name.cache_clear()
    ou_id_from_name.cache_clear()
    accounts_in_ou.cache_clear()
    logger.info("Cleared all organization caches")

def get_cache_info():
    """Get cache statistics for monitoring"""
    return {
        "account_cache": account_id_from_name.cache_info(),
        "ou_cache": ou_id_from_name.cache_info(),
        "accounts_in_ou_cache": accounts_in_ou.cache_info()
    }