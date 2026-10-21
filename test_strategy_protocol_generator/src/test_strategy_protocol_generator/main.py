#!/usr/bin/env python
import logging
import sys
import json
import re
import shutil
import tempfile
import time
import warnings
import zipfile

from datetime import datetime
from enum import Enum
from pathlib import Path
from docx import Document
from docx.shared import RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

import gradio as gr
from crewai import Crew, Process, Task
from pydantic import BaseModel, Field

from test_strategy_protocol_generator.crew import TestStrategyProtocolGenerator

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")
logger = logging.getLogger(__name__)


class DocumentationMode(str, Enum):
    GENERAL_SOFTWARE = "General Software"
    MEDICAL_DEVICE_SOFTWARE = "Medical Device Software"


class GenerationSpeed(str, Enum):
    DEMO_SAMPLE = "Demo Mode (Instant Sample)"
    FAST_AI = "Fast AI Generation"
    FULL = "Full Generation"


class FastRequirement(BaseModel):
    id: str
    category: str
    description: str


class FastRisk(BaseModel):
    id: str | None = None
    description: str
    control_ids: list[str] = Field(default_factory=list)


class FastTestCase(BaseModel):
    id: str
    requirement_ids: list[str]
    risk_ids: list[str] = Field(default_factory=list)
    risk_control_ids: list[str] = Field(default_factory=list)
    risk_rationale: str = ""
    objective: str
    priority: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str]
    expected_result: str


class FastGenerationOutput(BaseModel):
    requirements: list[FastRequirement]
    risks: list[FastRisk] = Field(default_factory=list)
    scope: list[str]
    strategy: list[str]
    acceptance_criteria: list[str]
    test_cases: list[FastTestCase]
    review_items: list[str] = Field(default_factory=list)


GENERAL_TEST_DESIGN_OUTPUT_INSTRUCTIONS = (
    "For General Software, use requirement IDs assigned by the requirements analysis "
    "exactly. Return separate 'Requirements Traceability Matrix' and 'Detailed Test "
    "Cases' sections; map each requirement to test case IDs, identify uncovered "
    "requirements, and do not repeat matrix rows in the cases."
)

GENERAL_REQUIREMENTS_OUTPUT_INSTRUCTIONS = (
    "Extract functional and nonfunctional requirements from source material into "
    "separate groups. Assign stable IDs REQ-F-001, REQ-F-002, ... for functional and "
    "REQ-NF-001, REQ-NF-002, ... for nonfunctional requirements. Preserve explicit "
    "source IDs alongside these generated IDs when available. Clearly mark inferred "
    "or proposed requirements; do not present them as source requirements."
)

MEDICAL_DEVICE_MODE_INSTRUCTIONS = (
    "The selected documentation mode is Medical Device Software. Treat IEC 62304, "
    "ISO 14971, ISO 13485, and applicable FDA QMSR expectations as design references "
    "only. Never claim compliance, certification, or regulatory acceptance. Do not "
    "assert that a reference applies unless project context establishes applicability. "
    "Use only supplied facts and identify gaps as not provided or requiring confirmation. "
    "Never invent intended use, software safety classification, risk controls, test "
    "results, anomalies, evidence, approvals, reviewers, or signatures. Do not infer a "
    "classification or jurisdiction."
)

MEDICAL_DEVICE_REQUIREMENTS_OUTPUT_INSTRUCTIONS = (
    "Extract functional and nonfunctional requirements from supplied source records. "
    "Assign stable IDs REQ-F-001, REQ-F-002, ... and REQ-NF-001, REQ-NF-002, ...; "
    "preserve source IDs alongside generated IDs. Distinguish requirements from "
    "assumptions and proposed items. Do not invent intended use, safety classification, "
    "risk controls, or regulatory requirements."
)

MEDICAL_DEVICE_TEST_PLAN_INSTRUCTIONS = (
    "For Medical Device Software, ensure the plan addresses intended use and scope; "
    "applicable standards and applicability assumptions; software safety classification "
    "only if supplied (otherwise state 'Not provided; classification not determined'); "
    "risk-based testing strategy; verification approach; measurable acceptance criteria "
    "where supplied or clearly identified as proposed; and review/approval fields left "
    "blank or marked Pending. Keep these as plan-level decisions, not duplicated test cases."
)

MEDICAL_DEVICE_PROTOCOL_INSTRUCTIONS = (
    "For Medical Device Software, return executable verification procedures. Each test "
    "case must include Test Case ID, linked Requirement ID, linked Risk Control ID where "
    "applicable, Preconditions, Test Steps, Expected Results, Actual Results only if "
    "present in supplied execution records, Test Status, and Objective Evidence "
    "Reference. Without supplied execution evidence, set status to 'Not Executed' and "
    "leave actual results/evidence unavailable rather than inventing them."
)

MEDICAL_DEVICE_TRACEABILITY_INSTRUCTIONS = (
    "For Medical Device Software, produce a distinct section titled 'Requirements and "
    "Risk Traceability Matrix' with columns Requirement ID, Risk Reference, Risk "
    "Control, Test Case ID, Verification Status, and Evidence Reference. Preserve IDs "
    "from supplied requirements/risk records. Do not create IDs or assert coverage. "
    "Mark unmapped or unverified items Pending / Not Verified and evidence Not Provided. "
    "Include each supplied requirement and risk control where identifiable."
)

MEDICAL_DEVICE_SUMMARY_INSTRUCTIONS = (
    "For Medical Device Software, summarize verification scope, test execution summary, "
    "requirements coverage, risk-control verification, open anomalies, conclusions, "
    "and review/approval fields. Report actual execution only when supported by supplied "
    "records traceable to test cases and evidence; otherwise state Pending / Not Executed, "
    "coverage Not Assessed, risk-control verification Not Verified, and anomalies not "
    "provided/not assessed as appropriate. Do not invent approvals or release conclusions. "
    "Include optional risk-management, validation, anomaly, and change-control records "
    "only when the project requirements call for them and source information is supplied."
)


GENERAL_SOFTWARE_DOCUMENTS = [
    ("Software_Test_Plan.docx", "Software Test Plan"),
    ("Software_Test_Protocol.docx", "Software Test Protocol"),
    ("Requirements_Traceability_Matrix.xlsx", "Requirements Traceability Matrix"),
    ("Software_Test_Summary_Report.docx", "Software Test Summary Report"),
]

MEDICAL_DEVICE_SOFTWARE_DOCUMENTS = [
    ("Software_Test_Plan.docx", "Software Test Plan"),
    ("Software_Verification_Protocol.docx", "Software Verification Protocol"),
    ("Requirements_Risk_Traceability_Matrix.xlsx", "Requirements and Risk Traceability Matrix"),
    ("Software_Verification_Summary_Report.docx", "Software Verification Summary Report"),
]

TASK_OUTPUT_INDEX = {
    "planning": 0,
    "research": 1,
    "requirements": 2,
    "strategy": 3,
    "risk": 4,
    "protocol": 5,
    "test_design": 6,
    "automation": 7,
    "quality": 8,
    "reporting": 9,
}

DOCUMENT_MODE_PROFILES = {
    DocumentationMode.GENERAL_SOFTWARE: {
        "documents": GENERAL_SOFTWARE_DOCUMENTS,
        "matrix_heading": "Requirements Traceability Matrix",
        "case_headings": ("Detailed Test Cases", "Test Cases"),
        "matrix_columns": (
            "Requirement ID",
            "Test Case ID",
            "Verification Status",
            "Evidence Reference",
        ),
        "medical_device": False,
    },
    DocumentationMode.MEDICAL_DEVICE_SOFTWARE: {
        "documents": MEDICAL_DEVICE_SOFTWARE_DOCUMENTS,
        "matrix_heading": "Requirements and Risk Traceability Matrix",
        "case_headings": ("Verification Test Cases", "Detailed Test Cases", "Test Cases"),
        "matrix_columns": (
            "Requirement ID",
            "Risk Reference",
            "Risk Control",
            "Test Case ID",
            "Verification Status",
            "Evidence Reference",
        ),
        "medical_device": True,
    },
}

DEMO_SAMPLE_ARCHIVES = {
    DocumentationMode.GENERAL_SOFTWARE: "general_software.zip",
    DocumentationMode.MEDICAL_DEVICE_SOFTWARE: "medical_device_software.zip",
}
DEMO_SAMPLE_DIRECTORY = Path(__file__).resolve().parents[2] / "test_data" / "demo_samples"


def _extract_text_from_file(file_path: str) -> str:
    """Read common text-based project files and extract text content."""
    path = Path(file_path)
    if not path.exists():
        return ""

    suffix = path.suffix.lower()

    try:
        if suffix in {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}:
            return path.read_text(encoding="utf-8", errors="ignore")

        if suffix == ".docx":
            from docx import Document

            document = Document(path)
            return "\n".join(paragraph.text for paragraph in document.paragraphs)

        if suffix == ".pdf":
            import fitz

            document = fitz.open(path)
            return "\n".join(page.get_text() for page in document)

        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return f"Unable to read file: {path.name}"


def _build_document_context(uploaded_files):
    """Convert uploaded files into a single context string for the crew."""
    if not uploaded_files:
        return (
            "No project documents were uploaded. Use only the supplied topic and general "
            "context; identify assumptions and do not invent project facts."
        )

    collected_sections = []
    for uploaded_file in uploaded_files:
        if hasattr(uploaded_file, "name"):
            file_name = uploaded_file.name
        else:
            file_name = str(uploaded_file)

        text = _extract_text_from_file(file_name)
        if text.strip():
            collected_sections.append(f"## {Path(file_name).name}\n{text[:15000]}")

    if not collected_sections:
        return "No readable document content was found in the uploaded files."

    return "\n\n".join(collected_sections)


