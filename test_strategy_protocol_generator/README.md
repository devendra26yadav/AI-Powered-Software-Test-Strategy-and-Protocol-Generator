# TestStrategyProtocolGenerator Crew

Welcome to the TestStrategyProtocolGenerator Crew project, powered by [crewAI](https://crewai.com). This template is designed to help you set up a multi-agent AI system with ease, leveraging the powerful and flexible framework provided by crewAI. Our goal is to enable your agents to collaborate effectively on complex tasks, maximizing their collective intelligence and capabilities.

## Installation

Ensure you have Python >=3.10 <3.14 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management and package handling, offering a seamless setup and execution experience.

First, if you haven't already, install uv:

```bash
pip install uv
```

Next, navigate to your project directory and install the dependencies:

(Optional) Lock the dependencies and install them by using the CLI command:
```bash
crewai install
```
### Customizing

**Add your `OPENAI_API_KEY` into the `.env` file**

- Modify `src/test_strategy_protocol_generator/config/agents.yaml` to define your agents
- Modify `src/test_strategy_protocol_generator/config/tasks.yaml` to define your tasks
- Modify `src/test_strategy_protocol_generator/crew.py` to add your own logic, tools and specific args
- Modify `src/test_strategy_protocol_generator/main.py` to add custom inputs for your agents and tasks

## Running the Project

To kickstart your crew of AI agents and begin task execution, run this from the root folder of your project:

```bash
$ crewai run
```

This command initializes the test_strategy_protocol_generator Crew, assembling the agents and assigning them tasks as defined in your configuration.

This example, unmodified, will run the create a `report.md` file with the output of a research on LLMs in the root folder.

## Documentation modes

The Gradio application offers two documentation modes. **General Software** is the default and generates four core Markdown documents in the downloadable ZIP:

- Software Test Plan
- Software Test Protocol
- Requirements Traceability Matrix
- Software Test Summary Report

When no test execution evidence is supplied, the summary report marks execution as **Pending / Not Executed** and notes that defects, coverage, and execution conclusions are unavailable.

**Medical Device Software** generates a Software Test Plan, Software Verification Protocol, Requirements and Risk Traceability Matrix, and Software Verification Summary Report. IEC 62304, ISO 14971, ISO 13485, and applicable FDA QMSR expectations are used as design references only; generated documentation does not assert compliance. Missing classifications, execution results, evidence, anomalies, and approvals are identified as not provided, pending, or not assessed rather than inferred. Optional risk-management, validation, anomaly, and change-control records are included when the project requirements call for them and source records are supplied.

## Understanding Your Crew

The test_strategy_protocol_generator Crew is composed of multiple AI agents, each with unique roles, goals, and tools. These agents collaborate on a series of tasks, defined in `config/tasks.yaml`, leveraging their collective skills to achieve complex objectives. The `config/agents.yaml` file outlines the capabilities and configurations of each agent in your crew.

## Support

For support, questions, or feedback regarding the TestStrategyProtocolGenerator Crew or crewAI.
- Visit our [documentation](https://docs.crewai.com)
- Reach out to us through our [GitHub repository](https://github.com/joaomdmoura/crewai)
- [Join our Discord](https://discord.com/invite/X4JWnZnxPb)
- [Chat with our docs](https://chatg.pt/DWjSBZn)

Let's create wonders together with the power and simplicity of crewAI.
