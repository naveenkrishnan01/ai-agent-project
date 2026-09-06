import logging
import os
import re
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Silence Firecrawl's Pydantic "field name shadows attribute" warnings before
# the SDK is imported anywhere in the process.
warnings.filterwarnings("ignore", message='Field name "json" in .* shadows an attribute')

import multiprocessing

# agentspan 0.2.0 wraps every @tool function in a dynamically-created closure
# (agentspan.agents.runtime._dispatch.make_tool_worker) whose __module__ still
# points at _dispatch.py even after its __qualname__ is renamed to match the
# tool. Under multiprocessing's 'spawn' start method, worker processes are
# started by pickling that closure *by reference* (module + qualname), which
# fails immediately (PicklingError) since _dispatch.py has no such top-level
# attribute, and even if patched to have one, a fresh closure rebuilt in the
# spawned child has no relation to the one the parent registered.
#
# conductor-python (agentspan's task-runner dependency) unconditionally forces
# 'spawn' at import time, but only inside a try/except that swallows
# RuntimeError ("context has already been set"). Setting 'fork' ourselves
# before agentspan is imported wins the race: child processes are then
# created via os.fork(), which copies the whole process image instead of
# pickling the target, sidestepping the bug entirely.
# See https://github.com/conductor-oss/conductor-python/issues/264
multiprocessing.set_start_method("fork")

from agentspan.agents import Agent, AgentRuntime, run, tool


load_dotenv(override=True)
logging.basicConfig(level=logging.WARNING, force=True)
logging.disable(logging.INFO)

MODES = {"sequential", "parallel", "nested", "worker"}
REPORTS_DIR = Path("reports")
MAX_PAGE_CHARS = 4000


# Searches the web using the Firecrawl API and returns a list of results with titles, URLs, and descriptions.
@tool
def search_web(query: str, limit: int = 5) -> list[dict]:
    """Search the web with Firecrawl. Returns a list of {title, url, description}."""
    from firecrawl import Firecrawl

    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
    response = fc.search(query, limit=limit)
    return [
        {"title": r.title or "", "url": r.url or "", "description": r.description or ""}
        for r in (response.web or [])
    ]

# Scrapes a specific web page using Firecrawl, extracts its markdown content, and truncates it to fit context limits.
@tool
def fetch_page(url: str) -> str:
    """Fetch a web page as markdown via Firecrawl. Truncated for the LLM context."""
    from firecrawl import Firecrawl

    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
    document = fc.scrape(url, formats=["markdown"])
    markdown = document.markdown or ""
    return markdown[:MAX_PAGE_CHARS] if markdown else f"No content found at {url}."

# Core research agent equipped with web searching and page scraping tools to gather cited source material.
researcher = Agent(
    name="researcher",
    model="anthropic/claude-sonnet-5",
    instructions=(
        "Research the topic thoroughly. Call search_web first, then fetch_page on "
        "the most relevant results. Write factual notes citing each claim. "
        "Always end your output with a '## Sources' section listing every URL you "
        "actually fetched, one per line, as markdown links: '- [title](url)'."
    ),
    tools=[search_web, fetch_page],
)

# Content synthesis agent tasked with organizing raw research notes into a coherent, structured article format.
writer = Agent(
    name="writer",
    model="anthropic/claude-sonnet-5",
    instructions=(
        "Turn research notes into a clear, well-structured article. "
        "Preserve the '## Sources' section verbatim at the end."
    ),
)

# Quality assurance agent responsible for refining text flow, grammar, and readability without breaking source links.
editor = Agent(
    name="editor",
    model="anthropic/claude-sonnet-5",
    instructions=(
        "Polish the article for publication. Improve clarity and tighten writing. "
        "Do not modify or remove the '## Sources' section."
    ),
)
# Domain specialist agent focused on evaluating market sizing, adoption vectors, and commercial opportunities.
market_analyst = Agent(
    name="market",
    model="anthropic/claude-sonnet-5",
    instructions="Analyze market opportunity and adoption trends.",
)

