import multiprocessing

# agentspan/conductor forces multiprocessing start_method="spawn" on import,
# which requires pickling @tool functions and crashes because agentspan's
# decorator rebinds their __module__ to an unimportable dispatch path.
# Setting "fork" first (before agentspan is imported) makes conductor's own
# set_start_method call a silent no-op, and fork doesn't need to pickle the
# target function at all.
multiprocessing.set_start_method("fork")

import logging

# This looks at .env file to load the agentspan url : http://localhost:6767
from dotenv import load_dotenv

# You want to use pydantic basemodel and field to restric the LLM repsonse , rather than free-form text.
from pydantic import BaseModel, Field

# All the libraries that are imported and used for this agent
from agentspan.agents import (
    Agent,
    AgentRuntime,
    ConversationMemory,
    EventType,
    Guardrail,
    GuardrailResult,
    OnFail,
    Position,
    guardrail,
    start,
    tool,
)


load_dotenv(override=True)
# Keep the logging elvel to error or Warning, so that termnal is clean for logs 
logging.basicConfig(level=logging.WARNING, force=True)
logging.disable(logging.INFO)

# RAG COMPONENTS 
# This is mimicking a database with some mock order infor and account information
MOCK_DB = {
    "orders": {"A100": {"status": "delivered", "total": 49.99}},
    "accounts": {"tim@example.com": {"status": "active", "tier": "pro"}},
}
# This provides some informtion of rthe refund policy, shipping and account information 
# for the support agent to use in the response.
DOCS = {
    "refund policy": "Refunds are processed within 5 business days.",
    "shipping": "Standard shipping takes 3 to 7 business days.",
    "account": "Pro accounts include priority support.",
}
# This provide a strict response
# Stage : refunded when successful, rejected when not successful 
# Status : Successful ( true or false)
# message : text reply to the user
class SupportResponse(BaseModel):
    stage: str = Field(description="Stage like answered, refunded or rejected")
    successful: bool
    message: str

# Tool calling : It will look up the knwledge base in the OOC to provide the answer to the user.
@tool
def search_knowledge_base(query: str) -> str:
    """search support docs"""
    for title, body in DOCS.items():
        if title in query.lower():
            return body
    return "No matching support articles found."

# Tool calling : It will look up the order in the mock database and return the order information if found, 
# otherwise it will return an error message.
@tool
def lookup_order(order_id: str) -> dict:
    """lookup order in database by ID"""
    return MOCK_DB["orders"].get(order_id, {"error": "order not found"})

# Tool calling - This for the aprovel for refund
@tool(approval_required=True)
def process_refund(order_id: str, amount: float) -> str:
    """request a refund, pause for human approval think before you run this"""
    return f"Refunded {amount:.2f} for order {order_id}"

# This is guadrail for prompt injection
# This is to protect in case user enter prompts before it reachees AI to bypass the validation
# asking for refund, it will protect from that 

@guardrail
def safe_support_request(prompt: str) -> GuardrailResult:
    """Block obvious prompt injection attempts"""
    blocked = ["ignore", "ignore previous", "system prompt", "jailbreak"]
    passed = not any(phrase in prompt.lower() for phrase in blocked)
    return GuardrailResult(passed=passed, message="Please ask a normal question, this is blocked.")

# This puts everything together like the nae of the ageent, LLM name of the model,
# Instruction - it gives soem  personlity and rules for the reponse
# Support response - Giving some structure to the response
# tools - All the tool calling functions tht will be called
# memory - how many previous essages you want to store, 50 in this case
# guadlrails - the prompt injection protection


support_agent = Agent(
    name="support_agent",
    model="anthropic/claude-sonnet-5",
    instructions=(
        "You are a customer support agent. Use the knowledge base first. "
        "If the customer wants a refund: when you know the order ID, call "
        "lookup_order to get the amount. Before calling process_refund, "
        "write a short plain-English sentence describing exactly what refund "
        "you are about to issue, for example: 'I am going to refund $49.99 "
        "for order A100.' Then call process_refund. The tool will pause for "
        "human approval automatically. If the order ID is missing, ask the "
        "customer for it. Always populate the message field with a clear reply."
    ),
    output_type=SupportResponse,
    tools=[search_knowledge_base, lookup_order, process_refund],
    memory=ConversationMemory(max_messages=50),
    guardrails=[Guardrail(safe_support_request, position=Position.INPUT, on_fail=OnFail.RAISE)],
    max_turns=10
)
# hhere the decision is mae when to call the order_id and the anount for the order
# The re is numan-in-lioop intervention for refund.
# Only when user respond to prompt with "y", only then refund process occurs.

def run_interactive(prompt: str) -> None:
    with AgentRuntime() as runtime:
        handle = start(support_agent, prompt, runtime=runtime)
        stream = handle.stream()

        order_id, amount = None, None
        for event in stream:
            if event.type == EventType.TOOL_CALL and event.args:
                order_id = event.args.get("order_id") or order_id
            elif event.type == EventType.TOOL_RESULT and isinstance(event.result, dict):
                amount = event.result.get("total") or amount
            elif event.type == EventType.WAITING:
                print(f"\nApproval required: refund ${amount:.2f} for order {order_id}")
                decision = input("Approve? (y/n): ").lower().strip()
                if decision == "y":
                    handle.approve()
                else:
                    handle.reject("user rejected")
        
        result = stream.get_result()
        output = result.output.get("result")
        print(f"\n{output}\n")

# main entry of the orprogram.
# The agent keeps prompting for questions
# It stops only when you type q (Quit)

if __name__ == "__main__":
    print("Support bot starting....")
    while True:
        prompt = input("You: ").strip()
        if prompt.lower() == "q":
            break
        if not prompt:
            continue
        run_interactive(prompt)