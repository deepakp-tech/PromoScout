"""Model factory. The whole pipeline talks to models only through `structured()`,
so swapping Gemini -> Groq -> OpenAI -> Claude is a one-line .env change.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from . import config

_factory_override: Callable | None = None  # tests inject a fake model here
CACHE_DIR = Path(".cache")


def set_model_factory(fn: Callable | None):
    """fn(model_name) -> chat model. Used by tests to run offline."""
    global _factory_override
    _factory_override = fn
    _model.cache_clear()


@lru_cache(maxsize=None)
def _model(name: str):
    if _factory_override:
        return _factory_override(name)
    from langchain.chat_models import init_chat_model
    from langchain_core.rate_limiters import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(requests_per_second=config.REQUESTS_PER_SECOND,
                                  check_every_n_seconds=0.1, max_bucket_size=1)
    return init_chat_model(name, temperature=config.TEMPERATURE, rate_limiter=limiter)


def model_name(role: str) -> str:
    return {"finder": config.MODEL_FINDER, "judge": config.MODEL_JUDGE}.get(role, config.MODEL)


def structured(role: str, schema: type[BaseModel]):
    llm = _model(model_name(role)).with_structured_output(schema)
    return llm.with_retry(stop_after_attempt=3) if hasattr(llm, "with_retry") else llm


def call(role: str, schema: type[BaseModel], system: str, user: str, use_cache: bool = True) -> BaseModel:
    """Structured LLM call with a disk cache, so a crashed free-tier run resumes cheaply."""
    key = hashlib.sha256(json.dumps(
        [model_name(role), config.PROMPT_VERSION, schema.__name__, system, user]).encode()).hexdigest()[:24]
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists() and not _factory_override:
        return schema.model_validate_json(path.read_text())
    result = structured(role, schema).invoke([("system", system), ("human", user)])
    if result is None:
        raise ValueError(f"{model_name(role)} returned no structured output")
    if not isinstance(result, schema):  # some providers return dicts
        result = schema.model_validate(result)
    if use_cache and not _factory_override:
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(result.model_dump_json())
    return result
