# AI-Powered Software Test Strategy and Protocol Generator

A walkthrough for explaining the project to an examiner.

## What this project is

This project is a multi-agent application that turns a software project description and uploaded project documents into a first draft of testing documentation. A person enters a topic, uploads requirements or design notes, and downloads a reviewable package of Word and Excel files.

The system assists testers. It does not replace tester judgment, execute the generated tests, or claim that a product is fully tested or compliant.

## Problem it addresses

Requirements are often written in ordinary language. They can be incomplete or ambiguous, and turning them into a test strategy, test cases, an automation recommendation, and a requirements traceability matrix takes time and is easy to do inconsistently.

The application produces a structured first draft from those sources so a human reviewer can check identifiers, coverage, and wording before the documents are used.

## Goal

Given a topic and supporting documents, produce:

- a risk-based test strategy
- traceable test cases
- an automation recommendation
- a requirements traceability matrix
- a formal test protocol and a summary report

Every generated artifact stays subject to human review.

## How to demonstrate it

From the repository root, start the interface:

```bash
./launch_ui.sh
```

That script changes into `test_strategy_protocol_generator` and runs:

```bash
uv run python -m test_strategy_protocol_generator.main
```

Gradio prints a local URL, usually `http://127.0.0.1:7860`. Open it in a browser.

Suggested live demo:

1. Set the topic to `Testing a SaaS inventory management web application`.
2. Leave Documentation Mode on **General Software**.
3. Set Generation Speed to **Fast AI Generation**.
4. Upload every file in `test_strategy_protocol_generator/test_data/` except the files inside `demo_samples`:
   - `product_requirements.md`
   - `architecture_overview.md`
   - `user_stories.txt`
   - `test_plan.yaml`
   - `risk_register.csv`
5. Check **I confirm that all required documents have been uploaded.**
6. Click **Generate Testing Documents**.
7. Download the individual files or the ZIP.

`crewai run` does not open this interface. It runs generation with no uploaded files.

Fast AI Generation and Full Generation need an API key in `test_strategy_protocol_generator/.env`. Demo Mode does not call the model.

## What the examiner sees in the interface

| Control | What to say |
| --- | --- |
| Project / Topic | The product or testing subject the documents are about. |
| Documentation Mode | Chooses the document set and the wording rules. |
| Generation Speed | Chooses whether the run is a saved sample, one structured AI request, or the full agent crew. |
| Upload required documents | Accepts `.pdf`, `.docx`, `.txt`, `.md`, `.csv`, `.json`, `.yaml`, and `.yml`. |
| Confirmation checkbox | Required before generation starts. |
| Individual Documents and ZIP | The finished package, plus a generation status message. |

## Three ways a run can work

**Demo Mode (Instant Sample)** loads a ZIP that was already generated for the selected documentation mode. It does not read the uploaded files and does not call the model. Each sample is labeled as a pre-generated sample. Use this when the network or the API is unavailable and the goal is to show the document format.

**Fast AI Generation** reads the uploaded files, sends one structured request, and asks the model for requirements, risks, strategy points, acceptance criteria, and about 5 to 10 linked test cases. Python then renders the Word and Excel files and builds the ZIP. This is the practical choice for a live exam because it uses the uploaded project and finishes in one model call.

**Full Generation** reads the uploaded files and runs the seven-agent CrewAI crew in sequence. Each task receives the project context, and later tasks can use the outputs of earlier tasks. Document rendering and the ZIP are still done locally after the crew finishes.

## Agents in the full workflow

The crew is defined in `src/test_strategy_protocol_generator/crew.py`. Agent roles live in `config/agents.yaml`, and task instructions live in `config/tasks.yaml`. The crew uses CrewAI's sequential process.

