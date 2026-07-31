from pydantic import BaseModel
from typing import Optional, List

class ManuscriptDetails(BaseModel):
    language: Optional[str] = None
    date_composed: Optional[str] = None
    archive_location: Optional[str] = None
    shelfmark: Optional[str] = None
    incipit: Optional[str] = None

class Work(BaseModel):
    id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    work_type: Optional[str] = None
    cited_by_count: Optional[int] = 0
    source: str = "manual"
    status: str = "curated"
    manuscript_details: Optional[ManuscriptDetails] = None

class WorkCreate(BaseModel):
    id: Optional[str] = None
    doi: Optional[str] = None
    title: str
    year: Optional[int] = None
    venue: Optional[str] = None
    work_type: Optional[str] = None
    authors: Optional[List[str]] = []  # List of author names or IDs
    manuscript_details: Optional[ManuscriptDetails] = None

class WorkUpdate(BaseModel):
    title: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    work_type: Optional[str] = None
    manuscript_details: Optional[ManuscriptDetails] = None

class Author(BaseModel):
    id: str
    name: str
    bio: Optional[str] = None
    interests: Optional[str] = None
    source: str = "manual"
    status: str = "curated"

class AuthorUpdate(BaseModel):
    bio: Optional[str] = None
    interests: Optional[str] = None

class MergeAuthorsRequest(BaseModel):
    primary_id: str
    secondary_ids: List[str]

class MergeWorksRequest(BaseModel):
    primary_id: str
    secondary_id: str

class UserCreate(BaseModel):
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class ClaimAuthorRequest(BaseModel):
    author_id: str

class ContributionCreate(BaseModel):
    type: str # e.g. "new_work", "edit_work"
    payload: str # JSON encoded string

class Contribution(BaseModel):
    id: int
    user_id: int
    type: str
    payload: str
    status: str
    submitted_at: str

class Notification(BaseModel):
    id: int
    user_id: int
    message: str
    is_read: bool
    created_at: str

