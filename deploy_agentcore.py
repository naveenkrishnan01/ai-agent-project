"""Creates the AgentCore Runtime for the personal_assistant agent.

Prerequisites (see docker/agentcore/README steps in the chat guidance):
  1. Image built for linux/arm64 and pushed to ECR.
  2. An execution role created with the trust policy + permissions documented at
     https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html
     (ECR pull, CloudWatch Logs, X-Ray, cloudwatch:PutMetricData, workload
     access token — NOT bedrock:InvokeModel, since this agent calls Anthropic
     directly rather than an AWS-hosted foundation model).

Usage:
    IMAGE_URI=<account-id>.dkr.ecr.<region>.amazonaws.com/personal-assistant:latest \\
    ROLE_ARN=arn:aws:iam::<account-id>:role/AgentRuntimeExecutionRole \\
    ANTHROPIC_API_KEY=sk-ant-... \\
    uv run deploy_agentcore.py
"""

import os

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-1")


def main() -> None:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    response = client.create_agent_runtime(
        agentRuntimeName="personal_assistant",
        agentRuntimeArtifact={
            "containerConfiguration": {"containerUri": os.environ["IMAGE_URI"]}
        },
        roleArn=os.environ["ROLE_ARN"],
        networkConfiguration={"networkMode": "PUBLIC"},
        environmentVariables={
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
        },
        lifecycleConfiguration={
            "idleRuntimeSessionTimeout": 900,  # 15 min
            "maxLifetime": 28800,  # 8 hours
        },
    )

    print("Agent Runtime created.")
    print("ARN:", response["agentRuntimeArn"])
    print("Status:", response["status"])


if __name__ == "__main__":
    main()
