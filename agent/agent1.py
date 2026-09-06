import logging
from datetime import datetime
from dotenv import load_dotenv

import multiprocessing

# agentspan wraps every @tool function in a dynamically-created closure whose
# __module__ still points at agentspan.agents.runtime._dispatch even after its
# __qualname__ is renamed to match the tool. Under multiprocessing's 'spawn'
# start method (forced by conductor-python at import time), worker processes
# are started by pickling that closure by reference (module + qualname),
# which fails since _dispatch.py has no such top-level attribute. Setting
# 'fork' ourselves before agentspan is imported avoids pickling entirely.
# See https://github.com/conductor-oss/conductor-python/issues/264
multiprocessing.set_start_method("fork")

from agentspan.agents import Agent, AgentRuntime, ConversationMemory, run, tool

load_dotenv()
logging.basicConfig(level=logging.WARNING)
logging.getLogger("agentspan").setLevel(logging.WARNING)
logging.getLogger("conductor").setLevel(logging.WARNING)

# tool calling 
@tool
def current_date_time()-> str:
    """returns the curret local time"""
    return datetime.now().strftime("%Y-%m-%d %H-%M-%S")

# memory fo the agent
conversationMemory = ConversationMemory(max_messages=5)

#putting all together
#name of the agent
#llm model that is used
#instruction for the agent to follow
#tools that the agent can use to get the information, in the case current_date_time
#memory limit of the conversation , in this case 5 messages from the past conversation
asistant = Agent(
    name="personal_assistant",
    model="anthropic/claude-sonnet-5",
    instructions=("You are concise personal assistant and use tools when they help"
    "and rememer useful details across turns"),
    tools=[current_date_time],
    memory=conversationMemory,
)

#Script execution entry point.
if __name__ == "__main__":
    print("Starting Agent ..")
    # Initializes and manages the life cycle of the Agent Span runtime session.
    with AgentRuntime() as runtime:
        # Starts a continuous interactive command-line interface conversation loop.
        while True:
            prompt = input("You ").strip()
            # Provides a clean exit condition to terminate the loop when the user enters 'q'.
            if prompt.lower() == "q":
                break
            # Skips the current iteration to prevent empty inputs from crashing the agent runtime.
            if not prompt:
                continue
            # Dispatches the user input to the assistant agent and waits for the execution result.
            result = runtime.run(asistant, prompt)
            # Extracts the raw text generation string out of the runtime wrapper's output dictionary.
            readable_result = result.output.get('result')
            conversationMemory.add_user_message(prompt) # add memory for prompt
            conversationMemory.add_assistant_message(readable_result) # add memory for the response
            # Displays the final generated text response back to the user in the console.
            print(f"Assistant: {readable_result}")
