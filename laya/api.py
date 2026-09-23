import json
import math
import time
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, Literal

import httpx
import laya
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

agent: Any = None
model_name = "convaiinnovations/laya"
model_subfolder = "multilingual"
inference_lock = Lock()


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice", "score", "noul"]
    instructions: str = Field(min_length=1)
    criteria: list[Any] | dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_question(self):
        if not self.instructions.strip():
            raise ValueError("instructions must not be blank")
        criteria = self.criteria
        if self.type == "choice":
            if not criteria or len(criteria) < 2:
                raise ValueError("choice requires at least two options")
            labels = list(criteria)
            if any(not isinstance(label, str) or not label.strip() for label in labels):
                raise ValueError("choice labels must be non-empty strings")
            if len(set(labels)) != len(labels):
                raise ValueError("choice labels must be unique")
        elif self.type == "score":
            if not isinstance(criteria, list) or len(criteria) < 2:
                raise ValueError("score requires an ordered list of at least two levels")
        elif criteria is not None:
            if not isinstance(criteria, dict) or set(criteria) - {"false", "true"}:
                raise ValueError("noul criteria accepts only false and true keys")
        return self


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str | dict[str, Any] = Field(description="判断対象の入力または状態")
    schema_: dict[str, Question] = Field(alias="schema", min_length=1, description="判断項目の定義")

    @field_validator("input")
    @classmethod
    def validate_input(cls, value):
        if not value or (isinstance(value, str) and not value.strip()):
            raise ValueError("input must not be empty")
        json.dumps(value, allow_nan=False)
        return value

    @field_validator("schema_")
    @classmethod
    def validate_schema(cls, value):
        if any(not key.strip() for key in value):
            raise ValueError("question IDs must not be blank")
        json.dumps({key: q.model_dump() for key, q in value.items()}, allow_nan=False)
        return value


def is_connection_error(error: BaseException | None) -> bool:
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, httpx.TransportError):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


def load_agent() -> Any:
    for attempt in range(1, 5):
        try:
            return laya.load(model_name, subfolder=model_subfolder, device="cuda")
        except Exception as error:
            if not is_connection_error(error) or attempt == 4:
                raise RuntimeError("Layaモデルのロードに失敗しました") from error
            time.sleep(2**attempt)


def require_gpu() -> None:
    if agent is None:
        raise HTTPException(status_code=503, detail="model is loading")
    if agent.device.type != "cuda":
        raise HTTPException(status_code=503, detail="GPU model is unavailable; restart required")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global agent
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable inside the container")
    print(f"Using GPU: {torch.cuda.get_device_name(0)}", flush=True)
    agent = load_agent()
    require_gpu()
    try:
        yield
    finally:
        agent = None


app = FastAPI(title="Laya Decision API", version="1.0.0", lifespan=lifespan)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    require_gpu()
    return {"status": "ready"}


@app.get("/v1/metadata")
def metadata() -> dict[str, Any]:
    return {
        "model": model_name,
        "subfolder": model_subfolder,
        "schemas": [],
        "device": str(agent.device) if agent is not None else None,
    }


def decision_confidence(answers: dict[str, Any]) -> float | None:
    confidences = [answer.get("confidence") for answer in answers.values()]
    if not confidences or any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or not 0 <= value <= 1
        for value in confidences
    ):
        return None
    return min(confidences)


@app.post("/v1/decide")
def decide(request: DecisionRequest) -> dict[str, Any]:
    require_gpu()
    input_text = (
        request.input if isinstance(request.input, str)
        else json.dumps(request.input, ensure_ascii=False, sort_keys=True)
    )
    schema = {key: q.model_dump(exclude_none=True) for key, q in request.schema_.items()}
    with inference_lock:
        require_gpu()
        try:
            answers = agent.predict(input_text, schema)["answers"]
            if set(answers) != set(schema) or any(not isinstance(a, dict) for a in answers.values()):
                raise ValueError("incomplete model response")
            json.dumps(answers, allow_nan=False)
        except ValueError as error:
            if "options exceed head_max_len=" in str(error):
                raise HTTPException(status_code=422, detail="schema exceeds model option budget") from error
            raise HTTPException(status_code=500, detail="Laya decision failed") from error
        except Exception as error:
            raise HTTPException(status_code=500, detail="Laya decision failed") from error
        require_gpu()
    return {
        "answers": answers,
        "confidence": decision_confidence(answers),
        "model": {"name": model_name, "subfolder": model_subfolder},
    }
