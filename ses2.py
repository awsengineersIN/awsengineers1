import json
import boto3
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

def send_email(
        sender_addr: str,
        receiver_addr: list,
        email_subject: str,
        email_body: str,
        email_attachment=None,
        reply_to: str = "",
) -> str:
    
    try:
        client = boto3.client("secretsmanager", region_name="us-east-1")
        response = client.get_secret_value(SecretId=os.environ["SES_SECRETS_ARN"])
        ses_credentials = json.loads(response["SecretString"])

        msg = MIMEMultipart()
        msg["From"] = sender_addr
        msg["To"] = ", ".join(receiver_addr)
        msg["Subject"] = email_subject
        msg["Reply-To"] = reply_to  # Fixed header name
        
        # Attach email body
        msg.attach(MIMEText(email_body, "plain"))
        
        # Handle attachment properly
        if email_attachment is not None and os.path.exists(email_attachment):
            with open(email_attachment, "rb") as attachment_file:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment_file.read())
            
            # Encode file in ASCII characters to send by email
            encoders.encode_base64(part)
            
            # Add header with filename
            filename = Path(email_attachment).name
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {filename}'
            )
            
            # Attach the part to message
            msg.attach(part)

        # Fixed syntax errors
        ses_server = smtplib.SMTP(os.environ["SES_ENDPOINT"], 587)  # Removed extra space
        ses_server.starttls()
        ses_server.login(
            ses_credentials["ses_smtp_username"], 
            ses_credentials["ses_smtp_password"]
        )
        ses_server.sendmail(sender_addr, receiver_addr, msg.as_string())
        ses_server.quit()
        
        return f"Email sent successfully via SES to {receiver_addr}"
        
    except FileNotFoundError:
        return f"Attachment file not found: {email_attachment}"
    except Exception as e:
        return f"Failed to send email via SES due to {e}"
