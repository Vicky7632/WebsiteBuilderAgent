# PortfolioAgent

PortfolioAgent is a small FastAPI app with a browser UI that accepts a
natural-language website prompt and asks a Groq-backed AI model to build a
complete static website using tool calls.

## Project structure

- `app/main.py` serves the frontend, the job API, frontend assets, and generated sites.
- `app/agent.py` contains the autonomous agent loop.
- `app/tools.py` contains the four file tools.
- `app/verifier.py` checks generated websites and local asset references.
- `app/models.py` contains agent and verification state models.
- `frontend/` contains the browser interface.
- `generated-sites/` stores generated website projects.

## Tech stack

- Python
- FastAPI
- OpenAI-compatible Groq client
- Function/tool calling
- `pathlib`
- HTML, CSS, and vanilla JavaScript for generated websites

## How it works

The frontend sends JSON to `POST /portfolio`. The API starts a build job and
returns a job ID. The UI polls `GET /portfolio/{job_id}` to display actual
agent state transitions and tool observations while the build runs. After the
site passes verification, the API returns its project name and generated file
list. Generated sites are served under `/sites/`.

The agent uses a tool-calling loop to:

1. choose a project directory
2. create the project folder
3. write `index.html`, `style.css`, and optionally `script.js`
4. read files when needed
5. verify the project structure
6. return a short final completion message

The filesystem is restricted to `generated-sites/` via `safe_path()` to prevent access outside the app workspace.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Add your Groq API key to `.env`:

   ```env
   GROQ_API_KEY=your_key_here
   GROQ_MODEL=openai/gpt-oss-20b
   ```

## Run the app

```powershell
python -m uvicorn app.main:app --reload
```

## Test the API

Use Postman or curl with JSON:

```powershell
curl -X POST http://127.0.0.1:8000/portfolio -H "Content-Type: application/json" --data "{\"prompt\":\"Build a premium developer portfolio for Vicky Kumar with dark theme, hero, about, skills, projects, experience, education and contact.\"}"
```

The response contains `job_id`. Poll
`GET http://127.0.0.1:8000/portfolio/<job_id>` for progress and the completed
project/file details. The generated website can then be opened at
`http://127.0.0.1:8000/sites/<project-name>/`.
