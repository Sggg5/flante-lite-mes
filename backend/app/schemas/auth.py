from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]


class UpdateUserRolesRequest(BaseModel):
    role_codes: list[str] = Field(min_length=1)
    reason: str = Field(min_length=2, max_length=500)


class UserRolesResponse(BaseModel):
    user_id: int
    role_codes: list[str]
