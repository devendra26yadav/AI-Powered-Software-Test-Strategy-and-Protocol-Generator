import unittest

from test_strategy_protocol_generator.main import DocumentationMode, _build_crew_inputs


class BuildCrewInputsTests(unittest.TestCase):
    def test_defaults_to_general_software_mode(self):
        inputs = _build_crew_inputs("Example project", "Project context")

        self.assertEqual(inputs["documentation_mode"], DocumentationMode.GENERAL_SOFTWARE.value)
        self.assertEqual(inputs["topic"], "Example project")
        self.assertEqual(inputs["document_context"], "Project context")

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


if __name__ == "__main__":
    unittest.main()
