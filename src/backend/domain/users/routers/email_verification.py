from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.domain.users.schemas.email_verification import (
    EmailVerificationCheck,
    EmailVerificationResult,
    EmailVerificationSend,
)
from backend.domain.users.services.email_verification import (
    EmailVerificationService,
)

router = APIRouter(prefix="/auth/email-verification", tags=["AUTH"])


def get_email_verification_service(
    db: Session = Depends(get_db),
) -> EmailVerificationService:
    return EmailVerificationService(db)


@router.post("/send", status_code=status.HTTP_202_ACCEPTED)
def send_email_verification(
    body: EmailVerificationSend,
    verification_service: EmailVerificationService = Depends(
        get_email_verification_service
    ),
) -> EmailVerificationResult:
    verification_service.send_code(str(body.email))
    return EmailVerificationResult(
        message="이메일이 등록 가능하다면 인증번호가 발송됩니다.",
        verified=False,
    )


@router.post("/verify", response_model=EmailVerificationResult)
def verify_email(
    body: EmailVerificationCheck,
    verification_service: EmailVerificationService = Depends(
        get_email_verification_service
    ),
) -> EmailVerificationResult:
    verification_service.verify_code(str(body.email), body.code)
    return EmailVerificationResult(
        message="이메일 인증이 완료되었습니다.",
        verified=True,
    )
