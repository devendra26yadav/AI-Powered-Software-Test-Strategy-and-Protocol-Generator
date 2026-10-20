import unittest
import zipfile
from pathlib import Path

from test_strategy_protocol_generator.main import (
    DocumentationMode,
    GENERAL_TEST_DESIGN_OUTPUT_INSTRUCTIONS,
    GENERAL_SOFTWARE_DOCUMENTS,
    MEDICAL_DEVICE_MODE_INSTRUCTIONS,
    MEDICAL_DEVICE_PROTOCOL_INSTRUCTIONS,
    MEDICAL_DEVICE_SOFTWARE_DOCUMENTS,
    MEDICAL_DEVICE_SUMMARY_INSTRUCTIONS,
    MEDICAL_DEVICE_TEST_PLAN_INSTRUCTIONS,
    MEDICAL_DEVICE_TRACEABILITY_INSTRUCTIONS,
    _build_crew_inputs,
    _extract_markdown_section,
    _has_verification_execution_evidence,
    _remove_markdown_section,
    _write_document_package,
)


class TaskOutput:
    def __init__(self, raw):
        self.raw = raw


class BuildCrewInputsTests(unittest.TestCase):
    def test_defaults_to_general_software_mode(self):
        inputs = _build_crew_inputs("Example project", "Project context")

        self.assertEqual(inputs["documentation_mode"], DocumentationMode.GENERAL_SOFTWARE.value)
        self.assertEqual(inputs["topic"], "Example project")
        self.assertEqual(inputs["document_context"], "Project context")
        self.assertIn(
            "Requirements Traceability Matrix",
            inputs["test_design_output_instructions"],
        )

    def test_preserves_selected_medical_device_mode(self):
        inputs = _build_crew_inputs(
            "Example device",
            "Device context",
            DocumentationMode.MEDICAL_DEVICE_SOFTWARE.value,
        )

        self.assertEqual(
            inputs["documentation_mode"],
            DocumentationMode.MEDICAL_DEVICE_SOFTWARE.value,
        )
        self.assertEqual(
            inputs["test_design_output_instructions"],
            MEDICAL_DEVICE_TRACEABILITY_INSTRUCTIONS,
        )
        self.assertEqual(
            inputs["medical_device_mode_instructions"],
            MEDICAL_DEVICE_MODE_INSTRUCTIONS,
        )
        self.assertEqual(
            inputs["medical_device_test_plan_instructions"],
            MEDICAL_DEVICE_TEST_PLAN_INSTRUCTIONS,
        )
        self.assertEqual(
            inputs["medical_device_protocol_instructions"],
            MEDICAL_DEVICE_PROTOCOL_INSTRUCTIONS,
        )
        self.assertTrue(
            inputs["medical_device_summary_instructions"].startswith(
                MEDICAL_DEVICE_SUMMARY_INSTRUCTIONS
            )
        )
        self.assertIn(
            "Pending / Not Executed",
            inputs["medical_device_summary_instructions"],
        )
        self.assertIn("IEC 62304", inputs["medical_device_mode_instructions"])
        self.assertIn("ISO 14971", inputs["medical_device_mode_instructions"])
        self.assertIn("ISO 13485", inputs["medical_device_mode_instructions"])
        self.assertIn("FDA QMSR", inputs["medical_device_mode_instructions"])
        self.assertIn("Risk Control", inputs["test_design_output_instructions"])

    def test_extract_markdown_section_stops_at_next_peer_heading(self):
        content = (
            "## Requirements Traceability Matrix\nMatrix content\n"
            "## Detailed Test Cases\nCase content"
        )

        section = _extract_markdown_section(content, "Requirements Traceability Matrix")

        self.assertEqual(section, "## Requirements Traceability Matrix\nMatrix content")

    def test_remove_markdown_section_preserves_other_sections(self):
        content = (
            "## Requirements Traceability Matrix\nMatrix content\n"
            "## Test Cases\nCase content"
        )

        remaining = _remove_markdown_section(content, "Requirements Traceability Matrix")

        self.assertEqual(remaining, "## Test Cases\nCase content")

    def test_execution_evidence_requires_case_result_status_and_reference(self):
        context = (
            "Test Case ID: TC-1\n"
            "Actual Results: Inventory count updated\n"
            "Test Status: Passed\n"
            "Objective Evidence Reference: run-123/screenshot.png"
        )

        self.assertTrue(_has_verification_execution_evidence(context))
        self.assertFalse(
            _has_verification_execution_evidence(
                context.replace("Objective Evidence Reference: run-123/screenshot.png", "")
            )
        )


