import time
from contextlib import asynccontextmanager
from typing import Any

import gradio as gr
import httpx
import laya
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from gradio.routes import mount_gradio_app
from pydantic import BaseModel, Field


DEFAULT_SCHEMA = {
    "department": {
        "type": "choice",
        "instructions": "Which department should handle this request?",
        "criteria": ["billing", "technical", "sales"],
    },
    "refund": {
        "type": "noul",
        "instructions": "Does the customer request a refund?",
    },
}

agent: Any = None
model_name = "convaiinnovations/laya"
model_subfolder = "multilingual"


class ClassifyRequest(BaseModel):
    message: str = Field(min_length=1)
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


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
                raise RuntimeError("Hugging FaceからLayaモデルを取得できませんでした") from error
            time.sleep(2**attempt)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global agent
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable inside the container")
    print(f"Using GPU: {torch.cuda.get_device_name(0)}", flush=True)
    agent = load_agent()
    yield


app = FastAPI(title="Laya API", version="1.0.0", lifespan=lifespan)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    if agent is None:
        raise HTTPException(status_code=503, detail="model is loading")
    return {"status": "ready"}


@app.get("/v1/metadata")
def metadata() -> dict[str, Any]:
    return {
        "model": model_name,
        "subfolder": model_subfolder,
        "schemas": ["customer_support"],
    }


@app.post("/v1/classify")
def classify(request: ClassifyRequest) -> dict[str, Any]:
    if agent is None:
        raise HTTPException(status_code=503, detail="model is loading")
    schema = request.schema_ or DEFAULT_SCHEMA
    try:
        answers = agent.predict(request.message.strip(), schema)["answers"]
    except Exception as error:
        raise HTTPException(status_code=500, detail="Laya prediction failed") from error
    return {
        "answers": answers,
        "model": {"name": model_name, "subfolder": model_subfolder},
    }


def predict_for_ui(message: str) -> tuple[str, dict[str, Any]]:
    if not message or not message.strip():
        raise gr.Error("問い合わせ文を入力してください。")
    result = classify(ClassifyRequest(message=message))
    answers = result["answers"]
    department = answers["department"]
    refund = answers["refund"]
    summary = (
        f"担当部署: {department['choice']}（信頼度 {department['confidence']:.1%}）\n"
        f"返金希望スコア: {refund['noul']:.1%}"
    )
    return summary, answers


with gr.Blocks(title="Laya 問い合わせ判定") as demo:
    gr.Markdown("# Laya 問い合わせ判定\n文章を入力すると、担当部署と返金希望を判定します。")
    message = gr.Textbox(label="問い合わせ文", lines=5)
    run = gr.Button("判定")
    summary = gr.Textbox(label="結果", lines=2)
    details = gr.JSON(label="詳細")
    run.click(predict_for_ui, inputs=message, outputs=[summary, details])
    message.submit(predict_for_ui, inputs=message, outputs=[summary, details])


app = mount_gradio_app(app, demo, path="/ui")