def _task_output_text(task_outputs, index: int) -> str:
    if index >= len(task_outputs):
        return ""
    task_output = task_outputs[index]
    raw_output = getattr(task_output, "raw", None)
    return (str(task_output) if raw_output is None else raw_output).strip()


def _extract_markdown_section(content: str, heading: str) -> str:
    """Return a Markdown section and its child content, excluding peer sections."""
    heading_pattern = re.compile(
        rf"^(?P<level>#+)\s+{re.escape(heading)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = heading_pattern.search(content)
    if not match or len(match.group("level")) > 6:
        return ""

    next_heading = re.search(
        rf"^#{{1,{len(match.group('level'))}}}\s+",
        content[match.end():],
        re.MULTILINE,
    )
    end = match.end() + next_heading.start() if next_heading else len(content)
    return content[match.start():end].strip()


def _remove_markdown_section(content: str, heading: str) -> str:
    """Remove a Markdown section and its child content, preserving other sections."""
    section_pattern = re.compile(
        rf"^#{{1,6}}\s+{re.escape(heading)}\s*$.*?(?=^#{{1,6}}\s+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return section_pattern.sub("", content, count=1).strip()


def _ensure_markdown_sections(content: str, sections: dict[str, str]) -> str:
    missing_sections = []
    for heading, fallback in sections.items():
        if not re.search(
            rf"^#{{1,6}}\s+{re.escape(heading)}\s*$",
            content,
            re.IGNORECASE | re.MULTILINE,
        ):
            missing_sections.append(f"## {heading}\n\n{fallback}")
    return "\n\n".join(part for part in (content, *missing_sections) if part)


def _has_verification_execution_evidence(document_context: str) -> bool:
    test_case_id_present = re.search(
        r"\b(?:TC[-_ ]?[A-Z0-9]+|Test Case ID\s*:\s*\S+)",
        document_context,
        re.IGNORECASE,
    )
    actual_result = re.search(
        r"^\s*(?:[-*]\s*)?Actual Results?\s*:\s*(\S.*)$",
        document_context,
        re.IGNORECASE | re.MULTILINE,
    )
    status = re.search(
        r"^\s*(?:[-*]\s*)?Test Status\s*:\s*(passed|pass|failed|fail|blocked|executed)\s*$",
        document_context,
        re.IGNORECASE | re.MULTILINE,
    )
    evidence_reference = re.search(
        r"^\s*(?:[-*]\s*)?(?:Objective Evidence|Evidence) Reference\s*:\s*(\S.*)$",
        document_context,
        re.IGNORECASE | re.MULTILINE,
    )
    return bool(
        test_case_id_present
        and actual_result
        and status
        and evidence_reference
        and actual_result.group(1).strip().casefold()
        not in {"not provided", "not executed", "pending", "n/a"}
        and evidence_reference.group(1).strip().casefold()
        not in {"not provided", "pending", "n/a"}
    )


def _task_outputs_by_name(task_outputs) -> dict[str, str]:
    return {
        name: _task_output_text(task_outputs, index)
        for name, index in TASK_OUTPUT_INDEX.items()
    }


def _requirement_ids(requirements: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\bREQ-(?:F|NF)-\d{3}\b", requirements)))


def _test_case_ids(test_cases: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\bTC-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", test_cases)))


def _risk_ids(risk_content: str) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(r"\b(?:RISK|RSK|RC)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", risk_content)
        )
    )


_TEST_TYPE_ORDER = (
    "Functional",
    "Negative",
    "Boundary",
    "Failure and recovery",
    "Non-functional",
    "Integration",
    "Regression",
)
_TEST_TYPE_RULES = (
    (
        "Failure and recovery",
        re.compile(
            r"\b(?:fail(?:s|ed|ure)?|recover(?:y|ed)?|restore[ds]?|retry|timeout|duplicate|idempoten\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Boundary",
        re.compile(r"\b(?:boundary|threshold|limit|maximum|minimum|zero|edge)\b", re.IGNORECASE),
    ),
    (
        "Negative",
        re.compile(
            r"\b(?:invalid|reject(?:s|ed)?|unauthorized|denied|forbidden|must not|negative)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Regression",
        re.compile(r"\bregression\b", re.IGNORECASE),
    ),
    (
        "Non-functional",
        re.compile(
            r"\b(?:performance|load|security|encrypt\w*|latency|accessib\w*|browser)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Integration",
        re.compile(r"\b(?:integrat\w*|api|endpoint|event bus|service)\b", re.IGNORECASE),
    ),
)
_AUTOMATION_CASE_PATTERN = re.compile(
    r"\b(?:api|endpoint|automated|automation|nunit|contract test|idempoten\w*)\b",
    re.IGNORECASE,
)


def _classify_test_case(case: dict[str, str], automation_text: str) -> tuple[str, str]:
    """Assign one executing tester role and one test type from the case text."""
    block = case["block"]
    test_type = "Functional"
    if any(requirement_id.startswith("REQ-NF-") for requirement_id in case["requirements"]):
        test_type = "Non-functional"
    else:
        for name, pattern in _TEST_TYPE_RULES:
            if pattern.search(block):
                test_type = name
                break

    cited_for_automation = bool(
        re.search(rf"\b{re.escape(case['id'])}\b", automation_text, re.IGNORECASE)
        and re.search(r"\bautomat", automation_text, re.IGNORECASE)
    )
    role = (
        "Automation Engineer"
        if _AUTOMATION_CASE_PATTERN.search(block) or cited_for_automation
        else "Manual Tester"
    )
    return role, test_type


def _case_classifications(
    protocol: str,
    automation_text: str,
) -> dict[str, tuple[str, str]]:
    classifications = {}
    for case in _case_records(protocol):
        classifications.setdefault(case["id"], _classify_test_case(case, automation_text))
    return classifications


def _insert_case_labels(block: str, role: str, test_type: str) -> str:
    if re.search(r"Responsible Tester Role", block, re.IGNORECASE):
        return block
    labels = (
        f"- **Responsible Tester Role:** {role}\n"
        f"- **Test Type:** {test_type}"
    )
    field = re.search(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?Test Case ID(?:\*\*)?\s*:.*$",
        block,
        re.IGNORECASE | re.MULTILINE,
    )
    if field:
        return block[: field.end()] + "\n" + labels + block[field.end() :]
    heading = re.search(r"^#{2,6}\s+.*$", block, re.MULTILINE)
    if heading:
        return block[: heading.end()] + "\n" + labels + block[heading.end() :]
    return labels + "\n" + block


def _annotate_cases_with_classification(
    protocol: str,
    classifications: dict[str, tuple[str, str]],
) -> str:
    records = _case_records(protocol)
    updated = []
    cursor = 0
    for case in records:
        start = protocol.find(case["block"], cursor)
        if start < 0:
            continue
        role, test_type = classifications.get(case["id"], ("Manual Tester", "Functional"))
        updated.append(protocol[cursor:start])
        updated.append(_insert_case_labels(case["block"], role, test_type))
        cursor = start + len(case["block"])
    updated.append(protocol[cursor:])
    return "".join(updated)


def _format_id_list(case_ids: list[str], classifications: dict[str, tuple[str, str]], by_role: bool) -> str:
    if not case_ids:
        return "- None assigned."
    lines = []
    for case_id in case_ids:
        role, test_type = classifications[case_id]
        detail = test_type if by_role else role
        lines.append(f"- {case_id} — {detail}")
    return "\n".join(lines)


def _build_classification_catalog(
    classifications: dict[str, tuple[str, str]],
    protocol: str,
    automation_text: str,
    risk_text: str,
) -> str:
    """Group the same cases by executing role and by test type."""
    by_role: dict[str, list[str]] = {"Manual Tester": [], "Automation Engineer": []}
    by_type: dict[str, list[str]] = {test_type: [] for test_type in _TEST_TYPE_ORDER}
    risk_cases = []
    blocks = {case["id"]: case["block"] for case in _case_records(protocol)}
    for case_id, (role, test_type) in classifications.items():
        by_role.setdefault(role, []).append(case_id)
        by_type.setdefault(test_type, []).append(case_id)
        if _risk_ids(blocks.get(case_id, "")):
            risk_cases.append(case_id)

    role_section = "\n".join(
        [
            "## Work by Tester Role",
            "",
            "Each test case has one executing role. The test lead confirms these draft assignments before execution. Risk Reviewer checks risk-linked cases and does not replace the executor.",
            "",
            "### Test Lead",
            "Owns scope, priorities, entry and exit criteria, and unresolved decisions in this test plan.",
            "",
            "### Manual Tester",
            _format_id_list(by_role.get("Manual Tester", []), classifications, by_role=True),
            "",
            "### Automation Engineer",
            _format_id_list(by_role.get("Automation Engineer", []), classifications, by_role=True),
            "",
            automation_text.strip() or "No automation assessment was returned.",
            "",
            "### Risk Reviewer",
            _format_id_list(risk_cases, classifications, by_role=True),
            "",
            risk_text.strip() or "No source-supported risk analysis was returned.",
        ]
    )
    type_lines = ["## Work by Test Type", ""]
    for test_type in list(dict.fromkeys([*_TEST_TYPE_ORDER, *by_type])):
        type_lines.extend(
            [
                f"### {test_type}",
                _format_id_list(by_type.get(test_type, []), classifications, by_role=False),
                "",
            ]
        )
    return role_section + "\n\n" + "\n".join(type_lines).strip()


def _build_traceability_matrix(requirements, risks, test_cases, profile) -> str:
    heading = profile["matrix_heading"]
    matrix = _extract_markdown_section(test_cases, heading)
    requirement_ids = _requirement_ids(requirements)
    risk_ids = _risk_ids(risks)
    test_case_ids = _test_case_ids(test_cases)
    columns = profile["matrix_columns"]

    if not matrix:
        rows = []
        if requirement_ids:
            for requirement_id in requirement_ids:
                rows.append(
                    "| "
                    + " | ".join(
                        requirement_id if column == "Requirement ID" else "Not provided"
                        if column in {"Risk Reference", "Risk Control"}
                        else "Not linked"
                        if column == "Test Case ID"
                        else "Pending / Not Verified"
                        if column == "Verification Status"
                        else "Not provided"
                        for column in columns
                    )
                    + " |"
                )
        elif profile["medical_device"]:
            for risk_id in risk_ids:
                rows.append(
                    "| "
                    + " | ".join(
                        risk_id if column == ("Risk Control" if risk_id.startswith("RC-") else "Risk Reference")
                        else "Not provided"
                        if column in {"Requirement ID", "Risk Reference", "Risk Control"}
                        else "Not linked"
                        if column == "Test Case ID"
                        else "Pending / Not Verified"
                        if column == "Verification Status"
                        else "Not provided"
                        for column in columns
                    )
                    + " |"
                )
        if not rows:
            rows.append(
                "| "
                + " | ".join(
                    "Not provided" if column not in {"Verification Status"}
                    else "Pending / Not Verified"
                    for column in columns
                )
                + " |"
            )
        matrix = (
            f"## {heading}\n\n"
            "Requirement IDs come from requirements analysis; verify all mappings before sign-off.\n\n"
            "| " + " | ".join(columns) + " |\n"
            "| " + " | ".join("---" for _ in columns) + " |\n"
            + "\n".join(rows)
        )

    header_line = next(
        (line.casefold() for line in matrix.splitlines() if "|" in line),
        "",
    )
    if not all(column.casefold() in header_line for column in columns):
        matrix += (
            "\n\n### Required traceability fields\n\n"
            "| " + " | ".join(columns) + " |\n"
            "| " + " | ".join("---" for _ in columns) + " |\n"
            "| "
            + " | ".join(
                "Not provided" if column != "Verification Status"
                else "Pending / Not Verified"
                for column in columns
            )
            + " |"
        )

    missing_requirements = [
        identifier for identifier in requirement_ids if identifier not in matrix
    ]
    missing_cases = [
        identifier for identifier in test_case_ids if identifier not in matrix
    ]
    missing_risks = [identifier for identifier in risk_ids if identifier not in matrix]
    validation_heading = "\n\n### Consistency validation\n"
    matrix_body, separator, validation_note = matrix.partition(validation_heading)
    for requirement_id in missing_requirements:
        values = {
            "Requirement ID": requirement_id,
            "Risk Reference": "Not provided",
            "Risk Control": "Not provided",
            "Test Case ID": "Not linked",
            "Verification Status": "Pending / Not Verified",
            "Evidence Reference": "Not provided",
        }
        matrix_body += "\n| " + " | ".join(values.get(column, "Not provided") for column in columns) + " |"
    for test_case_id in missing_cases:
        values = {
            "Requirement ID": "Not linked",
            "Risk Reference": "Not provided",
            "Risk Control": "Not provided",
            "Test Case ID": test_case_id,
            "Verification Status": "Not Executed",
            "Evidence Reference": "Not provided",
        }
        matrix_body += "\n| " + " | ".join(values.get(column, "Not provided") for column in columns) + " |"
    for risk_id in missing_risks:
        values = {
            "Requirement ID": "Not provided",
            "Risk Reference": risk_id if risk_id.startswith(("RISK-", "RSK-")) else "Not provided",
            "Risk Control": risk_id if risk_id.startswith("RC-") else "Not provided",
            "Test Case ID": "Not linked",
            "Verification Status": "Pending / Not Verified",
            "Evidence Reference": "Not provided",
        }
        matrix_body += "\n| " + " | ".join(values.get(column, "Not provided") for column in columns) + " |"
    matrix = matrix_body + (separator + validation_note if separator else "")
    if missing_requirements or missing_cases or missing_risks:
        matrix += (
            ("" if separator else validation_heading)
            + "\n"
            "- Unmapped requirements: "
            + (", ".join(missing_requirements) or "None")
            + "\n- Test cases missing from matrix: "
            + (", ".join(missing_cases) or "None")
            + "\n- Risk identifiers requiring mapping: "
            + (", ".join(missing_risks) or "None")
            + "\n- Status: Review required; do not claim coverage for missing mappings."
        )
    return matrix


def _set_traceability_execution_status(matrix: str, profile, evidence_supplied: bool) -> str:
    if evidence_supplied:
        return matrix

    lines = matrix.splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if "|" in line and "Requirement ID" in line),
        None,
    )
    if header_index is None:
        return matrix

    headers = [cell.strip().casefold() for cell in lines[header_index].strip().strip("|").split("|")]
    status_index = headers.index("verification status") if "verification status" in headers else None
    evidence_index = headers.index("evidence reference") if "evidence reference" in headers else None
    if status_index is None:
        return matrix

    for index in range(header_index + 1, len(lines)):
        if not lines[index].strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
        if len(cells) != len(headers) or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        cells[status_index] = (
            "Pending / Not Verified" if profile["medical_device"] else "Pending"
        )
        if evidence_index is not None:
            cells[evidence_index] = "Not provided"
        lines[index] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines)


def _mark_cases_not_executed(content: str) -> str:
    fields = (
        (
            r"(?im)^(\s*[-*]\s*)?(?:\*\*)?Actual Results?(?:\*\*)?\s*:\s*.*$",
            r"\1**Actual Results:** Not executed; no result supplied",
        ),
        (
            r"(?im)^(\s*[-*]\s*)?(?:\*\*)?Test Status(?:\*\*)?\s*:\s*.*$",
            r"\1**Test Status:** Not Executed",
        ),
        (
            r"(?im)^(\s*[-*]\s*)?(?:\*\*)?Objective Evidence Reference(?:\*\*)?\s*:\s*.*$",
            r"\1**Objective Evidence Reference:** Not provided",
        ),
    )
    for pattern, replacement in fields:
        content = re.sub(pattern, replacement, content)
    return content


def _case_records(content: str) -> list[dict[str, str]]:
    heading_matches = list(
        re.finditer(
            r"^(?P<heading>#{2,6})\s+.*?\b(?P<id>TC-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b.*$",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
    )
    if heading_matches:
        starts = [
            (match.start(), match.end(), match.group("id").upper(), len(match.group("heading")))
            for match in heading_matches
        ]
        heading_pattern = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
    else:
        field_matches = list(
            re.finditer(
                r"^\s*(?:[-*]\s*)?(?:\*\*)?Test Case ID(?:\*\*)?\s*:\s*"
                r"(?P<id>TC-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b.*$",
                content,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        inline_matches = list(
            re.finditer(
                r"^\s*(?P<id>TC-[A-Z0-9]+(?:-[A-Z0-9]+)*)\s*[:.)-].*$",
                content,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        matches = [
            (match.start(), match.end(), match.group("id").upper())
            for match in field_matches
        ]
        for match in inline_matches:
            case_id = match.group("id").upper()
            preceding_fields = [item for item in matches if item[0] < match.start()]
            if preceding_fields and preceding_fields[-1][2] == case_id:
                continue
            matches.append((match.start(), match.end(), case_id))
        matches.sort()
        starts = [(start, end, case_id, 0) for start, end, case_id in matches]
        heading_pattern = re.compile(r"^\s*$")

    records = []
    for index, (start, body_start, case_id, level) in enumerate(starts):
        end = len(content)
        if level:
            next_heading = heading_pattern.search(content, body_start)
            while next_heading:
                if len(next_heading.group(1)) <= level:
                    end = next_heading.start()
                    break
                next_heading = heading_pattern.search(content, next_heading.end())
        elif index + 1 < len(starts):
            end = starts[index + 1][0]

        block = content[start:end]
        requirement_ids = list(dict.fromkeys(_requirement_ids(block)))
        expected_match = re.search(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?Expected Results?(?:\*\*)?\s*:\s*(.*)$",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
        actual_match = re.search(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?Actual Results?(?:\*\*)?\s*:\s*(.*)$",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
        status_match = re.search(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?Test Status(?:\*\*)?\s*:\s*(.*)$",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
        evidence_match = re.search(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:Objective Evidence|Evidence) Reference"
            r"(?:\*\*)?\s*:\s*(.*)$",
            block,
            re.IGNORECASE | re.MULTILINE,
        )
        records.append(
            {
                "id": case_id,
                "block": block,
                "requirements": requirement_ids,
                "expected": expected_match.group(1).strip() if expected_match else "",
                "actual": actual_match.group(1).strip() if actual_match else "",
                "status": status_match.group(1).strip() if status_match else "",
                "evidence": evidence_match.group(1).strip() if evidence_match else "",
            }
        )
    return records


def _remove_protocol_test_cases(protocol: str) -> str:
    case_boundary = re.search(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?Test Case ID(?:\*\*)?\s*:\s*TC-"
        r"|^#{1,6}\s+(?:Verification )?Test Cases?\s*$",
        protocol,
        re.IGNORECASE | re.MULTILINE,
    )
    if not case_boundary:
        return protocol.strip()
    return protocol[:case_boundary.start()].strip()


def _meaningful_value(value: str) -> bool:
    return bool(value.strip()) and value.strip().casefold() not in {
        "not provided",
        "not executed",
        "not executed; no result supplied",
        "pending",
        "n/a",
        "none",
        "omit until supplied in execution records",
    }


def _source_supports_execution_record(document_context: str, case: dict[str, str]) -> bool:
    if not document_context or not re.search(
        rf"\b{re.escape(case['id'])}\b", document_context, re.IGNORECASE
    ):
        return False
    claims = [case["actual"], case["status"], case["evidence"]]
    substantive_claims = [claim for claim in claims if _meaningful_value(claim)]
    if not substantive_claims:
        return True
    normalized_context = re.sub(r"\s+", " ", document_context).casefold()
    return all(
        re.sub(r"\s+", " ", claim).casefold() in normalized_context
        for claim in substantive_claims
    )


def _sanitize_unsubstantiated_execution_claims(
    protocol: str, document_context: str
) -> tuple[str, list[str]]:
    records = _case_records(protocol)
    findings = []
    for case in records:
        claims = [case["actual"], case["status"], case["evidence"]]
        has_execution_claim = any(_meaningful_value(claim) for claim in claims)
        if has_execution_claim and not _source_supports_execution_record(document_context, case):
            findings.append(
                f"{case['id']}: unsupported execution result, status, or evidence claim "
                "was replaced with Not Executed / Not provided."
            )
            protocol = protocol.replace(case["block"], _mark_cases_not_executed(case["block"]), 1)
    return protocol, findings


def _sanitize_summary_execution_claims(
    report: str, document_context: str
) -> tuple[str, list[str]]:
    outcome_pattern = re.compile(
        r"\b(?:tests?|test cases?|verification|execution)\b.{0,100}\b"
        r"(?:passed|failed|were executed|have been executed|completed|successful)\b"
        r"|\b(?:test )?coverage\s*(?:is|:)\s*\d+(?:\.\d+)?\s*%"
        r"|\b(?:no|\d+)\s+(?:open )?(?:defects?|bugs?)\s+(?:were )?"
        r"(?:found|reported|open|closed)\b"
        r"|\b(?:execution|test|verification) status\s*:\s*"
        r"(?:passed|failed|complete|completed|executed)\b",
        re.IGNORECASE,
    )
    source = re.sub(r"\s+", " ", document_context).casefold()
    findings = []
    sentences = re.split(r"(?<=[.!?])\s+", report)
    sanitized = []
    for sentence in sentences:
        if outcome_pattern.search(sentence) and re.sub(
            r"\s+", " ", sentence
        ).strip().casefold() not in source:
            findings.append(
                f"Unsupported execution summary was removed: {sentence.strip()}"
            )
            sanitized.append(
                "Execution claim omitted because supporting source evidence was not supplied."
            )
        else:
            sanitized.append(sentence)
    return " ".join(sanitized), findings


def _matrix_column_values(matrix: str, column_name: str) -> list[str]:
    lines = matrix.splitlines()
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        headers = [cell.strip().casefold() for cell in line.strip().strip("|").split("|")]
        if column_name.casefold() not in headers:
            continue
        column_index = headers.index(column_name.casefold())
        values = []
        for row in lines[index + 1:]:
            if "|" not in row:
                if values:
                    break
                continue
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            if len(cells) != len(headers) or all(
                re.fullmatch(r":?-{3,}:?", cell) for cell in cells
            ):
                continue
            values.append(cells[column_index])
        return values
    return []


def _matrix_case_ids(matrix: str) -> list[str]:
    return list(dict.fromkeys(
        case_id
        for value in _matrix_column_values(matrix, "Test Case ID")
        for case_id in _test_case_ids(value)
    ))


def _case_fingerprint(case: dict[str, str]) -> str:
    value = case["block"]
    value = re.sub(r"^#{1,6}\s+.*$", "", value, flags=re.MULTILINE)
    value = re.sub(r"\b(?:TC|REQ-(?:F|NF))-[A-Z0-9-]+\b", "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:Test Case ID|Linked Requirement ID|"
        r"Requirement ID|Responsible Tester Role|Test Type|Actual Results?|Test Status|"
        r"(?:Objective )?Evidence Reference)"
        r"(?:\*\*)?\s*:.*$",
        "",
        value,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return re.sub(r"\s+", " ", value).strip()


def _validate_document_quality(
    topic: str,
    mode: DocumentationMode | str,
    documents: dict[str, str],
    requirements: str,
    risks: str,
    document_context: str,
    execution_findings: list[str] | None = None,
) -> dict:
    mode = DocumentationMode(mode)
    profile = DOCUMENT_MODE_PROFILES[mode]
    protocol = next(
        (text for name, text in documents.items() if "protocol" in name.casefold()),
        "",
    )
    matrix = next(
        (text for name, text in documents.items() if "traceability" in name.casefold()),
        "",
    )
    cases = _case_records(protocol)
    case_ids = [case["id"] for case in cases]
    duplicate_ids = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    valid_requirements = set(_requirement_ids(requirements))
    referenced_requirements = {
        requirement_id for case in cases for requirement_id in case["requirements"]
    }
    invalid_requirement_refs = sorted(referenced_requirements - valid_requirements)
    unlinked_cases = sorted(
        case["id"] for case in cases if not case["requirements"]
    )
    matrix_case_ids = _matrix_case_ids(matrix)
    unknown_matrix_cases = sorted(set(matrix_case_ids) - set(case_ids))
    unmapped_cases = sorted(set(case_ids) - set(matrix_case_ids))
    matrix_has_case_column = any(
        "test case id" in [cell.strip().casefold() for cell in line.strip().strip("|").split("|")]
        for line in matrix.splitlines()
        if "|" in line
    )
    matrix_requirements = {
        requirement_id
        for value in _matrix_column_values(matrix, "Requirement ID")
        for requirement_id in _requirement_ids(value)
    }
    untested_requirements = sorted(valid_requirements - referenced_requirements)
    requirements_missing_from_matrix = sorted(valid_requirements - matrix_requirements)

    fingerprints: dict[str, list[str]] = {}
    for case in cases:
        fingerprint = _case_fingerprint(case)
        if len(fingerprint) >= 12:
            fingerprints.setdefault(fingerprint, []).append(case["id"])
    duplicate_cases = [
        sorted(ids) for ids in fingerprints.values() if len(ids) > 1
    ]

    expectations: dict[str, set[str]] = {}
    for text in documents.values():
        for case in _case_records(text):
            if case["expected"]:
                normalized = re.sub(r"\s+", " ", case["expected"]).strip().casefold()
                expectations.setdefault(case["id"], set()).add(normalized)
    expectation_conflicts = sorted(
        case_id for case_id, values in expectations.items() if len(values) > 1
    )
    missing_expectations = sorted(
        case["id"] for case in cases if not case["expected"]
    )

    supported_risk_ids = set(_risk_ids(risks)) if profile["medical_device"] else set()
    matrix_risk_ids = {
        risk_id
        for column in ("Risk Reference", "Risk Control")
        for value in _matrix_column_values(matrix, column)
        for risk_id in _risk_ids(value)
    } if profile["medical_device"] else set()
    protocol_risk_ids = set(
        _risk_ids(protocol)
    ) if profile["medical_device"] else set()
    invalid_risk_refs = sorted(
        (protocol_risk_ids | matrix_risk_ids) - supported_risk_ids
    )
    untraced_risk_controls = sorted(
        risk_id for risk_id in supported_risk_ids
        if risk_id.startswith("RC-") and risk_id not in matrix_risk_ids
    )
    unlinked_risk_controls = sorted(
        risk_id for risk_id in supported_risk_ids
        if risk_id.startswith("RC-") and risk_id not in protocol_risk_ids
    )

    expected_titles = {
        filename: title for filename, title in profile["documents"]
    }
    metadata_issues = []
    for filename, title in expected_titles.items():
        text = documents.get(filename, "")
        if not text.startswith(
            f"# {title}\n\nProject: {topic}\n\nDocumentation Mode: {mode.value}\n"
        ):
            metadata_issues.append(filename)

    execution_findings = execution_findings or []
    checks = [
        {
            "id": "unique_test_case_identifiers",
            "status": "FAIL" if duplicate_ids else ("PASS" if case_ids else "REVIEW"),
            "summary": "Test-case identifiers are unique." if case_ids and not duplicate_ids else "Test-case identifiers are duplicated or unavailable.",
            "findings": duplicate_ids or ([] if case_ids else ["No identifiable test cases were found."]),
        },
        {
            "id": "valid_requirement_references",
            "status": "FAIL" if invalid_requirement_refs else ("REVIEW" if unlinked_cases else "PASS"),
            "summary": "Test cases reference extracted requirements." if not invalid_requirement_refs and not unlinked_cases else "Requirement links require review.",
            "findings": [*(f"Unknown requirement: {item}" for item in invalid_requirement_refs), *(f"{item} has no requirement reference." for item in unlinked_cases)],
        },
        {
            "id": "traceability_matrix_test_cases",
            "status": "FAIL" if unknown_matrix_cases else ("REVIEW" if unmapped_cases or not matrix_has_case_column or not case_ids else "PASS"),
            "summary": "Matrix test-case references match protocol cases." if not unknown_matrix_cases and not unmapped_cases and matrix_has_case_column and case_ids else "Matrix-to-protocol test-case coverage requires review.",
            "findings": [*(f"Matrix references unknown case: {item}" for item in unknown_matrix_cases), *(f"Protocol case is missing from matrix: {item}" for item in unmapped_cases), *([] if matrix_has_case_column else ["Traceability matrix has no Test Case ID column."]), *([] if case_ids else ["No protocol test cases are available to map."])],
        },
        {
            "id": "expectation_consistency",
            "status": "FAIL" if expectation_conflicts else ("REVIEW" if missing_expectations else "PASS"),
            "summary": "Repeated test expectations are consistent." if not expectation_conflicts and not missing_expectations else "Test expectations are inconsistent or missing.",
            "findings": [*(f"Conflicting expected results for {item}." for item in expectation_conflicts), *(f"Expected result missing for {item}." for item in missing_expectations)],
        },
        {
            "id": "duplicate_test_cases",
            "status": "FAIL" if duplicate_cases else "PASS",
            "summary": "No duplicate test-case definitions were detected." if not duplicate_cases else "Potential duplicate test cases were detected.",
            "findings": [", ".join(ids) for ids in duplicate_cases],
        },
        {
            "id": "requirements_coverage",
            "status": "REVIEW" if untested_requirements or requirements_missing_from_matrix or not valid_requirements else "PASS",
            "summary": "All extracted requirements are represented in test cases and the matrix." if valid_requirements and not untested_requirements and not requirements_missing_from_matrix else "Requirements are missing or need coverage and matrix review.",
            "findings": [*(f"No test case covers {item}." for item in untested_requirements), *(f"Matrix omits {item}." for item in requirements_missing_from_matrix), *([] if valid_requirements else ["No requirement identifiers were extracted."])],
        },
        {
            "id": "execution_results_supported",
            "status": "REVIEW" if execution_findings else "PASS",
            "summary": "No unsupported execution claims remain." if not execution_findings else "Unsupported execution claims were removed and require user review.",
            "findings": execution_findings,
        },
        {
            "id": "medical_risk_control_traceability",
            "status": (
                "FAIL" if invalid_risk_refs else
                "REVIEW" if profile["medical_device"] and (untraced_risk_controls or unlinked_risk_controls) else
                "PASS"
            ),
            "summary": "Supplied risk-control references are traceable." if not invalid_risk_refs and not untraced_risk_controls and not unlinked_risk_controls else "Risk-control references are unknown or incompletely linked.",
            "findings": [*(f"Protocol references unknown risk item: {item}" for item in invalid_risk_refs), *(f"Risk control missing from matrix: {item}" for item in untraced_risk_controls), *(f"Risk control not linked to a protocol case: {item}" for item in unlinked_risk_controls)],
        },
        {
            "id": "document_metadata_consistency",
            "status": "FAIL" if metadata_issues else "PASS",
            "summary": "Project, mode, and document-title metadata are consistent." if not metadata_issues else "Document metadata is missing or inconsistent.",
            "findings": metadata_issues,
        },
    ]
    status = "REVIEW_REQUIRED" if any(check["status"] != "PASS" for check in checks) else "PASS"
    return {
        "status": status,
        "documentation_mode": mode.value,
        "project": topic,
        "review_required": status != "PASS",
        "checks": checks,
    }


def _markdown_runs(paragraph, text: str) -> None:
    for segment in re.split(r"(\*\*.*?\*\*|`.*?`|\*.*?\*)", text):
        if not segment:
            continue
        if segment.startswith("**") and segment.endswith("**"):
            paragraph.add_run(segment[2:-2]).bold = True
        elif segment.startswith("`") and segment.endswith("`"):
            run = paragraph.add_run(segment[1:-1])
            run.font.name = "Consolas"
        elif segment.startswith("*") and segment.endswith("*"):
            paragraph.add_run(segment[1:-1]).italic = True
        else:
            paragraph.add_run(segment)


def _markdown_table_rows(lines: list[str]) -> list[list[str]]:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in lines
    ]
    return [
        row for row in rows
        if row and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)
    ]


def _write_docx(
    path: Path,
    title: str,
    project: str,
    mode: DocumentationMode,
    content: str,
    sample_label: str | None = None,
) -> None:
    document = Document()
    document.core_properties.title = title
    document.core_properties.subject = f"{mode.value} test documentation"
    document.core_properties.author = "Test Strategy Protocol Generator"
    document.core_properties.keywords = f"{project}, {mode.value}"
    document.add_heading(title, level=0)
    document.add_paragraph(f"Project: {project}")
    document.add_paragraph(f"Documentation Mode: {mode.value}")
    if sample_label:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(sample_label)
        run.bold = True
        run.font.color.rgb = RGBColor(156, 0, 6)

    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            rows = _markdown_table_rows(table_lines)
            if rows:
                table = document.add_table(rows=1, cols=len(rows[0]))
                table.style = "Light Shading Accent 1"
                for cell, value in zip(table.rows[0].cells, rows[0]):
                    cell.text = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
                for values in rows[1:]:
                    cells = table.add_row().cells
                    for cell, value in zip(cells, values):
                        cell.text = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            document.add_heading(
                re.sub(r"\*\*(.*?)\*\*", r"\1", heading.group(2)),
                level=min(len(heading.group(1)), 3),
            )
        elif re.match(r"^[-*]\s+", line):
            paragraph = document.add_paragraph(style="List Bullet")
            _markdown_runs(paragraph, re.sub(r"^[-*]\s+", "", line))
        elif re.match(r"^\d+[.)]\s+", line):
            paragraph = document.add_paragraph(style="List Number")
            _markdown_runs(paragraph, re.sub(r"^\d+[.)]\s+", "", line))
        else:
            paragraph = document.add_paragraph()
            _markdown_runs(paragraph, line)
        index += 1

    document.save(path)


def _write_matrix_xlsx(
    path: Path,
    title: str,
    project: str,
    mode: DocumentationMode,
    content: str,
    sample_label: str | None = None,
) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Traceability Matrix"
    worksheet.append([title])
    worksheet.append([f"Project: {project}"])
    worksheet.append([f"Documentation Mode: {mode.value}"])
    worksheet.append([sample_label] if sample_label else [])
    worksheet.append([])

    table_lines = []
    collecting = False
    for line in content.splitlines():
        if line.strip().startswith("|"):
            collecting = True
            table_lines.append(line)
        elif collecting:
            break
    rows = _markdown_table_rows(table_lines)
    if rows:
        for row in rows:
            worksheet.append(row)
        header_row = 6
        for cell in worksheet[header_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        worksheet.freeze_panes = "A7"
        worksheet.auto_filter.ref = worksheet.dimensions
        for column in worksheet.columns:
            width = min(
                max(max(len(str(cell.value or "")) for cell in column) + 2, 14),
                48,
            )
            worksheet.column_dimensions[column[0].column_letter].width = width
            for cell in column:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    else:
        worksheet.append(["Traceability matrix content"])
        worksheet.append([content or "Not provided; review required."])
        worksheet.column_dimensions["A"].width = 100
        worksheet["A6"].font = Font(bold=True)
        worksheet["A7"].alignment = Alignment(wrap_text=True, vertical="top")
    workbook.properties.title = title
    workbook.properties.subject = f"{mode.value} traceability matrix"
    workbook.properties.creator = "Test Strategy Protocol Generator"
    workbook.properties.keywords = f"{project}, {mode.value}, traceability"
    workbook.save(path)


def _build_document_contents(
    task_outputs, result, mode, document_context="", return_execution_findings=False
):
    """Build the four deliverables through one shared, mode-profiled pipeline."""
    profile = DOCUMENT_MODE_PROFILES[DocumentationMode(mode)]
    outputs = _task_outputs_by_name(task_outputs)
    requirements = outputs["requirements"]
    test_design = outputs["test_design"]

    execution_evidence = (
        profile["medical_device"]
        and _has_verification_execution_evidence(document_context)
    )
    matrix = _build_traceability_matrix(
        requirements, outputs["risk"], test_design, profile
    )
    matrix = _set_traceability_execution_status(matrix, profile, execution_evidence)
    test_cases = next(
        (
            section
            for heading in profile["case_headings"]
            if (section := _extract_markdown_section(test_design, heading))
        ),
        "",
    )
    if not test_cases:
        test_cases = _remove_markdown_section(test_design, profile["matrix_heading"])
    if not test_cases:
        test_cases = (
            "No test cases were returned. Add and review executable test cases before execution.\n\n"
            f"{test_design or 'Test cases not provided.'}"
        )
    # The protocol and matrix both link to stable IDs, but only the protocol owns case detail.
    test_cases = _remove_markdown_section(test_cases, profile["matrix_heading"])

    plan_parts = [outputs["planning"], outputs["requirements"], outputs["strategy"]]
    if profile["medical_device"] and outputs["risk"]:
        plan_parts.append(outputs["risk"])
    plan = "\n\n".join(section for section in plan_parts if section)
    if profile["medical_device"]:
        plan = _ensure_markdown_sections(
            plan or "No test-plan task output was returned.",
            {
                "Intended Use and Scope": "Not provided; confirm from approved project records.",
                "Applicable Standards": (
                    "IEC 62304, ISO 14971, ISO 13485, and applicable FDA QMSR expectations "
                    "are design references only. Confirm applicability; this is not a compliance claim."
                ),
                "Software Safety Classification": "Not provided; classification not determined.",
                "Risk-Based Testing Strategy": "Define from supplied risk-management records.",
                "Verification Approach": "Define and approve before verification execution.",
                "Acceptance Criteria": "Not provided; confirm and approve project-specific criteria.",
                "Review and Approval": (
                    "| Role | Name | Signature | Date | Status |\n"
                    "|---|---|---|---|---|\n"
                    "| Reviewer | Not provided | Pending | Pending | Pending |\n"
                    "| Approver | Not provided | Pending | Pending | Pending |"
                ),
            },
        )

    protocol_parts = [_remove_protocol_test_cases(outputs["protocol"]), test_cases]
    if profile["medical_device"]:
        protocol = "\n\n".join(part for part in protocol_parts if part)
        if not re.search(r"^\s*[-*]\s*\*\*Test Case ID:", protocol, re.MULTILINE):
            protocol += (
                "\n\n### Test Case: Not provided\n\n"
                "- **Test Case ID:** Not provided\n"
                "- **Linked Requirement ID:** Not provided\n"
                "- **Linked Risk Control ID:** Not provided\n"
                "- **Preconditions:** Not provided\n"
                "- **Test Steps:** Not provided\n"
                "- **Expected Results:** Not provided\n"
                "- **Actual Results:** Omit until supplied in execution records\n"
                "- **Test Status:** Not Executed\n"
                "- **Objective Evidence Reference:** Not provided"
            )
    else:
        protocol = "\n\n".join(part for part in protocol_parts if part)

    protocol, execution_findings = _sanitize_unsubstantiated_execution_claims(
        protocol, document_context
    )
    if profile["medical_device"] and not execution_evidence:
        protocol = _mark_cases_not_executed(protocol)

    report = outputs["reporting"] or getattr(result, "raw", None) or str(result)
    report, summary_execution_findings = _sanitize_summary_execution_claims(
        report, document_context
    )
    execution_findings.extend(summary_execution_findings)
    if profile["medical_device"]:
        summary_sections = (
            "## Verification Scope\n\n"
            "See the plan and protocol; confirm intended use, boundaries, and applicable requirements from source records.\n\n"
            "## Test Execution Summary\n\n"
            f"- **Execution status:** {'See supplied, test-case-linked execution evidence.' if execution_evidence else 'Pending / Not Executed; no qualifying execution evidence was supplied.'}\n"
            "- **Actual results:** Include only results explicitly supplied in source records.\n\n"
            "## Requirements Coverage\n\n"
            "Pending / Not Assessed unless supported by the traceability matrix and verification evidence.\n\n"
            "## Risk-Control Verification\n\n"
            "Pending / Not Verified unless supplied records identify the risk control, linked test, result, and objective evidence.\n\n"
            "## Open Anomalies\n\n"
            "Use supplied anomaly records only; otherwise state not provided / not assessed.\n\n"
            "## Conclusions\n\n"
            "Verification conclusions and release decisions require reviewed execution evidence. "
            "Generated test documentation does not establish compliance or approval.\n\n"
            "## Review and Approval\n\n"
            "| Role | Name | Signature | Date | Status |\n"
            "|---|---|---|---|---|\n"
            "| Reviewer | Not provided | Pending | Pending | Pending |\n"
            "| Approver | Not provided | Pending | Pending | Pending |"
        )
        summary = summary_sections
        if execution_evidence:
            summary += (
                "\n\n## Project-Specific Summary\n\n"
                "Synthesize supplied project records only; this summary is not verification "
                "evidence or approval.\n\n"
                f"{report}"
            )
        else:
            summary += "\n\nNo execution-backed project summary is available."
    else:
        summary = (
            "## Test Execution Status\n\n"
            "- **Status:** Pending / Not Executed\n"
            "- **Execution results:** Not available; no actual test execution evidence was provided.\n"
            "- **Defects:** Not assessed; no execution or defect evidence was provided.\n"
            "- **Coverage:** Not measured; no execution coverage evidence was provided.\n"
            "- **Conclusion:** Execution-based conclusions and release readiness are pending test execution.\n\n"
            "## Strategy Summary\n\n"
            f"{report}"
        )

    classifications = _case_classifications(protocol, outputs["automation"])
    protocol = _annotate_cases_with_classification(protocol, classifications)
    catalog = _build_classification_catalog(
        classifications,
        protocol,
        outputs["automation"],
        outputs["risk"],
    )
    plan = f"{plan}\n\n{catalog}".strip()
    summary = (
        f"{summary}\n\n"
        "Tester role and test type assignments are listed in the test plan "
        "and on each protocol test case."
    ).strip()

    documents = [plan, protocol, matrix, summary]
    if return_execution_findings:
        return documents, execution_findings
    return documents


def _report_stage(timings: dict[str, float], stage: str, started_at: float) -> None:
    elapsed = time.perf_counter() - started_at
    timings[stage] = elapsed
    logger.info("generation_stage stage=%s elapsed_seconds=%.3f", stage, elapsed)


def _update_progress(progress, value: float, description: str) -> None:
    if progress is not None:
        progress(value, desc=description)


def _fast_generation_prompt(
    topic: str,
    mode: DocumentationMode,
    document_context: str,
) -> str:
    device_addendum = (
        "For Medical Device Software, use a risk-based verification focus. Preserve only "
        "risk and risk-control identifiers explicitly present in the source. Do not infer "
        "a safety classification, intended use, compliance, or regulatory applicability. "
        "Use IEC 62304, ISO 14971, ISO 13485, and FDA QMSR as design references only. "
        "If risks are described without IDs, describe the source risk theme without creating IDs."
        if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
        else "Do not add medical-device-specific standards, classifications, or documents."
    )
    return (
        "Create one concise, internally consistent set of structured test data for "
        f"{topic!r} in {mode.value} mode.\n"
        "Analyze the supplied project documents once. Extract testable requirements and "
        "assign sequential REQ-F-001 or REQ-NF-001 IDs by requirement category. Do not "
        "omit source requirements that can be tested. Do not add background, repeat facts, "
        "invent project details, or claim execution. Use one short sentence per requirement. "
        "Produce exactly 5 representative test cases with unique IDs such as TC-001. Every "
        "case must link to extracted requirement IDs and have 2-4 brief steps plus one "
        "measurable expected result. Keep scope to 2 bullets, strategy and acceptance "
        "criteria to 3 bullets each, and review_items to actionable gaps only. Set risk "
        "and control IDs only when they exactly occur in source material. If execution "
        "evidence is absent, leave execution as Not Executed / Not provided.\n"
        f"{device_addendum}\n"
        "Return data matching the supplied Pydantic output schema only.\n\n"
        f"Source documents:\n{document_context}"
    )


def _validate_fast_generation_output(
    output: FastGenerationOutput,
    mode: DocumentationMode,
    document_context: str,
) -> None:
    if not output.requirements:
        raise ValueError("Fast AI generation returned no requirements; review the source documents.")
    if not 5 <= len(output.test_cases) <= 10:
        raise ValueError(
            f"Fast AI generation returned {len(output.test_cases)} test cases; expected 5 to 10. "
            "Review the source documents or retry."
        )
    requirement_ids = [requirement.id for requirement in output.requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ValueError("Fast AI generation returned duplicate requirement identifiers.")
    if any(not re.fullmatch(r"REQ-(?:F|NF)-\d{3}", identifier) for identifier in requirement_ids):
        raise ValueError("Fast AI generation returned an invalid requirement identifier.")
    valid_requirements = set(requirement_ids)
    for requirement in output.requirements:
        category = requirement.category.casefold().replace("-", "")
        expected_prefix = "REQ-F-" if category == "functional" else "REQ-NF-"
        if category not in {"functional", "nonfunctional"} or not requirement.id.startswith(expected_prefix):
            raise ValueError(
                f"{requirement.id} does not match its requirement category."
            )
    test_ids = [case.id for case in output.test_cases]
    if len(test_ids) != len(set(test_ids)):
        raise ValueError("Fast AI generation returned duplicate test-case identifiers.")
    if any(not re.fullmatch(r"TC-[A-Z0-9]+(?:-[A-Z0-9]+)*", identifier) for identifier in test_ids):
        raise ValueError("Fast AI generation returned an invalid test-case identifier.")
    for case in output.test_cases:
        if not case.requirement_ids:
            raise ValueError(f"{case.id} does not reference a requirement.")
        invalid_ids = set(case.requirement_ids) - valid_requirements
        if invalid_ids:
            raise ValueError(f"{case.id} references unknown requirements: {', '.join(sorted(invalid_ids))}.")
        if not case.steps or not case.expected_result.strip():
            raise ValueError(f"{case.id} is missing steps or an expected result.")
    if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE:
        source_risks = set(_risk_ids(document_context))
        output_risks = {
            identifier
            for risk in output.risks
            for identifier in ([risk.id] if risk.id else []) + risk.control_ids
        }
        case_risks = {
            identifier
            for case in output.test_cases
            for identifier in (*case.risk_ids, *case.risk_control_ids)
        }
        unknown_risks = (case_risks | output_risks) - source_risks
        if unknown_risks:
            raise ValueError(
                "Fast AI generation returned risk identifiers absent from source material: "
                + ", ".join(sorted(unknown_risks))
            )


def _normalize_fast_generation_identifiers(
    output: FastGenerationOutput,
) -> FastGenerationOutput:
    requirement_ids = [requirement.id for requirement in output.requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ValueError("Fast AI generation returned duplicate requirement identifiers.")
    test_ids = [case.id for case in output.test_cases]
    if len(test_ids) != len(set(test_ids)):
        raise ValueError("Fast AI generation returned duplicate test-case identifiers.")

    requirement_mapping: dict[str, str] = {}
    category_counts = {"functional": 0, "nonfunctional": 0}
    requirements = []
    for requirement in output.requirements:
        source_category = re.sub(r"[^a-z0-9]", "", requirement.category.casefold())
        nonfunctional_terms = (
            "nonfunctional",
            "performance",
            "security",
            "reliability",
            "availability",
            "usability",
            "scalability",
            "maintainability",
            "compatibility",
            "privacy",
            "safety",
        )
        if any(term in source_category for term in nonfunctional_terms):
            category = "nonfunctional"
        elif source_category in {
            "functional",
            "business",
            "businessrule",
            "feature",
            "userstory",
            "usecase",
        }:
            category = "functional"
        else:
            raise ValueError(
                f"Fast AI generation returned unsupported requirement category: "
                f"{requirement.category}."
            )
        category_counts[category] += 1
        prefix = "REQ-F" if category == "functional" else "REQ-NF"
        normalized_id = f"{prefix}-{category_counts[category]:03d}"
        requirement_mapping[requirement.id] = normalized_id
        requirements.append(
            requirement.model_copy(
                update={"id": normalized_id, "category": category}
            )
        )

    test_cases = [
        case.model_copy(
            update={
                "id": f"TC-{index:03d}",
                "requirement_ids": [
                    requirement_mapping.get(identifier, identifier)
                    for identifier in case.requirement_ids
                ],
            }
        )
        for index, case in enumerate(output.test_cases, start=1)
    ]
    return output.model_copy(update={"requirements": requirements, "test_cases": test_cases})


def _fast_output_to_task_outputs(
    output: FastGenerationOutput,
    mode: DocumentationMode,
) -> list:
    profile = DOCUMENT_MODE_PROFILES[mode]
    functional = [item for item in output.requirements if item.category.casefold() == "functional"]
    nonfunctional = [
        item for item in output.requirements if item.category.casefold() in {"nonfunctional", "non-functional"}
    ]
    requirements = ["## Functional Requirements"]
    requirements.extend(f"- {item.id}: {item.description}" for item in functional)
    requirements.append("\n## Nonfunctional Requirements")
    requirements.extend(f"- {item.id}: {item.description}" for item in nonfunctional)
    requirements_text = "\n".join(requirements)

    planning = "## Project Scope\n" + "\n".join(f"- {item}" for item in output.scope)
    if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE:
        planning += (
            "\n\n## Intended Use and Scope\n"
            "Intended use: Not provided; confirm from approved project records."
        )
    strategy = "## Test Strategy\n" + "\n".join(f"- {item}" for item in output.strategy)
    strategy += "\n\n## Acceptance Criteria\n" + "\n".join(
        f"- {item}" for item in output.acceptance_criteria
    )
    if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE:
        strategy += (
            "\n\n## Applicable Standards\n"
            "IEC 62304, ISO 14971, ISO 13485, and applicable FDA QMSR expectations "
            "are design references only; applicability must be confirmed."
            "\n\n## Software Safety Classification\n"
            "Not provided; classification not determined."
            "\n\n## Risk-Based Testing Strategy\n"
            "Prioritize source-supported risk themes; verify traceability and risk controls "
            "before execution. No risk acceptance or compliance conclusion is asserted."
        )

    risk_lines = ["## Source-Supported Risk Information"]
    if output.risks:
        risk_lines.extend(
            f"- {risk.id + ': ' if risk.id else ''}{risk.description}"
            + (f" (controls: {', '.join(risk.control_ids)})" if risk.control_ids else "")
            for risk in output.risks
        )
    else:
        risk_lines.append("No separately identified risk records were supplied.")
    risks_text = "\n".join(risk_lines)

    matrix_rows = []
    for requirement in output.requirements:
        linked_cases = [
            case for case in output.test_cases
            if requirement.id in case.requirement_ids
        ]
        if not linked_cases:
            linked_cases = [None]
        for case in linked_cases:
            values = {
                "Requirement ID": requirement.id,
                "Risk Reference": ", ".join(case.risk_ids) if case and case.risk_ids else "Not provided",
                "Risk Control": ", ".join(case.risk_control_ids) if case and case.risk_control_ids else "Not provided",
                "Test Case ID": case.id if case else "Not linked",
                "Verification Status": "Pending / Not Verified" if profile["medical_device"] else "Pending",
                "Evidence Reference": "Not provided",
            }
            matrix_rows.append("| " + " | ".join(values[column] for column in profile["matrix_columns"]) + " |")
    matrix_text = (
        f"## {profile['matrix_heading']}\n\n"
        "| " + " | ".join(profile["matrix_columns"]) + " |\n"
        "| " + " | ".join("---" for _ in profile["matrix_columns"]) + " |\n"
        + "\n".join(matrix_rows)
    )
    cases_heading = "Verification Test Cases" if profile["medical_device"] else "Detailed Test Cases"
    test_cases = [f"## {cases_heading}"]
    for case in output.test_cases:
        test_cases.extend(
            [
                f"### {case.id}: {case.objective}",
                f"- **Test Case ID:** {case.id}",
                f"- **Linked Requirement ID:** {', '.join(case.requirement_ids)}",
                f"- **Priority:** {case.priority}",
                f"- **Preconditions:** {'; '.join(case.preconditions) or 'Not provided'}",
                f"- **Test Steps:** {'; '.join(case.steps)}",
                f"- **Expected Results:** {case.expected_result}",
            ]
        )
        if profile["medical_device"]:
            test_cases.append(
                "- **Linked Risk Control ID:** "
                + (", ".join(case.risk_control_ids) or "Not provided")
            )
            if case.risk_ids:
                test_cases.append(f"- **Risk Reference:** {', '.join(case.risk_ids)}")
        if case.risk_rationale:
            test_cases.append(f"- **Risk Focus:** {case.risk_rationale}")
        test_cases.extend(
            [
                "- **Actual Results:** Not executed; no execution evidence supplied",
                "- **Test Status:** Not Executed",
                "- **Objective Evidence Reference:** Not provided",
            ]
        )
    design = matrix_text + "\n\n" + "\n".join(test_cases)
    review_text = "\n".join(f"- {item}" for item in output.review_items) or "No additional review items."
    summary = "Fast-generation review items:\n" + review_text
    automation = "Automation assessment: determine candidates during the full generation workflow."

    task_outputs = [None] * len(TASK_OUTPUT_INDEX)
    values = {
        "planning": planning,
        "research": "Source review is limited to uploaded project documents.",
        "requirements": requirements_text,
        "strategy": strategy,
        "risk": risks_text,
        "protocol": "",
        "test_design": design,
        "automation": automation,
        "quality": "Fast mode validates structured data and traceability before export.",
        "reporting": summary,
    }
    for name, index in TASK_OUTPUT_INDEX.items():
        task_outputs[index] = type("FastTaskOutput", (), {"raw": values[name]})()
    return task_outputs


def _run_fast_ai_generation(topic: str, document_context: str, mode: DocumentationMode):
    generator = TestStrategyProtocolGenerator()
    full_crew = generator.crew()
    agent = next(
        candidate for candidate in full_crew.agents
        if "Quality Assurance Engineer" in candidate.role
    )
    output_schema = FastGenerationOutput
    task = Task(
        description=_fast_generation_prompt(topic, mode, document_context),
        expected_output=(
            "A Pydantic-structured set of extracted requirements, source-supported risks, "
            "and 5 to 10 unique requirement-linked test cases with measurable expectations."
        ),
        agent=agent,
        output_pydantic=output_schema,
    )
    fast_crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )
    result = fast_crew.kickoff(inputs={"topic": topic})
    structured = getattr(result.tasks_output[0], "pydantic", None)
    if structured is None:
        raise ValueError("Fast AI generation did not return structured test data.")
    output = FastGenerationOutput.model_validate(structured)
    output = _normalize_fast_generation_identifiers(output)
    _validate_fast_generation_output(output, mode, document_context)
    return output


def _load_demo_sample(mode: DocumentationMode) -> tuple[list[str], str, dict]:
    sample_path = DEMO_SAMPLE_DIRECTORY / DEMO_SAMPLE_ARCHIVES[mode]
    if not sample_path.is_file():
        raise FileNotFoundError(f"Pre-generated demo sample is missing: {sample_path}")
    expected_names = {filename for filename, _ in DOCUMENT_MODE_PROFILES[mode]["documents"]}
    with zipfile.ZipFile(sample_path) as archive:
        names = set(archive.namelist())
        missing = expected_names - names
        if missing:
            raise ValueError(
                f"Demo sample archive is incomplete: {', '.join(sorted(missing))}"
            )
        validation_report = json.loads(archive.read("validation_report.json"))
        output_dir = Path(tempfile.mkdtemp(prefix="test-docs-demo-sample-"))
        files = []
        for filename in expected_names:
            destination = output_dir / filename
            destination.write_bytes(archive.read(filename))
            files.append(str(destination))
        archive_copy = output_dir / sample_path.name
        shutil.copyfile(sample_path, archive_copy)
    return sorted(files), str(archive_copy), validation_report


def _write_document_package(
    result,
    topic: str,
    documentation_mode: DocumentationMode | str = DocumentationMode.GENERAL_SOFTWARE,
    document_context: str = "",
    sample_label: str | None = None,
    timings: dict[str, float] | None = None,
):
    """Write mode-specific Markdown deliverables and a ZIP bundle."""
    timings = timings if timings is not None else {}
    assembly_started = time.perf_counter()
    task_outputs = getattr(result, "tasks_output", [])
    mode = DocumentationMode(documentation_mode)
    profile = DOCUMENT_MODE_PROFILES[mode]
    documents = profile["documents"]
    contents, execution_findings = _build_document_contents(
        task_outputs,
        result,
        mode,
        document_context,
        return_execution_findings=True,
    )

    document_map = {
        filename: (
            f"# {title}\n\nProject: {topic}\n\nDocumentation Mode: {mode.value}\n\n"
            f"{content.strip()}\n"
        )
        for (filename, title), content in zip(documents, contents)
    }
    outputs = _task_outputs_by_name(task_outputs)
    validation_report = _validate_document_quality(
        topic,
        mode,
        document_map,
        outputs["requirements"],
        outputs["risk"],
        document_context,
        execution_findings,
    )
    if sample_label:
        validation_report["pre_generated_sample"] = True
        validation_report["sample_notice"] = sample_label
    _report_stage(timings, "document_assembly_validation", assembly_started)

    safe_topic = re.sub(r"[^a-zA-Z0-9]+", "-", topic).strip("-").lower() or "software-project"
    output_dir = Path(tempfile.mkdtemp(prefix=f"{safe_topic}-test-docs-"))
    generated_files = []
    render_started = time.perf_counter()
    for (filename, title), document_text in zip(documents, document_map.values()):
        document_path = output_dir / filename
        content = contents[len(generated_files)]
        file_started = time.perf_counter()
        if document_path.suffix.casefold() == ".docx":
            _write_docx(document_path, title, topic, mode, content, sample_label)
        elif document_path.suffix.casefold() == ".xlsx":
            _write_matrix_xlsx(
                document_path, title, topic, mode, content, sample_label
            )
        else:
            raise ValueError(f"Unsupported document export format: {document_path.suffix}")
        _report_stage(timings, f"render_{filename}", file_started)
        generated_files.append(str(document_path))
    _report_stage(timings, "document_rendering", render_started)

    archive_path = output_dir.parent / f"{output_dir.name}.zip"
    zip_started = time.perf_counter()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in generated_files:
            archive.write(file_path, arcname=Path(file_path).name)
        archive.writestr(
            "validation_report.json",
            json.dumps(validation_report, indent=2, ensure_ascii=False) + "\n",
        )
    _report_stage(timings, "zip_creation", zip_started)

    return generated_files, str(archive_path), validation_report


def _run_generation_pipeline(
    topic,
    uploaded_files,
    documentation_mode,
    generation_speed: GenerationSpeed | str = GenerationSpeed.FULL,
    progress=None,
):
    mode = DocumentationMode(documentation_mode)
    speed = GenerationSpeed(generation_speed)
    timings: dict[str, float] = {}
    total_started = time.perf_counter()

    if speed is GenerationSpeed.DEMO_SAMPLE:
        _update_progress(progress, 0.1, "Loading pre-generated sample")
        sample_started = time.perf_counter()
        document_files, archive_file, validation_report = _load_demo_sample(mode)
        _report_stage(timings, "sample_loading", sample_started)
        for stage in (
            "input_reading",
            "ai_generation",
            "document_assembly_validation",
            "document_rendering",
            "zip_creation",
        ):
            timings[stage] = 0.0
            logger.info("generation_stage stage=%s elapsed_seconds=0.000 skipped=true", stage)
        _report_stage(timings, "total", total_started)
        _update_progress(progress, 1.0, "Ready for download")
        status = (
            f"PRE-GENERATED DEMO SAMPLE for {mode.value}. "
            "Your uploaded files were not read or processed. "
            f"Sample archive: {Path(archive_file).name}. "
            f"Loaded in {timings['total']:.3f}s."
        )
        return None, document_files, archive_file, status, validation_report, timings

    _update_progress(progress, 0.05, "Analyzing requirements")
    input_started = time.perf_counter()
    document_context = _build_document_context(uploaded_files)
    _report_stage(timings, "input_reading", input_started)
    inputs = _build_crew_inputs(topic.strip(), document_context, mode)

    if speed is GenerationSpeed.FAST_AI:
        if not uploaded_files:
            raise ValueError(
                "Fast AI Generation requires uploaded project requirements or architecture documents."
            )
        _update_progress(progress, 0.2, "Generating test cases")
        ai_started = time.perf_counter()
        structured_output = _run_fast_ai_generation(
            topic.strip(), document_context, mode
        )
        task_outputs = _fast_output_to_task_outputs(structured_output, mode)
        result = type(
            "FastGenerationResult",
            (),
            {
                "tasks_output": task_outputs,
                "raw": "Fast AI generated a structured representative test set.",
            },
        )()
        _report_stage(timings, "ai_generation", ai_started)
    else:
        full_crew = TestStrategyProtocolGenerator().crew()
        ai_started = time.perf_counter()
        completed_tasks = 0

        def update_task_progress(_task_output):
            nonlocal completed_tasks
            completed_tasks += 1
            logger.info(
                "generation_stage stage=full_ai_task_completed "
                "task=%d total_tasks=%d elapsed_seconds=%.3f",
                completed_tasks,
                len(full_crew.tasks),
                time.perf_counter() - ai_started,
            )
            if completed_tasks <= 3:
                _update_progress(
                    progress,
                    min(0.1 + completed_tasks * 0.04, 0.25),
                    "Analyzing requirements",
                )
            elif completed_tasks <= 7:
                _update_progress(
                    progress,
                    min(0.25 + completed_tasks * 0.05, 0.65),
                    "Generating test cases",
                )
            else:
                _update_progress(
                    progress,
                    min(0.65 + completed_tasks * 0.03, 0.95),
                    "Creating documents",
                )

        full_crew.task_callback = update_task_progress
        result = full_crew.kickoff(inputs=inputs)
        _report_stage(timings, "ai_generation", ai_started)

    _update_progress(progress, 0.85, "Creating documents")
    writer_timings: dict[str, float] = {}
    document_files, archive_file, validation_report = _write_document_package(
        result,
        topic.strip(),
        mode,
        document_context,
        timings=writer_timings,
    )
    timings.update(writer_timings)
    _report_stage(timings, "total", total_started)
    review_count = sum(
        check["status"] != "PASS" for check in validation_report["checks"]
    )
    timing_summary = ", ".join(
        f"{name}={timings.get(name, 0.0):.2f}s"
        for name in (
            "input_reading",
            "ai_generation",
            "document_assembly_validation",
            "document_rendering",
            "zip_creation",
            "total",
        )
    )
    status = (
        f"Generated {len(DOCUMENT_MODE_PROFILES[mode]['documents'])} "
        f"separate testing documents for {topic.strip()}. "
        f"Quality validation: {validation_report['status']} "
        f"({review_count} check(s) require review). "
        f"Generation speed: {speed.value}. Timings: {timing_summary}."
    )
    _update_progress(progress, 1.0, "Ready for download")
    return result, document_files, archive_file, status, validation_report, timings


def _build_crew_inputs(
    topic: str,
    document_context: str,
    documentation_mode: DocumentationMode | str = DocumentationMode.GENERAL_SOFTWARE,
):
    mode = DocumentationMode(documentation_mode)
    profile = DOCUMENT_MODE_PROFILES[mode]
    return {
        "topic": topic,
        "current_year": str(datetime.now().year),
        "document_context": document_context,
        "documentation_mode": mode.value,
        "requirements_output_instructions": (
            MEDICAL_DEVICE_REQUIREMENTS_OUTPUT_INSTRUCTIONS
            if profile["medical_device"]
            else GENERAL_REQUIREMENTS_OUTPUT_INSTRUCTIONS
        ),
        "test_design_output_instructions": MEDICAL_DEVICE_TRACEABILITY_INSTRUCTIONS
        if profile["medical_device"]
        else GENERAL_TEST_DESIGN_OUTPUT_INSTRUCTIONS,
        "medical_device_mode_instructions": (
            MEDICAL_DEVICE_MODE_INSTRUCTIONS
            if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
            else ""
        ),
        "medical_device_test_plan_instructions": (
            MEDICAL_DEVICE_TEST_PLAN_INSTRUCTIONS
            if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
            else ""
        ),
        "medical_device_protocol_instructions": (
            MEDICAL_DEVICE_PROTOCOL_INSTRUCTIONS
            if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
            else ""
        ),
        "medical_device_summary_instructions": (
            MEDICAL_DEVICE_SUMMARY_INSTRUCTIONS
            + (
                " Source-record check: test-case-linked execution results and an objective "
                "evidence reference were supplied."
                if _has_verification_execution_evidence(document_context)
                else " Source-record check: no qualifying test-case-linked execution results "
                "and objective evidence reference were identified; report execution as "
                "Pending / Not Executed and do not state actual results."
            )
            if profile["medical_device"]
            else ""
        ),
    }


def run(
    topic: str = "Software Project",
    documentation_mode: DocumentationMode | str = DocumentationMode.GENERAL_SOFTWARE,
    generation_speed: GenerationSpeed | str = GenerationSpeed.FULL,
):
    """
    Run the crew with a default or supplied topic.
    """
    try:
        result, _, _, _, _, _ = _run_generation_pipeline(
            topic, [], documentation_mode, generation_speed
        )
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def launch_gradio_app():
    """Launch a simple Gradio UI for entering project details and uploading supporting documents."""

    def generate_strategy(
        topic,
        uploaded_files,
        all_documents_added,
        documentation_mode,
        generation_speed,
        progress=gr.Progress(track_tqdm=True),
    ):
        if not topic or not topic.strip():
            raise gr.Error("Please provide a project or technology topic.")

        if not all_documents_added:
            raise gr.Error("Please confirm that all required documents were uploaded.")

        _, document_files, archive_file, status, _, _ = _run_generation_pipeline(
            topic,
            uploaded_files,
            documentation_mode,
            generation_speed,
            progress,
        )
        return document_files, archive_file, status

    with gr.Blocks(title="Test Strategy Protocol Generator") as demo:
        gr.Markdown("# Test Strategy Protocol Generator")
        gr.Markdown("Describe any software project, upload its relevant documents, and generate a complete testing documentation package.")

        topic = gr.Textbox(
            label="Project / Topic",
            placeholder="Example: testing a SaaS inventory management web application",
            value="Software Project"
        )
        documentation_mode = gr.Radio(
            choices=[mode.value for mode in DocumentationMode],
            label="Documentation Mode",
            value=DocumentationMode.GENERAL_SOFTWARE.value,
        )
        generation_speed = gr.Radio(
            choices=[speed.value for speed in GenerationSpeed],
            label="Generation Speed",
            value=GenerationSpeed.FAST_AI.value,
        )
        gr.Markdown(
            "**Demo Mode** loads a pre-generated sample without reading uploaded files. "
            "**Fast AI Generation** uses uploaded documents and one structured AI request; "
            "**Full Generation** runs the comprehensive multi-agent workflow."
        )
        uploaded_files = gr.File(
            label="Upload required documents",
            file_count="multiple",
            type="filepath",
            file_types=[".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".yaml", ".yml"]
        )
        all_documents_added = gr.Checkbox(
            label="I confirm that all required documents have been uploaded."
        )
        submit = gr.Button("Generate Testing Documents")
        documents_output = gr.Files(label="Individual Documents")
        archive_output = gr.File(label="Download All Documents (.zip)")
        status_output = gr.Textbox(label="Generation Status", interactive=False)

        submit.click(
            fn=generate_strategy,
            inputs=[
                topic,
                uploaded_files,
                all_documents_added,
                documentation_mode,
                generation_speed,
            ],
            outputs=[documents_output, archive_output, status_output],
        )

    return demo


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = _build_crew_inputs(
        "Software Project",
        "No project documents were uploaded. Use topic-based research and standard testing context only.",
    )
    try:
        TestStrategyProtocolGenerator().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        TestStrategyProtocolGenerator().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = _build_crew_inputs(
        "Software Project",
        "No project documents were uploaded. Use topic-based research and standard testing context only.",
    )

    try:
        TestStrategyProtocolGenerator().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = _build_crew_inputs(
        "",
        "No project documents were uploaded. Use topic-based research and standard testing context only.",
    )
    inputs.update({
        "crewai_trigger_payload": trigger_payload,
    })

    try:
        result = TestStrategyProtocolGenerator().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")


if __name__ == "__main__":
    launch_gradio_app().launch(debug=True)
