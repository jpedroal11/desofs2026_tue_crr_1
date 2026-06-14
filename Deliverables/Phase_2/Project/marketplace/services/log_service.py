import os
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from fastapi import Request

from models.models import AuditLog

from core.request_context import get_client_ip

def write_audit_log(
        db: Session,
        user_id,
        action,
        resource,
        resource_id,
        result,
        message: Optional[str] = None
    ):

    event = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource,
        resource_id=resource_id,
        ip_address=get_client_ip(),
        result=result,
        message=message,
    )

    db.add(event)
    db.commit()