from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.report import ReportOut

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "jinja"]),
)


def render_report_html(report: ReportOut) -> str:
    template = _env.get_template("report.html.jinja")
    return template.render(report=report)
