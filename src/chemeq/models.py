"""Pydantic models for the VLM transcription contract."""

from __future__ import annotations

from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class TranscribedStudent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(default="", validation_alias=AliasChoices("name", "姓名"))
    no: str = Field(default="", validation_alias=AliasChoices("no", "number", "student_no", "学号"))
    class_name: str = Field(
        default="",
        validation_alias=AliasChoices("class_name", "class", "班级"),
    )
    confidence: float = 0.8

    @field_validator("name", "no", "class_name", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.8
        return max(0.0, min(1.0, number))


class TranscribedEquation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    qno: str = Field(default="", validation_alias=AliasChoices("qno", "number", "题号", "index"))
    raw: str = Field(
        default="",
        validation_alias=AliasChoices("raw", "equation", "answer", "text", "content"),
    )
    confidence: float = 1.0

    @field_validator("qno", "raw", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 1.0
        return max(0.0, min(1.0, number))


class Transcription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student: TranscribedStudent = Field(default_factory=TranscribedStudent)
    equations: list[TranscribedEquation] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        student = payload.get("student")
        if isinstance(student, str):
            payload["student"] = {"name": student}
        elif student is None:
            payload["student"] = {}
        equations = payload.get("equations")
        if isinstance(equations, dict):
            payload["equations"] = [equations]
        elif equations is None:
            payload["equations"] = []
        elif isinstance(equations, list):
            cleaned = []
            for item in equations:
                if isinstance(item, str):
                    cleaned.append({"raw": item})
                elif isinstance(item, dict):
                    cleaned.append(item)
                else:
                    # Already a TranscribedEquation (e.g. multi-page merge).
                    cleaned.append(item)
            payload["equations"] = cleaned
        notes = payload.get("notes")
        payload["notes"] = "" if notes is None else str(notes)
        return payload

    @field_validator("equations")
    @classmethod
    def _limit_equations(cls, value: list[TranscribedEquation]) -> list[TranscribedEquation]:
        return value[:80]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0


class TranscriptionResult(BaseModel):
    transcription: Transcription
    usage: Usage
    model: str = ""
    cost_cny: float = 0.0
    latency_ms: int = 0
    raw_text: str = ""
