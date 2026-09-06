"""FastAPI wrapper around agent1.py's personal_assistant, for Amazon Bedrock
AgentCore Runtime.

Unlike the Lambda handler, this keeps a module-level Agent + ConversationMemory
(as agent1.py's CLI version does) rather than reloading history from external
storage per-request. AgentCore Runtime gives each runtimeSessionId its own
isolated microVM that survives idle periods (up to maxLifetime, default 8h) —
repeat invocations for the same session land on the same container, so
in-process memory works across turns without a database.

Contract required by AgentCore Runtime (see AWS docs):
  - Host 0.0.0.0, port 8080, linux/arm64 container.
  - POST /invocations: JSON in, JSON (or SSE) out.
  - GET /ping: {"status": "Healthy" | "HealthyBusy"} for health checks.
"""

import logging
import multiprocessing
from datetime import datetime

# Same fix as agent1.py/agent3.py: agentspan's @tool wrapper can't survive
# multiprocessing's 'spawn' start method (forced by conductor-python at
# import time). 'fork' works fine in this container's Linux environment.
# See https://github.com/conductor-oss/conductor-python/issues/264
if multiprocessing.get_start_method(allow_none=True) is None:
    multiprocessing.set_start_method("fork")

from fastapi import FastAPI
from pydantic import BaseModel

from agentspan.agents import Agent, AgentRuntime, ConversationMemory, tool

logging.basicConfig(level=logging.WARNING)
logging.getLogger("agentspan").setLevel(logging.WARNING)
logging.getLogger("conductor").setLevel(logging.WARNING)

app = FastAPI(title="personal_assistant (AgentCore)")


@tool
def current_date_time() -> str:
    """returns the current local time"""
    return datetime.now().strftime("%Y-%m-%d %H-%M-%S")


conversation_memory = ConversationMemory(max_messages=5)

assistant = Agent(
    name="personal_assistant",
    model="anthropic/claude-sonnet-5",
    instructions=(
        "You are concise personal assistant and use tools when they help "
        "and remember useful details across turns"
    ),
    tools=[current_date_time],
    memory=conversation_memory,
)


class InvocationRequest(BaseModel):
    prompt: str


class InvocationResponse(BaseModel):
    answer: str


@app.post("/invocations", response_model=InvocationResponse)
def invoke(request: InvocationRequest) -> InvocationResponse:
    with AgentRuntime() as runtime:
        result = runtime.run(assistant, request.prompt)

    answer = result.output.get("result")
    conversation_memory.add_user_message(request.prompt)
    conversation_memory.add_assistant_message(answer)
    return InvocationResponse(answer=answer)


@app.get("/ping")
def ping() -> dict:
    return {"status": "Healthy"}
