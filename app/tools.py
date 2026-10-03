import json
import re
from pathlib import Path, PureWindowsPath


class WebsiteTools:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.project_path: str | None = None

    def safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("A non-empty relative path is required")

        windows_path = PureWindowsPath(relative_path)
        normalized = relative_path.replace("\\", "/")
        relative = Path(normalized)
        if (
            relative.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or windows_path.root
            or any(part == ".." for part in relative.parts)
            or any(part == ".." for part in windows_path.parts)
        ):
            raise ValueError("Access outside generated-sites is not allowed")

        resolved = (self.workspace / relative).resolve()
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise ValueError("Access outside generated-sites is not allowed")
        return resolved

    @staticmethod
    def _directory_name(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A project directory name is required")

        candidate = value.strip()
        windows_path = PureWindowsPath(candidate)
        if (
            "/" in candidate
            or "\\" in candidate
            or Path(candidate).is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or candidate in {".", ".."}
        ):
            raise ValueError("Project directory must be a single relative name")

        name = re.sub(r"[^a-zA-Z0-9]+", "-", candidate).strip("-").lower()
        if not name:
            raise ValueError("Project directory name must contain letters or numbers")
        return name[:64].rstrip("-")

    def create_directory(self, path: str) -> str:
        if self.project_path is not None:
            raise ValueError(
                f"This run already owns generated-sites/{self.project_path}"
            )

        name = self._directory_name(path)
        self.workspace.mkdir(parents=True, exist_ok=True)
        suffix = 1
        while True:
            candidate = name if suffix == 1 else f"{name}-{suffix}"
            target = self.safe_path(candidate)
            try:
                target.mkdir()
                self.project_path = candidate
                return f"Directory created successfully: {candidate}"
            except FileExistsError:
                suffix += 1

    def _project_file(self, path: str) -> Path:
        if self.project_path is None:
            raise ValueError("Create a project directory before accessing its files")

        target = self.safe_path(path)
        project_root = self.safe_path(self.project_path)
        if target != project_root and project_root not in target.parents:
            raise ValueError("File access is limited to this run's website project")
        return target

    def write_file(self, path: str, content: str) -> str:
        if not isinstance(content, str):
            raise ValueError("File content must be text")
        target = self._project_file(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return (
            "File written successfully: "
            + target.relative_to(self.workspace).as_posix()
        )

    def read_file(self, path: str) -> str:
        target = self._project_file(path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return target.read_text(encoding="utf-8")

    def list_files(self, path: str) -> str:
        target = self._project_file(path)
        if not target.is_dir():
            raise NotADirectoryError(f"Directory not found: {path}")
        entries = sorted(
            item.relative_to(self.workspace).as_posix()
            for item in target.rglob("*")
        )
        return "\n".join(entries) if entries else "No files found"

    def execute(self, name: str, arguments: str) -> str:
        try:
            values = json.loads(arguments)
            if not isinstance(values, dict):
                raise ValueError("Tool arguments must be a JSON object")

            functions = {
                "createDirectory": self.create_directory,
                "writeFile": self.write_file,
                "readFile": self.read_file,
                "listFiles": self.list_files,
            }
            function = functions.get(name)
            if function is None:
                return f"Tool error: Unknown tool '{name}'"
            return str(function(**values))
        except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
            return f"Tool error: {exc}"


def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
            },
        },
    }


WEBSITE_TOOLS = [
    _tool(
        "createDirectory",
        "Create the new project directory for this website. Use a unique, "
        "lowercase, hyphenated name as a single folder name.",
        {"path": {"type": "string"}},
    ),
    _tool(
        "writeFile",
        "Write UTF-8 text to a file in the active project. Pass a path beginning "
        "with the project directory returned by createDirectory.",
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    ),
    _tool(
        "readFile",
        "Read a file in the active project. Pass a path beginning with the "
        "project directory returned by createDirectory.",
        {"path": {"type": "string"}},
    ),
    _tool(
        "listFiles",
        "List files and folders in the active project. Pass the project "
        "directory returned by createDirectory.",
        {"path": {"type": "string"}},
    ),
]
