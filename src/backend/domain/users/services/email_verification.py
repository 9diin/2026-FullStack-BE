import hashlib
import hmac
import logging
import secrets
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.domain.users.models.email_verification import EmailVerification
from backend.domain.users.models.user import User

logger = logging.getLogger(__name__)

VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_RANGE = 10**VERIFICATION_CODE_LENGTH


class EmailVerificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def send_code(self, email: str) -> None:
        normalized_email = email.strip().lower()

        # Keep the same HTTP response for existing accounts to avoid direct
        # account-existence disclosure in the response body and status.
        existing_user = (
            self.db.query(User)
            .filter(func.lower(User.email) == normalized_email)
            .first()
        )
        if existing_user is not None:
            return

        now = datetime.now(UTC)
        verification = (
            self.db.query(EmailVerification)
            .filter(EmailVerification.email == normalized_email)
            .with_for_update()
            .first()
        )
        if verification is not None:
            last_sent_at = self._as_utc(verification.last_sent_at)
            cooldown = timedelta(seconds=settings.EMAIL_VERIFICATION_RESEND_SECONDS)
            if now - last_sent_at < cooldown:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="인증번호 재발송까지 잠시 기다려 주세요.",
                )

        code = (
            f"{secrets.randbelow(VERIFICATION_CODE_RANGE):0{VERIFICATION_CODE_LENGTH}d}"
        )
        if verification is None:
            verification = EmailVerification(
                email=normalized_email,
                code_hash=self._hash_code(normalized_email, code),
                attempts=0,
                expires_at=now
                + timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES),
                last_sent_at=now,
            )
            self.db.add(verification)
        else:
            verification.code_hash = self._hash_code(normalized_email, code)
            verification.attempts = 0
            verification.expires_at = now + timedelta(
                minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES
            )
            verification.last_sent_at = now
            verification.verified_at = None

        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        try:
            self._send_email(normalized_email, code)
        except (OSError, smtplib.SMTPException, RuntimeError) as exc:
            logger.exception("Failed to send an email verification")
            try:
                self.db.delete(verification)
                self.db.commit()
            except SQLAlchemyError:
                self.db.rollback()
                logger.exception("Failed to invalidate an email verification")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="인증 이메일을 발송하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            ) from exc

    def verify_code(self, email: str, code: str) -> None:
        normalized_email = email.strip().lower()
        verification = self._get_verification(normalized_email)
        if verification is None:
            self._invalid_code()

        now = datetime.now(UTC)
        if self._as_utc(verification.expires_at) <= now:
            self.db.delete(verification)
            self._commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="인증번호가 만료되었습니다. 새 인증번호를 요청해 주세요.",
            )

        if verification.attempts >= settings.EMAIL_VERIFICATION_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="인증 시도 횟수를 초과했습니다. 새 인증번호를 요청해 주세요.",
            )

        self._validate_code(verification, normalized_email, code)
        if verification.verified_at is not None:
            return

        verification.verified_at = now
        self._commit()

    def consume_verified_code(self, email: str, code: str) -> None:
        normalized_email = email.strip().lower()
        verification = self._get_verification(normalized_email)
        if verification is None or verification.verified_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="회원가입 전에 이메일 인증을 완료해 주세요.",
            )
        if self._as_utc(verification.expires_at) <= datetime.now(UTC):
            self.db.delete(verification)
            self._commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="인증이 만료되었습니다. 이메일을 다시 인증해 주세요.",
            )
        self._validate_code(verification, normalized_email, code)

        # Consuming the verification in the same transaction as user creation
        # prevents the same confirmation from being reused for another account.
        self.db.delete(verification)

    def _get_verification(self, email: str) -> EmailVerification | None:
        return (
            self.db.query(EmailVerification)
            .filter(EmailVerification.email == email)
            .with_for_update()
            .first()
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def _validate_code(
        self, verification: EmailVerification, email: str, code: str
    ) -> None:
        if verification.attempts >= settings.EMAIL_VERIFICATION_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="인증 시도 횟수를 초과했습니다. 새 인증번호를 요청해 주세요.",
            )

        expected_hash = self._hash_code(email, code)
        if not hmac.compare_digest(verification.code_hash, expected_hash):
            verification.attempts += 1
            self._commit()
            self._invalid_code()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        # SQLite may return a timezone-naive datetime even when the column is timezone-aware.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _hash_code(email: str, code: str) -> str:
        # A keyed hash prevents a database-only leak from exposing six-digit codes
        # to a trivial offline brute-force search.
        message = f"{email}:{code}".encode("utf-8")
        return hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _invalid_code() -> None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이메일 또는 인증번호가 올바르지 않습니다.",
        )

    @staticmethod
    def _send_email(email: str, code: str) -> None:
        required_settings = (
            settings.SMTP_HOST,
            settings.SMTP_FROM_EMAIL,
        )
        if not all(required_settings):
            raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be configured")
        if bool(settings.SMTP_USERNAME) != bool(settings.SMTP_PASSWORD):
            raise RuntimeError(
                "SMTP_USERNAME and SMTP_PASSWORD must both be configured"
            )

        message = EmailMessage()
        message["Subject"] = "[사업계획서 플랫폼] 이메일 인증번호 안내"
        message["From"] = settings.SMTP_FROM_EMAIL
        message["To"] = email
        message.set_content(
            f"이메일 인증번호는 {code} 입니다.\n"
            f"인증번호는 {settings.EMAIL_VERIFICATION_EXPIRE_MINUTES}분 후 만료됩니다.\n"
            "본인이 요청하지 않았다면 이 메일을 무시해 주세요."
        )
        message.add_alternative(
            f"""\
<!doctype html>
<html lang="ko">
  <body style="margin:0;background:#f3f5f9;font-family:Arial,sans-serif;color:#172033;">
    <div style="max-width:560px;margin:40px auto;padding:0 16px;">
      <div style="overflow:hidden;border-radius:20px;background:#ffffff;box-shadow:0 12px 40px rgba(24,39,75,.10);">
        <div style="padding:32px 36px;background:linear-gradient(135deg,#4338ca,#7c3aed);color:#ffffff;">
          <div style="font-size:13px;letter-spacing:1.5px;opacity:.85;">EMAIL VERIFICATION</div>
          <h1 style="margin:12px 0 0;font-size:25px;">이메일 인증을 완료해 주세요</h1>
        </div>
        <div style="padding:36px;">
          <p style="margin:0 0 12px;font-size:16px;">회원가입을 위한 인증번호입니다.</p>
          <p style="margin:0 0 24px;color:#667085;font-size:14px;">아래 번호를 가입 화면에 입력해 주세요.</p>
          <div style="padding:20px;border:1px solid #e4e7ec;border-radius:14px;background:#f9fafb;text-align:center;">
            <span style="font-size:34px;font-weight:700;letter-spacing:10px;color:#4338ca;">{code}</span>
          </div>
          <p style="margin:20px 0 0;color:#667085;font-size:13px;">
            인증번호는 <strong>{settings.EMAIL_VERIFICATION_EXPIRE_MINUTES}분</strong> 후 만료됩니다.
          </p>
          <div style="height:1px;margin:28px 0;background:#eaecf0;"></div>
          <p style="margin:0;color:#98a2b3;font-size:12px;line-height:1.7;">
            본인이 요청하지 않았다면 이 메일을 무시해 주세요.<br>
            보안을 위해 인증번호를 다른 사람과 공유하지 마세요.
          </p>
        </div>
      </div>
      <p style="margin:18px 0;text-align:center;color:#98a2b3;font-size:12px;">
        사업계획서 플랫폼
      </p>
    </div>
  </body>
</html>
""",
            subtype="html",
        )

        context = ssl.create_default_context()
        with smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=10,
        ) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls(context=context)
            if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                smtp.login(
                    settings.SMTP_USERNAME,
                    settings.SMTP_PASSWORD.get_secret_value(),
                )
            smtp.send_message(message)
