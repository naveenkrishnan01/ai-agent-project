"""Invokes the deployed personal_assistant AgentCore Runtime.

Reuse the same SESSION_ID across a conversation's turns — AgentCore routes
repeat invocations for the same runtimeSessionId to the same warm microVM,
which is what makes the in-process ConversationMemory in agentcore_app.py
work across turns.

Usage:
    RUNTIME_ARN=arn:aws:bedrock-agentcore:...:runtime/personal_assistant-xxxxx \\
    SESSION_ID=00000000-0000-0000-0000-000000000000-conversation-1 \\
    uv run invoke_agentcore.py "What time is it?"
"""

import json
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-1")


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Hello!"
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    response = client.invoke_agent_runtime(
        agentRuntimeArn=os.environ["RUNTIME_ARN"],
        runtimeSessionId=os.environ["SESSION_ID"],  # must be 33+ characters
        payload=json.dumps({"prompt": prompt}),
        contentType="application/json",  # without this, FastAPI's automatic
        accept="application/json",       # JSON-body parsing doesn't trigger,
        qualifier="DEFAULT",              # even though the payload is valid JSON
    )

    body = json.loads(response["response"].read())
    print("Assistant:", body.get("answer"))


if __name__ == "__main__":
    main()
