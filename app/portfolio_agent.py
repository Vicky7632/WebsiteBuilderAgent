import json
import os
import re
import unicodedata
from pathlib import Path, PureWindowsPath

from dotenv import load_dotenv
from fastapi import HTTPException
from openai import OpenAI, OpenAIError

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
website_workspace = (PROJECT_ROOT / "generated-sites").resolve()
website_history = []
model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

WEBSITE_SYSTEM_PROMPT = """
You are an expert autonomous frontend website builder.

Your job is to turn a user's natural-language request into a complete static website.
You must actually create the website files using the provided tools. Do not simply return HTML, CSS, or JavaScript in the final response.

Rules:
- Always create a separate project directory for each website.
- Use lowercase, hyphenated names for project directories.
- Always create index.html and style.css.
- Create script.js when JavaScript is useful.
- Use only HTML, CSS, and vanilla JavaScript.
- Do not use React, Next.js, npm, backend code, or build tools.
- Adapt the structure to the user's request.
- Make the site modern, responsive, and accessible.
- Use placeholder content when needed; do not invent sensitive personal information.
- Use the filesystem tools to create and inspect files.
- After creating the files, listFiles and read important files when needed.
- Fix obvious issues before finishing.
- Never access files outside generated-sites.
- Return a concise completion message only after the website files exist.
"""


def safe_path(relative_path):
    if relative_path is None:
        raise ValueError("Path is required")

    raw = str(relative_path)
    if not raw.strip():
        raise ValueError("Path is required")

    windows = PureWindowsPath(raw)
    relative = Path(raw.replace("\\", "/"))

    if (
        raw in {".", ".."}
        or relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part == ".." for part in relative.parts)
        or any(part == ".." for part in windows.parts)
    ):
        raise ValueError("Access outside generated-sites is not allowed")

    resolved = (website_workspace / relative).resolve()

    if resolved != website_workspace and website_workspace not in resolved.parents:
        raise ValueError("Access outside generated-sites is not allowed")

    return resolved


def slugify(value):
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = slug[:60].rstrip("-")
    return slug or "website"


def _tool(name, description, properties):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties.keys()),
            },
        },
    }


WEBSITE_TOOLS = [
    _tool(
        "createDirectory",
        "Create a directory inside generated-sites.",
        {"path": {"type": "string"}},
    ),
    _tool(
        "writeFile",
        "Create or overwrite a text file inside generated-sites.",
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    ),
    _tool(
        "readFile",
        "Read an existing file inside generated-sites.",
        {"path": {"type": "string"}},
    ),
    _tool(
        "listFiles",
        "List files inside a website project directory.",
        {"path": {"type": "string"}},
    ),
]


def create_directory(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Directory path is required")

    target = safe_path(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Directory created successfully: {Path(path).as_posix()}"


def write_file(path, content):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("File path is required")
    if content is None:
        raise ValueError("File content is required")

    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content), encoding="utf-8")
    return f"File written successfully: {Path(path).as_posix()}"


def read_file(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("File path is required")

    target = safe_path(path)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    return target.read_text(encoding="utf-8")


def list_files(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Path is required")

    target = safe_path(path)
    if not target.exists():
        return "No files found"

    if target.is_file():
        return target.relative_to(website_workspace).as_posix()

    entries = sorted(item.relative_to(website_workspace).as_posix() for item in target.rglob("*"))
    return "\n".join(entries) if entries else "No files found"


def _unique_project_name(prompt):
    base = slugify(prompt)
    candidate = base
    counter = 1

    while True:
        target = website_workspace / candidate
        if not target.exists():
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


def _verify_project(project_name):
    project_dir = safe_path(project_name)
    if not project_dir.exists() or not project_dir.is_dir():
        raise ValueError(f"Project directory not found: {project_name}")

    listing = list_files(project_name)
    if listing == "No files found":
        raise ValueError(f"Project directory is empty: {project_name}")

    files = {Path(line).name for line in listing.splitlines() if line.strip()}
    if "index.html" not in files or "style.css" not in files:
        raise ValueError("The project must contain at least index.html and style.css")

    html = read_file(f"{project_name}/index.html")
    if 'style.css' not in html.lower():
        raise ValueError("index.html does not reference style.css")

    if "script.js" in files and 'script.js' not in html.lower():
        raise ValueError("index.html does not reference script.js")

    return sorted(files)


def generate_website(message):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured in the PortfolioAgent .env file.",
        )

    website_workspace.mkdir(parents=True, exist_ok=True)
    project_name = _unique_project_name(message)
    create_directory(project_name)

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    conversation = [
        {"role": "system", "content": WEBSITE_SYSTEM_PROMPT},
        *website_history,
        {"role": "user", "content": message},
    ]

    for _ in range(20):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=conversation,
                tools=WEBSITE_TOOLS,
            )
        except OpenAIError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Groq request failed: {exc}",
            ) from exc

        if not response.choices:
            raise HTTPException(status_code=502, detail="Groq returned an empty response.")

        reply = response.choices[0].message

        if not reply.tool_calls:
            try:
                files = _verify_project(project_name)
            except ValueError as exc:
                return f"Error: {exc}"

            summary = (
                "Website created successfully.\n\n"
                f"Project: {project_name}\n"
                f"Location: generated-sites/{project_name}\n"
                "Files:\n"
                + "\n".join(f"- {file_name}" for file_name in files)
            )
            website_history.extend(
                [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": summary},
                ]
            )
            return summary

        conversation.append(reply)

        for call in reply.tool_calls:
            try:
                arguments = json.loads(call.function.arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")

                tool_name = call.function.name
                if tool_name == "createDirectory":
                    result = create_directory(**arguments)
                elif tool_name == "writeFile":
                    result = write_file(**arguments)
                elif tool_name == "readFile":
                    result = read_file(**arguments)
                elif tool_name == "listFiles":
                    result = list_files(**arguments)
                else:
                    result = f"Unknown tool: {tool_name}"
            except (TypeError, ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
                result = f"Tool error: {exc}"

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(result),
                }
            )

    raise HTTPException(
        status_code=502,
        detail="Portfolio generation did not finish successfully.",
    )