# Domain specialist agent focused on mapping out operational vulnerabilities, technical blockers, and security bugs.
risk_analyst = Agent(
    name="risk",
    model="anthropic/claude-sonnet-5",
    instructions="Analyze technical, security, and operational risks.",
)

# Domain specialist agent focused on modeling monetization strategies, cost overhead structures, and financial impact.
financial_analyst = Agent(
    name="financial",
    model="anthropic/claude-sonnet-5",
    instructions="Analyze business model and financial impact.",
)

# A supervisor agent that manages the market, risk, and financial analysts concurrently, compiling their work into a single file.
analysis_team = Agent(
    name="analysis_team",
    model="anthropic/claude-sonnet-5",
    instructions="Synthesize the analyst outputs into one concise brief.",
    agents=[market_analyst, risk_analyst, financial_analyst],
    strategy="parallel",
)

# pipeline flow
# A linear pipeline where information flows sequentially from data gathering to draft generation, and finally to review.
publish_pipeline = researcher >> writer >> editor
# A deep multi-tier pipeline that starts with high-level parallel strategic analysis before feeding those insights into the standard research and publishing loop.
nested_pipeline = analysis_team >> researcher >> writer >> editor

# Converts a raw topic text string into a clean, lower-case, URL-safe alphanumeric string for file naming.
def slugify(text: str) -> str:
    """Convert a topic into a safe filename slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "report"

# Formats raw agent outputs (handling both strings and dictionaries with sub-results) into structured markdown sections.
def render_output(output) -> str:
    """Render the agent's output dict (or string) as clean markdown."""
    if isinstance(output, str):
        return output
    if not isinstance(output, dict):
        return str(output)

    sections = []
    main = output.get("result")
    if main:
        sections.append(str(main).strip())

    sub_results = output.get("subResults") or {}
    for name, body in sub_results.items():
        if body:
            sections.append(f"## {name.title()}\n\n{str(body).strip()}")

    return "\n\n---\n\n".join(sections) if sections else str(output)

# Handles directories, renders the formatted markdown content, and writes the completed file to the reports folder.
def save_report(mode: str, topic: str, output) -> Path:
    """Write the final report to reports/<mode>-<slug>.md and return the path."""
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"{mode}-{slugify(topic)}.md"
    body = render_output(output)
    path.write_text(f"# {topic}\n\n_Mode: {mode}_\n\n{body}\n")
    return path

# Sets up the AgentRuntime instance, routes the chosen execution path, tracks status, and saves the final result.
def run_pipeline(mode: str, topic: str) -> None:
    pipelines = {
        "sequential": publish_pipeline,
        "parallel": analysis_team,
        "nested": nested_pipeline,
    }
    with AgentRuntime() as runtime:
        result = run(pipelines[mode], topic, runtime=runtime)
        print("Execution ID:", result.execution_id)
        print("Status:", result.status)
        path = save_report(mode, topic, result.output)
        print(f"Report saved to {path}")

# Initializes the agent runtime environment as a continuous background listener to process remote distributed worker tasks.
def serve_worker() -> None:
    with AgentRuntime() as runtime:
        runtime.serve(nested_pipeline, blocking=True)


# Manages a command-line interface loop to prompt the user to choose a valid workflow pipeline mode.
def prompt_mode() -> str:
    while True:
        choice = input(f"Mode {sorted(MODES)}: ").strip().lower() or "nested"
        if choice in MODES:
            return choice
        print(f"Invalid mode. Pick one of {sorted(MODES)}.")


 #Script execution entry point that handles user initialization and orchestration mode routing.
if __name__ == "__main__":
    mode = prompt_mode()
    # Runs the application as a distributed background worker node listening for orchestration tasks.
    if mode == "worker":
        serve_worker()
    # Captures the user's research target and starts the active data generation pipeline.
    else:
        topic = input("Topic: ").strip() or "AI agents in production in 2026"
        run_pipeline(mode, topic)