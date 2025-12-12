from datetime import datetime
from pydantic import BaseModel, Field


class TagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class TagDTO(TagBase):
    id: str

    class Config:
        from_attributes = True


class TagGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TagGroupCreate(TagGroupBase):
    pass


class TagGroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class TagGroupSummaryDTO(BaseModel):
    """Summary DTO without full tag list."""
    id: str
    name: str
    description: str | None = None
    tagCount: int = 0

    class Config:
        from_attributes = True


class TagGroupDTO(TagGroupBase):
    """Full DTO with tags."""
    id: str
    tags: list[TagDTO] = []
    createdDate: datetime
    lastModifiedDate: datetime

    class Config:
        from_attributes = True
