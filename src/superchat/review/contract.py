"""
The data contract between the MCP and ANY review screen (artifact, MCP App, agent-built, text).
JSON schemas are generated from these models into review/*.schema.json.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Ref(BaseModel):
    """An existing row (id) or a new one (name)."""
    id: Optional[str] = None
    name: Optional[str] = None

    @model_validator(mode="after")
    def _one(self):
        if not (self.id or (self.name and self.name.strip())):
            raise ValueError("give an id or a name")
        return self


class Conflict(BaseModel):
    other_id: str
    note: Optional[str] = None


class PushItem(BaseModel):
    keep_id: str
    chat_id: Optional[str] = None
    kind: Literal["decision", "key_note"] = "decision"
    title: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    condition: Optional[str] = None
    reason: Optional[str] = None
    original_text: Optional[str] = None
    source_agent: Optional[str] = None
    folder_key: Optional[str] = None
    kept_at: Optional[str] = None
    company: Ref                                   # required: nothing is saved without a company
    product: Optional[Ref] = None                  # empty = applies to all of the company's products
    conflicts: list[Conflict] = []

    @field_validator("title", "decision")
    @classmethod
    def _not_blank(cls, v):
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class PushPayload(BaseModel):
    """What the review screen sends when the person presses the single Push button."""
    cutoff: str                                    # the review list's `cutoff`, passed back unchanged
    items: list[PushItem] = []                     # ticked items only
    remove_keep_ids: list[str] = []                # un-ticked items: deleted for good


class SuggestionRef(BaseModel):
    id: Optional[str] = None
    name: str


class Suggestion(BaseModel):
    company: Optional[SuggestionRef] = None
    product: Optional[SuggestionRef] = None
    evidence: str = ""
    strength: Literal["strong", "none"] = "none"


class SimilarHit(BaseModel):
    id: str
    title: str
    decision: str
    company: str
    product: Optional[str] = None
    similarity: Optional[float] = None
    author_email: Optional[str] = None


class ReviewItem(BaseModel):
    keep_id: str
    source: Literal["queue", "draft"]
    chat_id: Optional[str] = None
    kind: Literal["decision", "key_note"] = "decision"
    title: str
    decision: str
    condition: Optional[str] = None
    reason: Optional[str] = None
    original_text: Optional[str] = None
    kept_at: Optional[str] = None
    source_agent: Optional[str] = None
    folder_key: Optional[str] = None
    suggestion: Suggestion = Suggestion()
    similar: list[SimilarHit] = []                 # possible duplicates / conflicts, for the agent to judge
    selected: bool = True


class ProductOption(BaseModel):
    id: str
    name: str


class CompanyOption(BaseModel):
    id: str
    name: str
    aliases: list[str] = []
    products: list[ProductOption] = []


class ReviewList(BaseModel):
    """What the MCP gives a review screen."""
    built_at: str
    cutoff: str                                    # = built_at; items kept later wait for the next review
    items: list[ReviewItem]
    companies: list[CompanyOption]
