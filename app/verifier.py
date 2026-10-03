from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .models import VerificationResult
from .tools import WebsiteTools


class _ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("href"):
            self.resources.append(("href", attributes["href"]))
        elif tag in {"script", "img", "source", "video", "audio"}:
            if attributes.get("src"):
                self.resources.append(("src", attributes["src"]))


def verify_website(tools: WebsiteTools) -> VerificationResult:
    project_name = tools.project_path
    if project_name is None:
        return VerificationResult(
            passed=False,
            errors=["The agent has not created a project directory."],
        )

    try:
        project_root = tools.safe_path(project_name)
        listing = tools.list_files(project_name)
        files = [
            line for line in listing.splitlines()
            if line and line != "No files found"
        ]
        relative_files = {
            Path(line).relative_to(project_name).as_posix()
            for line in files
        }
    except (OSError, ValueError) as exc:
        return VerificationResult(
            passed=False,
            project_path=project_name,
            errors=[f"Could not inspect the project: {exc}"],
        )

    errors = []
    for required in ("index.html", "style.css"):
        if required not in relative_files:
            errors.append(f"Required file is missing: {required}")

    if "index.html" in relative_files:
        try:
            html = tools.read_file(f"{project_name}/index.html")
        except (OSError, ValueError) as exc:
            errors.append(f"Could not read index.html: {exc}")
            html = ""

        parser = _ResourceParser()
        try:
            parser.feed(html)
        except Exception as exc:
            errors.append(f"Could not parse index.html: {exc}")

        if not any(
            attribute == "href" and urlsplit(value).path.lower().endswith(".css")
            for attribute, value in parser.resources
        ):
            errors.append("index.html does not reference a CSS stylesheet.")

        for attribute, resource in parser.resources:
            parsed = urlsplit(resource)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resource_path = Path(
                unquote(parsed.path).replace("/", "\\")
            )
            if resource_path.is_absolute() or ".." in resource_path.parts:
                errors.append(f"Unsafe local resource path in index.html: {resource}")
                continue

            html_path = project_root / "index.html"
            resolved_resource = (html_path.parent / resource_path).resolve()
            if (
                resolved_resource != project_root
                and project_root not in resolved_resource.parents
            ):
                errors.append(f"Resource escapes the project directory: {resource}")
            elif not resolved_resource.is_file():
                errors.append(f"Referenced local resource is missing: {resource}")

    return VerificationResult(
        passed=not errors,
        project_path=project_name,
        files=sorted(relative_files),
        errors=errors,
    )
