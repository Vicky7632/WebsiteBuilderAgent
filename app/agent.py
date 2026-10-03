import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI, OpenAIError

from .models import AgentRun, AgentState
from .tools import WEBSITE_TOOLS, WebsiteTools
from .verifier import verify_website

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
WEBSITE_WORKSPACE = (PROJECT_ROOT / "generated-sites").resolve()
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
website_history: list[dict] = []
MAX_AGENT_TURNS = 30

SYSTEM_PROMPT = """
You are an autonomous frontend website builder and coding agent. Build complete
static websites from the user's natural-language request using the available
filesystem tools.

Reason about the requested site and decide which tool to call next. Do not use
a fixed tool sequence. After every action, inspect its observation and choose
the next action accordingly. You must create files, inspect the result, then
wait for the independent verifier. If verification reports errors, repair the
website with tools, inspect the result, and allow it to be verified again.

Requirements:
- Create a unique lowercase, hyphenated project directory using
  createDirectory. Use the exact returned directory path for every later tool.
- Always create index.html and style.css. Add script.js when useful.
- Use semantic, accessible HTML, responsive CSS, and vanilla JavaScript only.
- Do not use React, Next.js, npm, a build system, or backend code.
- Adapt content, sections, and design to the actual request.
- Use placeholders when information is missing; do not invent sensitive data.
- Use only the four supplied filesystem tools. Tool paths must remain within
  generated-sites and within the current project directory.
- Treat every tool result as an observation. A tool error is not success:
  reason about it and select a corrective action.
- Finish only after verification succeeds. Return a concise completion report,
  not the generated source code.
"""


def _assistant_message(reply) -> dict:
    if hasattr(reply, "model_dump"):
        return reply.model_dump(exclude_none=True)
    if hasattr(reply, "dict"):
        return reply.dict(exclude_none=True)
    return {
        "role": "assistant",
        "content": getattr(reply, "content", None),
        "tool_calls": getattr(reply, "tool_calls", None),
    }


def _completion_message(project_name: str, files: list[str]) -> str:
    return (
        "Website created and verified successfully.\n"
        f"Project: {project_name}\n"
        f"Location: generated-sites/{project_name}\n"
        "Files:\n"
        + "\n".join(f"- {name}" for name in files)
    )


def run_agent(
    user_prompt: str,
    on_event: Callable[[dict], None] | None = None,
) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured in the PortfolioAgent .env file.",
        )

    WEBSITE_WORKSPACE.mkdir(parents=True, exist_ok=True)
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    tools = WebsiteTools(WEBSITE_WORKSPACE)
    run = AgentRun()

    def transition(state: AgentState, message: str) -> None:
        run.transition(state)
        if on_event is not None:
            on_event(
                {
                    "state": state.value,
                    "message": message,
                    "project_name": tools.project_path,
                }
            )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *website_history,
        {"role": "user", "content": user_prompt},
    ]

    for _ in range(MAX_AGENT_TURNS):
        transition(AgentState.PLANNING, "Agent is deciding its next action.")
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=WEBSITE_TOOLS,
            )
        except OpenAIError as exc:
            print("========== GROQ ERROR ==========")
            print(type(exc).__name__)
            print(str(exc))
            print("================================")

            transition(
                AgentState.FAILED,
                f"The Groq request failed: {exc}",
            )

            raise HTTPException(
                status_code=502,
                detail=f"Groq API request failed: {exc}",
            ) from exc
        if not response.choices:
            transition(AgentState.FAILED, "Groq returned an empty response.")
            raise HTTPException(status_code=502, detail="Groq returned an empty response.")

        reply = response.choices[0].message
        calls = reply.tool_calls or []
        if calls:
            messages.append(_assistant_message(reply))
            for call in calls:
                transition(
                    AgentState.ACTING,
                    f"Agent called {call.function.name}.",
                )
                result = tools.execute(
                    call.function.name,
                    call.function.arguments,
                )
                transition(
                    AgentState.OBSERVING,
                    f"{call.function.name} observation: {result}",
                )
                run.observations.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )
                if tools.project_path is not None:
                    run.project_path = tools.project_path
            continue

        transition(
            AgentState.INSPECTING,
            "Agent finished its proposed edits; inspecting generated files.",
        )
        transition(
            AgentState.VERIFYING,
            "Independent verifier is checking the generated website.",
        )
        verification = verify_website(tools)
        observation = verification.observation()
        run.observations.append(observation)
        transition(
            AgentState.VERIFYING,
            observation,
        )

        if verification.passed and tools.project_path is not None:
            transition(
                AgentState.DONE,
                "Website verification passed.",
            )
            result = _completion_message(
                tools.project_path,
                verification.files,
            )
            website_history.extend(
                [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": result},
                ]
            )
            return result

        transition(
            AgentState.REPAIRING,
            "Verification failed; returning the errors to the agent for repair.",
        )
        messages.append(_assistant_message(reply))
        messages.append(
            {
                "role": "user",
                "content": (
                    "Independent website verification returned this observation:\n"
                    f"{observation}\n"
                    "Use the filesystem tools to repair the project, inspect your "
                    "changes, and then provide your completion response."
                ),
            }
        )

    transition(
        AgentState.FAILED,
        "The agent reached its action limit before verification passed.",
    )
    raise HTTPException(
        status_code=502,
        detail=(
            "The website agent reached its action limit before the website "
            "passed verification."
        ),
    )
