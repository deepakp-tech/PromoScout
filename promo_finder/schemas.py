"""Pydantic schemas used for LLM structured output.

The LLM only ever refers to beat IDs (e.g. "E07-B023"); real timestamps are looked up in code.
"""
from typing import Literal

from pydantic import BaseModel, Field


class SegmentRef(BaseModel):
    episode: int = Field(description="Episode number the segment comes from")
    start_beat: str = Field(description="Beat ID where the segment starts, e.g. E07-B023")
    end_beat: str = Field(description="Beat ID where the segment ends (inclusive)")


class CandidatePromo(BaseModel):
    title: str = Field(description="3-6 word internal name for the promo")
    segments: list[SegmentRef] = Field(
        description="1 segment for a continuous clip, 2-3 to stitch moments; in playback order")
    hook_beat: str = Field(description="Beat ID of the hook; must be in the FIRST segment, near its start")
    cliffhanger_beat: str = Field(description="Beat ID of the cliffhanger; must be the end of the LAST segment")
    hook: str = Field(description="What happens in the first 3 seconds that stops the scroll")
    cliffhanger: str = Field(description="The unresolved moment the clip cuts on")
    why: str = Field(description="One line on why this promo works")
    self_score: int = Field(ge=1, le=10, description="Your honest 1-10 rating of this promo")


class EpisodeCandidates(BaseModel):
    promos: list[CandidatePromo]


class Judgement(BaseModel):
    hook_score: int = Field(ge=0, le=10, description="Would the first 3 seconds stop a scrolling stranger?")
    cliffhanger_score: int = Field(ge=0, le=10, description="Does it cut on an unresolved moment that demands 'what next'?")
    standalone_score: int = Field(ge=0, le=10, description="Can someone who never saw the show follow it?")
    spoiler_risk: int = Field(ge=0, le=10, description="How much a major twist is given away (10 = ruins it)")
    verdict: Literal["post", "maybe", "reject"]
    issues: list[str] = Field(default_factory=list, description="Concrete problems, empty if none")
