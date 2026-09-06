"""AWS Lambda handler for the personal_assistant agent.

Adapted from agent1.py (the interactive CLI version). Differences:
  - No REPL loop / input() — one event in, one response out.
  - Conversation history lives in DynamoDB (SESSIONS_TABLE env var), keyed by
    session_id, instead of an in-process ConversationMemory — Lambda
    containers are ephemeral and may not be reused between turns.
  - Secrets (ANTHROPIC_API_KEY, AGENTSPAN_SERVER_URL, ...) come from the
    Lambda environment / Secrets Manager, not a local .env file.

Expects an API Gateway / Function URL proxy event with a JSON body:
    {"session_id": "abc123", "prompt": "what time is it?"}
Returns:
    {"statusCode": 200, "body": "{\"answer\": \"...\"}"}
"""

import json
import logging
import multiprocessing
import os
from datetime import datetime

# Same fix as agent1.py/agent3.py: agentspan's @tool wrapper can't survive
# multiprocessing's 'spawn' start method. Lambda's runtime is a real Linux
# container, so 'fork' works here too.
if multiprocessing.get_start_method(allow_none=True) is None:
    multiprocessing.set_start_method("fork")

import boto3
from agentspan.agents import Agent, AgentRuntime, ConversationMemory, tool

logging.basicConfig(level=logging.WARNING)
logging.getLogger("agentspan").setLevel(logging.WARNING)
logging.getLogger("conductor").setLevel(logging.WARNING)

MAX_MESSAGES = 5


@tool
def current_date_time() -> str:
    """returns the current local time"""
    return datetime.now().strftime("%Y-%m-%d %H-%M-%S")


_sessions_table = boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])


def _load_history(session_id: str) -> list[dict]:
    item = _sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    return item["messages"] if item else []


def _save_history(session_id: str, history: list[dict]) -> None:
    _sessions_table.put_item(
        Item={"session_id": session_id, "messages": history[-MAX_MESSAGES:]}
    )


def _build_assistant(history: list[dict]) -> Agent:
    memory = ConversationMemory(max_messages=MAX_MESSAGES)
    for msg in history[-MAX_MESSAGES:]:
        if msg["role"] == "user":
            memory.add_user_message(msg["content"])
        else:
            memory.add_assistant_message(msg["content"])
    return Agent(
        name="personal_assistant",
        model="anthropic/claude-sonnet-5",
        instructions=(
            "You are concise personal assistant and use tools when they help "
            "and remember useful details across turns"
        ),
        tools=[current_date_time],
        memory=memory,
    )


def handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid JSON body"})}

    session_id = body.get("session_id")
    prompt = (body.get("prompt") or "").strip()
    if not session_id or not prompt:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "session_id and prompt are required"}),
        }

    history = _load_history(session_id)
    assistant = _build_assistant(history)

    with AgentRuntime() as runtime:
        result = runtime.run(assistant, prompt)

    answer = result.output.get("result")

    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": answer})
    _save_history(session_id, history)

    return {"statusCode": 200, "body": json.dumps({"answer": answer})}
