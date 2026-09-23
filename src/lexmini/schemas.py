# src/lexmini/schemas.py
"""Review records. Confidence stays empty when a detector supplies no score."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sensitivity = Literal["public", "personal-private", "professional-secrecy"]
FieldType = Literal[
  "person_name", "organisation_name", "birth_date", "date", "address", "email",
  "phone", "personal_identifier", "account_number", "amount", "medical_information",
  "belief", "criminal_record", "case_reference", "legal_content", "business_secret",
  "firm_record", "credential", "private_url", "confidential_term", "other",
]


class Context(BaseModel):
  model_config = ConfigDict(extra="forbid")
  role: str = Field(default="Legal translator", max_length=500)
  goal: str = Field(default="Translate the document while protecting private client details and sensitive facts.", max_length=2000)
  confidential_terms: list[str] = Field(default_factory=list, max_length=100)
  retain_requests: list[str] = Field(default_factory=list, max_length=50)
  review_set: str = Field(default="demo", min_length=1, max_length=80, pattern=r"^[\w .-]+$")
  fuzzy_matching: bool = True
  languages: list[Literal["de", "fr", "it", "en"]] = Field(default_factory=lambda: ["fr"], min_length=1, max_length=4)
  use_layout: bool = True
  use_privacy_filter: bool = False
  use_llm_review: bool = False

  @model_validator(mode="after")
  def limit_terms(self):
    if any(not value.strip() or len(value) > 200 for value in self.confidential_terms + self.retain_requests):
      raise ValueError("Terms must contain 1 to 200 characters")
    return self


class Location(BaseModel):
  source: Literal["page_text", "metadata"] = "page_text"
  page_number: int | None = Field(default=None, ge=1)
  start: int | None = Field(default=None, ge=0)
  end: int | None = Field(default=None, ge=0)
  boxes: list[tuple[float, float, float, float]] = Field(default_factory=list)
  metadata_key: str | None = None


class Finding(BaseModel):
  finding_id: str
  entity_id: str | None = None
  field_type: FieldType
  original_text: str
  location: Location
  sensitivity_levels: list[Sensitivity]
  subcategory: str
  publication_status: Literal["unknown", "published", "not_published"] = "unknown"
  publication_source: str | None = None
  detection_confidence: float | None = Field(default=None, ge=0, le=1)
  classification_confidence: float | None = Field(default=None, ge=0, le=1)
  detector: str
  reason: str
  excerpt_before: str = ""
  excerpt_after: str = ""
  context_suggestion: Literal["keep", "remove", "review"] = "review"
  context_reason: str | None = None
  selected: bool = True
  review_status: Literal["unreviewed", "confirmed_remove", "confirmed_keep"] = "unreviewed"
  replacement: str | None = None
  review_signal: Literal["approved", "priority", "candidate", "weak"] = "candidate"
  signal_reason: str = "Candidate detection; confidence is not calibrated."
  layout_label: str | None = None
  legal_reference: dict | None = None

  @model_validator(mode="after")
  def consistent_classification(self):
    if not self.sensitivity_levels or ("public" in self.sensitivity_levels and len(self.sensitivity_levels) != 1):
      raise ValueError("Public cannot be combined with protected levels")
    if self.publication_status == "published" and not self.publication_source:
      raise ValueError("Published status requires a source")
    return self


class PageInfo(BaseModel):
  number: int
  width: float
  height: float
  readable: bool


class DocumentReview(BaseModel):
  document_id: str
  filename: str
  document_type: str = "unknown"
  languages: list[str] = Field(default_factory=list)
  page_count: int
  text_source: str = "embedded"
  metadata_fields: list[str] = Field(default_factory=list)
  warnings: list[str] = Field(default_factory=list)
  pages: list[PageInfo]
  findings: list[Finding] = Field(default_factory=list)
  analysed: bool = False
  revision: int = 0
  review_set: str = "demo"
  organisation_id: str = "local-organisation"
  processing: str = "Not analysed"
  quality_check: dict = Field(default_factory=dict)


class ExportRequest(BaseModel):
  selected_ids: list[str] = Field(max_length=10000)
  revision: int = Field(ge=0)
  format: Literal["pdf", "text"]
  replacement_style: Literal["tokens", "x"] = "tokens"
  pdf_layout: Literal["reflow", "original"] = "original"


class LearnRequest(BaseModel):
  model_config = ConfigDict(extra="forbid")
  revision: int = Field(ge=0)
  finding_id: str | None = None
  text: str | None = Field(default=None, min_length=2, max_length=200)
  field_type: FieldType = "confidential_term"
  sensitivity_levels: list[Sensitivity] = Field(default_factory=lambda: ["professional-secrecy"])
  remember: bool = False
  workspace_wide: bool = False
  kept_ids: list[str] = Field(default_factory=list, max_length=10000)

  @model_validator(mode="after")
  def validate_example(self):
    if bool(self.finding_id) == bool(self.text):
      raise ValueError("Choose one existing finding or enter one missed term")
    if not self.sensitivity_levels or "public" in self.sensitivity_levels:
      raise ValueError("A screening example must use a protected data group")
    return self


class Health(BaseModel):
  status: str = "ok"
  detector: str = "spaCy and optional Docling on Modal CPU; local rules and approved memory"
  storage: str = "Local memory; expires after 30 minutes"


class RestoreReviewRequest(BaseModel):
  model_config = ConfigDict(extra="forbid")
  findings: list[Finding] = Field(max_length=10000)
  context: Context


class ReviewDecision(BaseModel):
  model_config = ConfigDict(extra='forbid')
  finding_id: str
  selected: bool
  review_status: Literal['confirmed_remove','confirmed_keep']


class QualityRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  revision: int
  decisions: list[ReviewDecision] = Field(default_factory=list, max_length=10000)
