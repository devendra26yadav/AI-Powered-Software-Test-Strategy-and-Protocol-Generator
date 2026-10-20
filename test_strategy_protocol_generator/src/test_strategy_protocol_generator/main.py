#!/usr/bin/env python
import sys
import re
import tempfile
import warnings
import zipfile

from datetime import datetime
from enum import Enum
from pathlib import Path

import gradio as gr

from test_strategy_protocol_generator.crew import TestStrategyProtocolGenerator

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


class DocumentationMode(str, Enum):
    GENERAL_SOFTWARE = "General Software"
    MEDICAL_DEVICE_SOFTWARE = "Medical Device Software"


GENERAL_TEST_DESIGN_OUTPUT_INSTRUCTIONS = (
    'For General Software mode, return two distinct Markdown sections: '
    '"Requirements Traceability Matrix" and "Detailed Test Cases". The matrix '
    "must map each available requirement ID to linked test case IDs and identify "
    "uncovered requirements. The detailed cases section must contain executable "
    "test cases and must not repeat the matrix."
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
    ("01_software_test_plan.md", "Software Test Plan"),
    ("02_software_test_protocol.md", "Software Test Protocol"),
    ("03_requirements_traceability_matrix.md", "Requirements Traceability Matrix"),
    ("04_software_test_summary_report.md", "Software Test Summary Report"),
]

MEDICAL_DEVICE_SOFTWARE_DOCUMENTS = [
    ("01_software_test_plan.md", "Software Test Plan"),
    ("02_software_verification_protocol.md", "Software Verification Protocol"),
    ("03_requirements_risk_traceability_matrix.md", "Requirements and Risk Traceability Matrix"),
    ("04_software_verification_summary_report.md", "Software Verification Summary Report"),
]


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
        return "No project documents were uploaded. Use the topic and general context only."

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


def _general_software_documents(task_outputs, result):
    planning = _task_output_text(task_outputs, 0)
    strategy = _task_output_text(task_outputs, 3)
    protocol = _task_output_text(task_outputs, 4)
    test_design = _task_output_text(task_outputs, 5)
    automation = _task_output_text(task_outputs, 6)
    requirements = _task_output_text(task_outputs, 2)
    summary = _task_output_text(task_outputs, 9) or getattr(result, "raw", None) or str(result)

    traceability_matrix = _extract_markdown_section(
        test_design, "Requirements Traceability Matrix"
    )
    if not traceability_matrix:
        traceability_matrix = (
            "## Requirements Traceability Matrix\n\n"
            "The test-design task did not return a separately identifiable matrix. "
            "Requirement-to-test mapping is pending; review the test cases in the "
            "Software Test Protocol and complete this matrix before sign-off.\n\n"
            "### Requirements source\n\n"
            f"{requirements or 'No requirements-task output was returned.'}"
        )

    test_cases = (
        _extract_markdown_section(test_design, "Detailed Test Cases")
        or _extract_markdown_section(test_design, "Test Cases")
    )
    if not test_cases:
        test_cases = _remove_markdown_section(
            test_design, "Requirements Traceability Matrix"
        )
    if not test_cases:
        test_cases = (
            "Detailed test cases were not returned in a separately identifiable section. "
            "Review the test-design task output and add executable cases before test execution.\n\n"
            f"{test_design or 'No test-design task output was returned.'}"
        )

    return [
        "\n\n".join(section for section in (planning, strategy, automation) if section),
        "\n\n".join(section for section in (protocol, test_cases) if section),
        traceability_matrix,
        (
            "## Test Execution Status\n\n"
            "- **Status:** Pending / Not Executed\n"
            "- **Execution results:** Not available; no actual test execution evidence was provided.\n"
            "- **Defects:** Not assessed; no execution or defect evidence was provided.\n"
            "- **Coverage:** Not measured; no execution coverage evidence was provided.\n"
            "- **Conclusion:** Execution-based conclusions and release readiness are pending test execution.\n\n"
            "## Strategy Summary\n\n"
            f"{summary}"
        ),
    ]