class DocumentPackageTests(unittest.TestCase):
    def setUp(self):
        self.task_outputs = [
            TaskOutput("Project scope and acceptance criteria"),
            TaskOutput("Research findings"),
            TaskOutput("Prioritized requirement list"),
            TaskOutput("Test strategy and environment"),
            TaskOutput("Test execution procedures"),
            TaskOutput(
                "## Requirements Traceability Matrix\n"
                "| Requirement | Test case | Coverage |\n"
                "| REQ-1 | TC-1 | Covered |\n\n"
                "## Detailed Test Cases\n"
                "TC-1: Verify inventory item creation."
            ),
            TaskOutput("Manual and automated testing approach"),
            TaskOutput("Quality review"),
            TaskOutput("Risk register"),
            TaskOutput("Executive conclusions"),
        ]

    def _write_package(
        self,
        mode=DocumentationMode.GENERAL_SOFTWARE,
        task_outputs=None,
        document_context="",
    ):
        return _write_document_package(
            type(
                "CrewResult",
                (),
                {
                    "tasks_output": task_outputs or self.task_outputs,
                    "raw": "Crew result",
                },
            )(),
            "Example project",
            mode,
            document_context,
        )

    def test_general_mode_generates_exactly_four_core_documents(self):
        files, archive_path = self._write_package()
        try:
            generated_names = {Path(file_path).name for file_path in files}
            expected_names = {filename for filename, _ in GENERAL_SOFTWARE_DOCUMENTS}

            self.assertEqual(len(files), 4)
            self.assertEqual(generated_names, expected_names)
            with zipfile.ZipFile(archive_path) as archive:
                archive_names = set(archive.namelist())
                self.assertEqual(archive.testzip(), None)
                self.assertEqual(archive_names, expected_names | {"README.md"})
                plan = archive.read("01_software_test_plan.md").decode("utf-8")
                protocol = archive.read("02_software_test_protocol.md").decode("utf-8")
                matrix = archive.read("03_requirements_traceability_matrix.md").decode("utf-8")
                summary = archive.read("04_software_test_summary_report.md").decode("utf-8")

            self.assertIn("Project scope and acceptance criteria", plan)
            self.assertIn("Test strategy and environment", plan)
            self.assertIn("Manual and automated testing approach", plan)
            self.assertIn("Test execution procedures", protocol)
            self.assertIn("TC-1: Verify inventory item creation.", protocol)
            self.assertNotIn("| REQ-1 | TC-1 | Covered |", protocol)
            self.assertIn("| REQ-1 | TC-1 | Covered |", matrix)
            self.assertNotIn("TC-1: Verify inventory item creation.", matrix)
            self.assertIn("Pending / Not Executed", summary)
            self.assertIn("no actual test execution evidence", summary)
            self.assertIn("Defects:", summary)
            self.assertIn("Not measured", summary)
            self.assertIn("Conclusion:", summary)
        finally:
            self._remove_package(files, archive_path)

    def test_medical_device_mode_generates_four_verification_documents(self):
        medical_outputs = list(self.task_outputs)
        medical_outputs[5] = TaskOutput(
            "## Requirements and Risk Traceability Matrix\n"
            "| Requirement ID | Risk Reference | Risk Control | Test Case ID | "
            "Verification Status | Evidence Reference |\n"
            "| REQ-1 | RISK-1 | RC-1 | TC-1 | Pending / Not Verified | Not Provided |\n\n"
            "## Verification Test Cases\n"
            "### TC-1\n"
            "- **Linked Requirement ID:** REQ-1\n"
            "- **Linked Risk Control ID:** RC-1\n"
            "- **Preconditions:** Approved test environment available\n"
            "- **Test Steps:** Execute the documented verification steps\n"
            "- **Expected Results:** System meets REQ-1\n"
            "- **Actual Results:** Not provided\n"
            "- **Test Status:** Not Executed\n"
            "- **Objective Evidence Reference:** Not provided"
        )
        files, archive_path = self._write_package(
            DocumentationMode.MEDICAL_DEVICE_SOFTWARE,
            task_outputs=medical_outputs,
        )
        try:
            generated_names = {Path(file_path).name for file_path in files}
            expected_names = {
                filename for filename, _ in MEDICAL_DEVICE_SOFTWARE_DOCUMENTS
            }

            self.assertEqual(len(files), 4)
            self.assertEqual(generated_names, expected_names)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    expected_names | {"README.md"},
                )
                plan = archive.read("01_software_test_plan.md").decode("utf-8")
                protocol = archive.read(
                    "02_software_verification_protocol.md"
                ).decode("utf-8")
                matrix = archive.read(
                    "03_requirements_risk_traceability_matrix.md"
                ).decode("utf-8")
                summary = archive.read(
                    "04_software_verification_summary_report.md"
                ).decode("utf-8")

            self.assertIn("Project scope and acceptance criteria", plan)
            for section in (
                "Intended Use and Scope",
                "Applicable Standards",
                "Software Safety Classification",
                "Risk-Based Testing Strategy",
                "Verification Approach",
                "Acceptance Criteria",
                "Review and Approval",
            ):
                self.assertIn(section, plan)
            self.assertIn("classification not determined", plan)
            self.assertIn("TC-1", protocol)
            for field in (
                "Linked Requirement ID",
                "Linked Risk Control ID",
                "Preconditions",
                "Test Steps",
                "Expected Results",
                "Actual Results",
                "Test Status",
                "Objective Evidence Reference",
            ):
                self.assertIn(field, protocol)
            self.assertIn(
                "| REQ-1 | RISK-1 | RC-1 | TC-1 | Pending / Not Verified | Not Provided |",
                matrix,
            )
            self.assertNotIn("TC-1", summary.split("## Open Anomalies", 1)[0])
            self.assertIn("Pending / Not Executed", summary)
            self.assertIn("Risk-Control Verification", summary)
            self.assertIn("Review and Approval", summary)
            self.assertIn("Not provided | Pending", summary)
            self.assertIn("Executive conclusions", summary)
        finally:
            self._remove_package(files, archive_path)

    def test_medical_device_mode_marks_missing_content_as_pending(self):
        empty_outputs = [TaskOutput("") for _ in range(10)]
        files, archive_path = self._write_package(
            DocumentationMode.MEDICAL_DEVICE_SOFTWARE,
            task_outputs=empty_outputs,
        )
        try:
            with zipfile.ZipFile(archive_path) as archive:
                plan = archive.read("01_software_test_plan.md").decode("utf-8")
                protocol = archive.read(
                    "02_software_verification_protocol.md"
                ).decode("utf-8")
                matrix = archive.read(
                    "03_requirements_risk_traceability_matrix.md"
                ).decode("utf-8")
                summary = archive.read(
                    "04_software_verification_summary_report.md"
                ).decode("utf-8")

            self.assertIn("Not provided; classification not determined.", plan)
            self.assertIn("Test Case ID:** Not provided", protocol)
            self.assertIn("Test Status:** Not Executed", protocol)
            self.assertIn("Actual Results:** Omit until supplied", protocol)
            self.assertIn("Pending / Not Verified", matrix)
            self.assertIn("Pending / Not Executed", summary)
            self.assertNotIn("PASS", summary)
            self.assertNotIn("Approved by", summary)
        finally:
            self._remove_package(files, archive_path)

    def test_medical_summary_uses_supplied_execution_evidence(self):
        execution_context = (
            "Test Case ID: TC-1\n"
            "Actual Results: Inventory count updated\n"
            "Test Status: Passed\n"
            "Objective Evidence Reference: run-123/screenshot.png"
        )
        files, archive_path = self._write_package(
            DocumentationMode.MEDICAL_DEVICE_SOFTWARE,
            document_context=execution_context,
        )
        try:
            with zipfile.ZipFile(archive_path) as archive:
                summary = archive.read(
                    "04_software_verification_summary_report.md"
                ).decode("utf-8")

            self.assertIn("See supplied, test-case-linked execution evidence.", summary)
            self.assertIn("Project-Specific Summary", summary)
            self.assertIn("Executive conclusions", summary)
        finally:
            self._remove_package(files, archive_path)

    @staticmethod
    def _remove_package(files, archive_path):
        for file_path in files:
            Path(file_path).unlink(missing_ok=True)
        (Path(files[0]).parent / "README.md").unlink(missing_ok=True)
        Path(files[0]).parent.rmdir()
        Path(archive_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
