#!/usr/bin/env python
import sys
import warnings

from datetime import datetime
from pathlib import Path

import gradio as gr

from test_strategy_protocol_generator.crew import TestStrategyProtocolGenerator

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


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


def run(topic: str = "AI LLMs"):
    """
    Run the crew with a default or supplied topic.
    """
    inputs = {
        'topic': topic,
        'current_year': str(datetime.now().year),
        'document_context': 'No project documents were uploaded. Use topic-based research and standard testing context only.'
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
        return result.raw if hasattr(result, "raw") else str(result)

    with gr.Blocks(title="Test Strategy Protocol Generator") as demo:
        gr.Markdown("# Test Strategy Protocol Generator")
        gr.Markdown("Upload the required project documents and provide the project topic to generate a strategy report.")

        topic = gr.Textbox(
            label="Project / Topic",
            placeholder="Example: AI LLMs testing for healthcare assistant",
            value="AI LLMs"
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
        submit = gr.Button("Generate Test Strategy")
        output = gr.Textbox(
            label="Generated Report",
            lines=25,
            placeholder="The generated strategy will appear here..."
        )

        submit.click(
            fn=generate_strategy,
            inputs=[topic, uploaded_files, all_documents_added],
            outputs=output,
        )

    return demo


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "AI LLMs",
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
        "topic": "AI LLMs",
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
