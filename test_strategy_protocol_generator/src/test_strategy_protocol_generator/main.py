#!/usr/bin/env python
import sys
import re
import tempfile
import warnings
import zipfile

from datetime import datetime
from pathlib import Path

import gradio as gr

from test_strategy_protocol_generator.crew import TestStrategyProtocolGenerator

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

DOCUMENTS = [
    ("01_project_test_plan.md", "Project Test Plan"),
    ("02_research_findings.md", "Research Findings"),
    ("03_requirements_and_traceability.md", "Requirements and Traceability"),
    ("04_test_strategy.md", "Test Strategy"),
    ("05_test_protocol.md", "Test Protocol"),
    ("06_test_suites_and_cases.md", "Test Suites and Cases"),
    ("07_manual_vs_automated_testing.md", "Manual vs. Automated Testing"),
    ("08_quality_review.md", "Quality Review"),
    ("09_risk_register.md", "Risk Register"),
    ("10_executive_summary.md", "Executive Summary"),
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


def _write_document_package(result, topic: str):
    """Write each crew task result as a separate Markdown file and ZIP bundle."""
    task_outputs = getattr(result, "tasks_output", [])
    safe_topic = re.sub(r"[^a-zA-Z0-9]+", "-", topic).strip("-").lower() or "software-project"
    output_dir = Path(tempfile.mkdtemp(prefix=f"{safe_topic}-test-docs-"))
    generated_files = []

    for index, (filename, title) in enumerate(DOCUMENTS):
        if index < len(task_outputs):
            task_output = task_outputs[index]
            content = getattr(task_output, "raw", None) or str(task_output)
        elif index == len(DOCUMENTS) - 1:
            content = getattr(result, "raw", None) or str(result)
        else:
            content = "No output was returned for this deliverable. Review the crew run and regenerate."

        document_path = output_dir / filename
        document_path.write_text(
            f"# {title}\n\nProject: {topic}\n\n{content.strip()}\n",
            encoding="utf-8",
        )
        generated_files.append(str(document_path))

    readme_path = output_dir / "README.md"
    readme_path.write_text(
        "# Generated Test Documentation\n\n" + "\n".join(
            f"- {filename}: {title}" for filename, title in DOCUMENTS
        ) + "\n",
        encoding="utf-8",
    )
    generated_files.append(str(readme_path))

    archive_path = output_dir.parent / f"{output_dir.name}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in generated_files:
            archive.write(file_path, arcname=Path(file_path).name)

    return generated_files, str(archive_path)


def run(topic: str = "Software Project"):
    """
    Run the crew with a default or supplied topic.
    """
    inputs = {
        'topic': topic,
        'current_year': str(datetime.now().year),
        'document_context': 'No project documents were uploaded. Use the topic and general software testing practices only. State assumptions and do not assume a specific industry.'
    }

    try:
        return TestStrategyProtocolGenerator().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def launch_gradio_app():
    """Launch a simple Gradio UI for entering project details and uploading supporting documents."""

    def generate_strategy(topic, uploaded_files, all_documents_added):
        if not topic or not topic.strip():
            raise gr.Error("Please provide a project or technology topic.")

        if not all_documents_added:
            raise gr.Error("Please confirm that all required documents were uploaded.")

        document_context = _build_document_context(uploaded_files)
        inputs = {
            "topic": topic.strip(),
            "current_year": str(datetime.now().year),
            "document_context": document_context,
        }

        result = TestStrategyProtocolGenerator().crew().kickoff(inputs=inputs)
        document_files, archive_file = _write_document_package(result, topic.strip())
        status = f"Generated {len(DOCUMENTS)} separate testing documents for {topic.strip()}."
        return document_files, archive_file, status

    with gr.Blocks(title="Test Strategy Protocol Generator") as demo:
        gr.Markdown("# Test Strategy Protocol Generator")
        gr.Markdown("Describe any software project, upload its relevant documents, and generate a complete testing documentation package.")

        topic = gr.Textbox(
            label="Project / Topic",
            placeholder="Example: testing a SaaS inventory management web application",
            value="Software Project"
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
            inputs=[topic, uploaded_files, all_documents_added],
            outputs=[documents_output, archive_output, status_output],
        )

    return demo


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "Software Project",
        'current_year': str(datetime.now().year),
        'document_context': 'No project documents were uploaded. Use topic-based research and standard testing context only.'
    }
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
    inputs = {
        "topic": "Software Project",
        "current_year": str(datetime.now().year),
        'document_context': 'No project documents were uploaded. Use topic-based research and standard testing context only.'
    }

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

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "topic": "",
        "current_year": "",
        "document_context": "No project documents were uploaded. Use topic-based research and standard testing context only."
    }

    try:
        result = TestStrategyProtocolGenerator().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")


if __name__ == "__main__":
    launch_gradio_app().launch(debug=True)
