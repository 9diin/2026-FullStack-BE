from pydantic import BaseModel, EmailStr, Field


class EmailVerificationSend(BaseModel):
    email: EmailStr


class EmailVerificationCheck(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class EmailVerificationResult(BaseModel):
    message: str
    verified: bool
