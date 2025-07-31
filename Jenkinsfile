# Jenkinsfile - Complete Jenkins Pipeline for AWS Inventory
# This pipeline uses inline Groovy scripts with embedded Python to dynamically populate parameters

pipeline {
    agent any
    
    parameters {
        // First choice parameter - determines scope
        choice(
            name: 'SCOPE',
            choices: ['Account', 'OU'],
            description: 'Select whether to inventory a single AWS account or an entire Organizational Unit'
        )
        
        // Dynamic parameter that changes based on SCOPE selection
        [$class: 'CascadeChoiceParameter',
            choiceType: 'PT_SINGLE_SELECT',
            name: 'TARGET',
            referencedParameters: 'SCOPE',
            script: [$class: 'GroovyScript',
                sandbox: true,
                script: '''
                    import groovy.json.JsonSlurper
                    
                    // Embedded Python script that uses boto3 to fetch AWS Organizations data
                    def pythonScript = """
import boto3
import json
import sys
import os

# Get the scope from command line argument
scope = sys.argv[1] if len(sys.argv) > 1 else 'Account'

# AWS credentials should be available via IAM role or environment
# Assume the read-only role for Organizations access
role_arn = os.environ.get('ROLE_ARN', 'arn:aws:iam::123456789012:role/JenkinsOrganizationsReadRole')
external_id = os.environ.get('EXTERNAL_ID')  # Optional

try:
    # Assume role for Organizations access
    sts = boto3.client('sts')
    assume_role_kwargs = {
        'RoleArn': role_arn,
        'RoleSessionName': 'jenkins-parameter-discovery'
    }
    if external_id:
        assume_role_kwargs['ExternalId'] = external_id
    
    credentials = sts.assume_role(**assume_role_kwargs)['Credentials']
    
    # Create Organizations client with assumed role credentials
    org_client = boto3.client(
        'organizations',
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )
    
    items = []
    
    if scope == 'Account':
        # List all active accounts
        paginator = org_client.get_paginator('list_accounts')
        for page in paginator.paginate():
            for account in page.get('Accounts', []):
                if account.get('Status') == 'ACTIVE':
                    items.append(account['Name'])
    else:
        # List all Organizational Units
        # Start from root and get all OUs
        roots = org_client.list_roots()['Roots']
        for root in roots:
            try:
                paginator = org_client.get_paginator('list_organizational_units_for_parent')
                for page in paginator.paginate(ParentId=root['Id']):
                    for ou in page.get('OrganizationalUnits', []):
                        items.append(ou['Name'])
            except Exception as e:
                print(f"Warning: Could not list OUs for root {root['Id']}: {e}", file=sys.stderr)
    
    # Sort and return as JSON
    print(json.dumps(sorted(set(items))))
    
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    # Return empty list on error
    print(json.dumps([]))
                    """.stripIndent()
                    
                    try {
                        // Determine the mode based on SCOPE parameter
                        def mode = (SCOPE == 'Account') ? 'Account' : 'OU'
                        
                        // Execute Python script
                        def command = ['python3', '-c', pythonScript, mode]
                        def processBuilder = new ProcessBuilder(command)
                        
                        // Set environment variables for the Python script
                        def env = processBuilder.environment()
                        env.put('ROLE_ARN', 'arn:aws:iam::123456789012:role/JenkinsOrganizationsReadRole')  // Replace with your role ARN
                        // env.put('EXTERNAL_ID', 'your-external-id')  // Uncomment if your role requires external ID
                        
                        // Execute the process
                        def process = processBuilder.redirectErrorStream(true).start()
                        process.waitFor()
                        
                        def output = process.inputStream.text.trim()
                        
                        if (process.exitValue() == 0 && output) {
                            // Parse JSON output
                            def jsonSlurper = new JsonSlurper()
                            return jsonSlurper.parseText(output)
                        } else {
                            // Return default values on error
                            return ['Error: Could not fetch data']
                        }
                        
                    } catch (Exception e) {
                        // Return error message if script fails
                        return ["Error: ${e.message}"]
                    }
                '''
            ]
        ]
        
        // Multi-select choice for AWS resources
        choice(
            name: 'RESOURCES',
            choices: [
                'EC2',
                'S3', 
                'Lambda',
                'RDS',
                'DynamoDB',
                'Glue',
                'Eventbridge',
                'StepFunctions',
                'SecurityHub',
                'Config'
            ].join('\n'),
            description: 'Select AWS services to inventory (multiple selections allowed)',
            multiple: true
        )
        
        // Email address parameter
        string(
            name: 'EMAIL',
            defaultValue: 'your-email@company.com',
            description: 'Email address to receive the inventory report ZIP file'
        )
    }
    
    environment {
        // Lambda function ARN - replace with your actual Lambda ARN
        LAMBDA_ARN = 'arn:aws:lambda:us-east-1:123456789012:function:aws-inventory'
        
        // AWS CLI configuration for better reliability
        AWS_MAX_ATTEMPTS = '3'
        AWS_RETRY_MODE = 'adaptive'
    }
    
    stages {
        stage('Validate Parameters') {
            steps {
                script {
                    // Validate that required parameters are provided
                    if (!params.SCOPE) {
                        error('SCOPE parameter is required')
                    }
                    if (!params.TARGET) {
                        error('TARGET parameter is required')
                    }
                    if (!params.RESOURCES) {
                        error('At least one RESOURCE must be selected')
                    }
                    if (!params.EMAIL) {
                        error('EMAIL parameter is required')
                    }
                    
                    // Log parameters for debugging
                    echo "Parameters validated:"
                    echo "  SCOPE: ${params.SCOPE}"
                    echo "  TARGET: ${params.TARGET}"
                    echo "  RESOURCES: ${params.RESOURCES}"
                    echo "  EMAIL: ${params.EMAIL}"
                }
            }
        }
        
        stage('Invoke Lambda') {
            steps {
                script {
                    try {
                        // Prepare the payload for Lambda
                        def resourceList = params.RESOURCES.tokenize(',').collect { it.trim() }
                        def payload = [
                            scope: params.SCOPE,
                            target: params.TARGET,
                            resources: resourceList,
                            email: params.EMAIL
                        ]
                        
                        // Convert payload to JSON
                        def jsonPayload = groovy.json.JsonOutput.toJson(payload)
                        echo "Invoking Lambda with payload: ${jsonPayload}"
                        
                        // Invoke Lambda function
                        def invokeCommand = """
                            aws lambda invoke \
                                --function-name ${env.LAMBDA_ARN} \
                                --payload '${jsonPayload}' \
                                --cli-binary-format raw-in-base64-out \
                                --log-type Tail \
                                response.json
                        """
                        
                        def result = sh(script: invokeCommand, returnStatus: true)
                        
                        if (result != 0) {
                            error("Lambda invocation failed with exit code: ${result}")
                        }
                        
                        // Read and display the response
                        def response = readFile('response.json')
                        echo "Lambda response: ${response}"
                        
                        // Parse response to check for errors
                        def jsonSlurper = new groovy.json.JsonSlurper()
                        def responseObj = jsonSlurper.parseText(response)
                        
                        if (responseObj.errorMessage) {
                            error("Lambda execution failed: ${responseObj.errorMessage}")
                        }
                        
                        // Log success information
                        if (responseObj.accounts_processed) {
                            echo "Successfully processed ${responseObj.accounts_processed} accounts"
                        }
                        if (responseObj.successful_collections) {
                            echo "Successful collections: ${responseObj.successful_collections}/${responseObj.total_collections}"
                        }
                        if (responseObj.zip_size_mb) {
                            echo "ZIP file size: ${responseObj.zip_size_mb} MB"
                        }
                        
                    } catch (Exception e) {
                        echo "Error during Lambda invocation: ${e.message}"
                        throw e
                    }
                }
            }
        }
    }
    
    post {
        always {
            // Clean up response file
            script {
                if (fileExists('response.json')) {
                    sh 'rm -f response.json'
                }
            }
        }
        
        success {
            echo "✅ AWS Inventory pipeline completed successfully!"
            echo "📧 Inventory report has been sent to: ${params.EMAIL}"
        }
        
        failure {
            echo "❌ AWS Inventory pipeline failed!"
            
            // Optional: Send failure notification email
            script {
                try {
                    emailext(
                        subject: "AWS Inventory Pipeline Failed - ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                        body: """
                        The AWS Inventory pipeline has failed.
                        
                        Parameters:
                        - Scope: ${params.SCOPE}
                        - Target: ${params.TARGET}
                        - Resources: ${params.RESOURCES}
                        - Email: ${params.EMAIL}
                        
                        Build URL: ${env.BUILD_URL}
                        Console Output: ${env.BUILD_URL}console
                        
                        Please check the console output for details.
                        """,
                        to: "${params.EMAIL}",
                        mimeType: 'text/plain'
                    )
                } catch (Exception e) {
                    echo "Could not send failure notification email: ${e.message}"
                }
            }
        }
    }
}

/*
SETUP INSTRUCTIONS:

1. Prerequisites:
   - Install the "Active Choices" plugin in Jenkins
   - Ensure Jenkins has AWS CLI configured with appropriate credentials
   - Ensure Jenkins has Python 3 and boto3 installed on the master node
   - Create an IAM role that Jenkins can assume for Organizations read access

2. IAM Role Setup:
   Create a role with the following:
   - Trust policy allowing Jenkins to assume the role
   - Permissions: organizations:List*, organizations:Describe*
   - Optional: Require external ID for additional security

3. Lambda Function:
   - Deploy the Lambda function with the provided code
   - Update the LAMBDA_ARN environment variable with your Lambda ARN
   - Ensure Lambda has appropriate permissions for cross-account access

4. Jenkins Job Configuration:
   - Create a new Pipeline job
   - Use "Pipeline script from SCM" or paste this Jenkinsfile
   - Update the role ARN in the Groovy script
   - Test with a small scope first

5. Testing:
   - Run the pipeline with Account scope first
   - Verify parameters populate correctly
   - Check Lambda logs for any issues
   - Verify email delivery

TROUBLESHOOTING:

If parameters don't populate:
- Check Jenkins logs for Python/boto3 errors
- Verify IAM role permissions
- Test AWS CLI access from Jenkins node

If Lambda fails:
- Check Lambda logs in CloudWatch
- Verify cross-account role trusts
- Check Lambda timeout and memory settings

If email delivery fails:
- Verify SES configuration
- Check sender/recipient verification
- Review Lambda email function implementation
*/