| Order | Agent | Task | What it contributes |
| --- | --- | --- | --- |
| 1 | Test Strategy Lead | Planning | Scope, priorities, and success criteria. |
| 2 | Senior Test Researcher | Research | A short list of relevant practices, techniques, and risks. It must not invent sources. |
| 3 | Requirements and Scope Analyst | Requirements | Testable functional and non-functional requirements with stable IDs such as `REQ-F-001` and `REQ-NF-001`. |
| 4 | Test Strategy Architect | Strategy | Test levels, environment, entry and exit criteria, and acceptance criteria. |
| 5 | Risk and Compliance Manager | Risk | Source-supported risks, affected requirements, impact, and mitigation. It does not invent likelihood or acceptance ratings. |
| 6 | Test Strategy Architect | Protocol | Prerequisites, execution and evidence steps, and pass/fail handling. |
| 7 | Quality Assurance Engineer | Test design | Test cases linked to requirement IDs and, where applicable, risk IDs. |
| 8 | Test Strategy Architect | Automation assessment | Manual checks and automation candidates that the project sources support. |
| 9 | Quality Assurance Engineer | Quality review | Only actionable gaps in traceability, execution, or acceptance. |
| 10 | Reporting Analyst | Reporting | Decisions, unresolved questions, and whether execution is ready. |

The original proposal described five roles: requirements analysis, risk-based strategy, test design, automation planning, and protocol writing. The implementation keeps those responsibilities and adds a lead, a researcher, and a separate quality review before the final report.

## What the downloads contain

**General Software**, the default mode:

- `Software_Test_Plan.docx`
- `Software_Test_Protocol.docx`
- `Requirements_Traceability_Matrix.xlsx`
- `Software_Test_Summary_Report.docx`
- `validation_report.json` inside the ZIP

**Medical Device Software:**

- `Software_Test_Plan.docx`
- `Software_Verification_Protocol.docx`
- `Requirements_Risk_Traceability_Matrix.xlsx`
- `Software_Verification_Summary_Report.docx`
- `validation_report.json` inside the ZIP

Medical Device mode uses IEC 62304, ISO 14971, ISO 13485, and applicable FDA QMSR expectations only as design references. The documents must not claim compliance, certification, or regulatory acceptance. If intended use, safety classification, results, evidence, anomalies, or approvals were not supplied, the documents say they were not provided, not assessed, or pending.

If the upload does not include test execution evidence, the summary marks execution as **Pending / Not Executed**. The generator does not invent actual results.

## Quality checks before export

Before the files are written, the application checks the draft for problems such as:

- duplicate identifiers
- requirements or risks with no traceable test
- duplicated test cases
- inconsistent expected results
- unsupported execution claims
- coverage gaps
- missing document metadata

The status line in the interface reports how many checks need review. The same report is saved as `validation_report.json`. Findings that need a human decision are marked for review. Claims that the tests were executed are removed when the source documents do not support them.

## Technologies

| Technology | Role in this project |
| --- | --- |
| Python and CrewAI | Define the agents and run the sequential full workflow. |
| A configured language-model API | Analyze the documents and draft the structured content. |
| Pydantic | Define the structured Fast AI output: requirements, risks, and test cases. |
| Gradio | Provide the topic field, mode choices, file upload, and downloads. |
| python-docx and openpyxl | Write the Word protocols and the Excel traceability matrix. |
| uv | Install dependencies and run the application in the project environment. |

## What is intentionally out of scope

The first version does not:

- execute the generated tests
- deploy anything into a CI/CD pipeline
- prove complete test coverage
- certify a product or grant regulatory approval

## A short explanation to say out loud

"This application takes a software topic and the project's own documents and drafts a test plan, a test protocol, a traceability matrix, and a summary report. In the full mode, seven specialized CrewAI agents work in order: planning, research, requirements, strategy, risk, protocol, test design, automation, quality review, and reporting. For a live demonstration I use Fast AI Generation, which reads the uploaded inventory-system files and produces a smaller linked test set in one structured request. Either way, the program checks identifiers and traceability before export, and it leaves execution as pending unless real execution evidence was supplied. The result is a draft for a human tester to review, not an automated release decision."