def _medical_device_software_documents(
    task_outputs,
    result,
    execution_evidence_supplied: bool = False,
):
    planning = _task_output_text(task_outputs, 0)
    research = _task_output_text(task_outputs, 1)
    strategy = _task_output_text(task_outputs, 3)
    protocol = _task_output_text(task_outputs, 4)
    test_design = _task_output_text(task_outputs, 5)
    summary = _task_output_text(task_outputs, 9) or getattr(result, "raw", None) or str(result)

    traceability_matrix = _extract_markdown_section(
        test_design, "Requirements and Risk Traceability Matrix"
    )
    if not traceability_matrix:
        traceability_matrix = (
            "## Requirements and Risk Traceability Matrix\n\n"
            "No separately identifiable traceability matrix was returned. "
            "Requirement and risk-control mapping is Pending / Not Verified; "
            "verification and evidence references were not provided.\n\n"
            "| Requirement ID | Risk Reference | Risk Control | Test Case ID | "
            "Verification Status | Evidence Reference |\n"
            "|---|---|---|---|---|---|\n"
            "| Not provided | Not provided | Not provided | Not provided | "
            "Pending / Not Verified | Not provided |"
        )
    else:
        matrix_header = next(
            (line.casefold() for line in traceability_matrix.splitlines() if "|" in line),
            "",
        )
        required_columns = (
            "requirement id",
            "risk reference",
            "risk control",
            "test case id",
            "verification status",
            "evidence reference",
        )
        if not all(column in matrix_header for column in required_columns):
            traceability_matrix += (
                "\n\n### Traceability fields requiring completion\n\n"
                "| Requirement ID | Risk Reference | Risk Control | Test Case ID | "
                "Verification Status | Evidence Reference |\n"
                "|---|---|---|---|---|---|\n"
                "| Not provided | Not provided | Not provided | Not provided | "
                "Pending / Not Verified | Not provided |"
            )

    test_cases = (
        _extract_markdown_section(test_design, "Verification Test Cases")
        or _extract_markdown_section(test_design, "Detailed Test Cases")
        or _extract_markdown_section(test_design, "Test Cases")
    )
    if not test_cases:
        test_cases = _remove_markdown_section(
            test_design, "Requirements and Risk Traceability Matrix"
        )
    if not test_cases:
        test_cases = (
            "No separately identifiable verification test cases were returned. "
            "Define and review test cases before execution.\n\n"
            "### Test Case: Not provided\n\n"
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

    plan = "\n\n".join(
        section for section in (planning, research, strategy) if section
    )
    if not plan:
        plan = "No test-plan task output was returned."
    plan = _ensure_markdown_sections(
        plan,
        {
            "Intended Use and Scope": "Not provided; confirm from approved project records.",
            "Applicable Standards": (
                "IEC 62304, ISO 14971, ISO 13485, and applicable FDA QMSR expectations "
                "are design references only. Confirm applicability and current requirements; "
                "this is not a compliance claim."
            ),
            "Software Safety Classification": (
                "Not provided; classification not determined."
            ),
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

    verification_protocol = "\n\n".join(
        section for section in (protocol, test_cases) if section
    )
    if not verification_protocol:
        verification_protocol = "No verification protocol output was returned."

    verification_summary = (
        "## Verification Scope\n\n"
        "See the project-specific scope below. Confirm intended use, system boundaries, "
        "and applicable requirements from source records; do not infer missing details.\n\n"
        "## Test Execution Summary\n\n"
        f"- **Execution status:** {'See supplied, test-case-linked execution evidence.' if execution_evidence_supplied else 'Pending / Not Executed; no qualifying execution evidence was supplied.'}\n"
        "- **Actual results:** Include only results explicitly supplied in source records.\n\n"
        "## Requirements Coverage\n\n"
        "Pending / Not Assessed unless supported by the traceability matrix and verification evidence.\n\n"
        "## Risk-Control Verification\n\n"
        "Pending / Not Verified unless supplied records identify the risk control, linked test, "
        "result, and objective evidence.\n\n"
        "## Open Anomalies\n\n"
        "Use supplied anomaly records only; otherwise state that anomaly records were not provided "
        "and status is not assessed.\n\n"
        "## Conclusions\n\n"
        "Verification conclusions and release decisions require reviewed execution evidence. "
        "Do not infer completion or compliance from generated test documentation.\n\n"
        "## Review and Approval\n\n"
        "| Role | Name | Signature | Date | Status |\n"
        "|---|---|---|---|---|\n"
        "| Reviewer | Not provided | Pending | Pending | Pending |\n"
        "| Approver | Not provided | Pending | Pending | Pending |\n\n"
        "## Project-Specific Summary\n\n"
        "Synthesize only supplied project records. This AI-generated summary is not "
        "verification evidence or approval.\n\n"
        f"{summary}"
    )

    return [
        plan,
        verification_protocol,
        traceability_matrix,
        verification_summary,
    ]


def _write_document_package(
    result,
    topic: str,
    documentation_mode: DocumentationMode | str = DocumentationMode.GENERAL_SOFTWARE,
    document_context: str = "",
):
    """Write mode-specific Markdown deliverables and a ZIP bundle."""
    task_outputs = getattr(result, "tasks_output", [])
    mode = DocumentationMode(documentation_mode)
    if mode is DocumentationMode.GENERAL_SOFTWARE:
        documents = GENERAL_SOFTWARE_DOCUMENTS
        contents = _general_software_documents(task_outputs, result)
    elif mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE:
        documents = MEDICAL_DEVICE_SOFTWARE_DOCUMENTS
        contents = _medical_device_software_documents(
            task_outputs,
            result,
            _has_verification_execution_evidence(document_context),
        )
    else:
        raise ValueError(f"Unsupported documentation mode: {mode}")

    safe_topic = re.sub(r"[^a-zA-Z0-9]+", "-", topic).strip("-").lower() or "software-project"
    output_dir = Path(tempfile.mkdtemp(prefix=f"{safe_topic}-test-docs-"))
    generated_files = []

    for (filename, title), content in zip(documents, contents):
        document_path = output_dir / filename
        document_path.write_text(
            f"# {title}\n\nProject: {topic}\n\n{content.strip()}\n",
            encoding="utf-8",
        )
        generated_files.append(str(document_path))

    readme_path = output_dir / "README.md"
    readme_path.write_text(
        "# Generated Test Documentation\n\n" + "\n".join(
            f"- {filename}: {title}" for filename, title in documents
        ) + "\n",
        encoding="utf-8",
    )

    archive_path = output_dir.parent / f"{output_dir.name}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in [*generated_files, str(readme_path)]:
            archive.write(file_path, arcname=Path(file_path).name)

    return generated_files, str(archive_path)


def _build_crew_inputs(
    topic: str,
    document_context: str,
    documentation_mode: DocumentationMode | str = DocumentationMode.GENERAL_SOFTWARE,
):
    mode = DocumentationMode(documentation_mode)
    execution_evidence_supplied = (
        mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
        and _has_verification_execution_evidence(document_context)
    )
    return {
        "topic": topic,
        "current_year": str(datetime.now().year),
        "document_context": document_context,
        "documentation_mode": mode.value,
        "test_design_output_instructions": (
            GENERAL_TEST_DESIGN_OUTPUT_INSTRUCTIONS
            if mode is DocumentationMode.GENERAL_SOFTWARE
            else MEDICAL_DEVICE_TRACEABILITY_INSTRUCTIONS
            if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
            else ""
        ),
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
                if execution_evidence_supplied
                else " Source-record check: no qualifying test-case-linked execution results "
                "and objective evidence reference were identified; report execution as "
                "Pending / Not Executed and do not state actual results."
            )
            if mode is DocumentationMode.MEDICAL_DEVICE_SOFTWARE
            else ""
        ),
    }


def run(
    topic: str = "Software Project",
    documentation_mode: DocumentationMode | str = DocumentationMode.GENERAL_SOFTWARE,
):
    """
    Run the crew with a default or supplied topic.
    """
    inputs = _build_crew_inputs(
        topic,
        "No project documents were uploaded. Use the topic and general software testing practices only. State assumptions and do not assume a specific industry.",
        documentation_mode,
    )

    try:
        return TestStrategyProtocolGenerator().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def launch_gradio_app():
    """Launch a simple Gradio UI for entering project details and uploading supporting documents."""

    def generate_strategy(topic, uploaded_files, all_documents_added, documentation_mode):
        if not topic or not topic.strip():
            raise gr.Error("Please provide a project or technology topic.")

        if not all_documents_added:
            raise gr.Error("Please confirm that all required documents were uploaded.")

        document_context = _build_document_context(uploaded_files)
        inputs = _build_crew_inputs(topic.strip(), document_context, documentation_mode)

        result = TestStrategyProtocolGenerator().crew().kickoff(inputs=inputs)
        document_files, archive_file = _write_document_package(
            result, topic.strip(), documentation_mode, document_context
        )
        selected_mode = DocumentationMode(documentation_mode)
        document_count = len(
            GENERAL_SOFTWARE_DOCUMENTS
            if selected_mode is DocumentationMode.GENERAL_SOFTWARE
            else MEDICAL_DEVICE_SOFTWARE_DOCUMENTS
        )
        status = f"Generated {document_count} separate testing documents for {topic.strip()}."
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
            inputs=[topic, uploaded_files, all_documents_added, documentation_mode],
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
