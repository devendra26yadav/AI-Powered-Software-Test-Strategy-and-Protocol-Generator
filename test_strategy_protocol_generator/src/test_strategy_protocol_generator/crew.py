from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent


@CrewBase
class TestStrategyProtocolGenerator():
    """TestStrategyProtocolGenerator crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def test_lead(self) -> Agent:
        return Agent(
            config=self.agents_config['test_lead'], # type: ignore[index]
            verbose=True
        )

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'], # type: ignore[index]
            verbose=True
        )

    @agent
    def requirements_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['requirements_analyst'], # type: ignore[index]
            verbose=True
        )

    @agent
    def test_strategy_architect(self) -> Agent:
        return Agent(
            config=self.agents_config['test_strategy_architect'], # type: ignore[index]
            verbose=True
        )

    @agent
    def quality_assurance_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['quality_assurance_engineer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def risk_manager(self) -> Agent:
        return Agent(
            config=self.agents_config['risk_manager'], # type: ignore[index]
            verbose=True
        )

    @agent
    def reporting_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['reporting_analyst'], # type: ignore[index]
            verbose=True
        )

    @task
    def planning_task(self) -> Task:
        return Task(
            config=self.tasks_config['planning_task'], # type: ignore[index]
        )

    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'], # type: ignore[index]
        )

    @task
    def requirements_task(self) -> Task:
        return Task(
            config=self.tasks_config['requirements_task'], # type: ignore[index]
        )

    @task
    def strategy_task(self) -> Task:
        return Task(
            config=self.tasks_config['strategy_task'], # type: ignore[index]
        )

    @task
    def risk_task(self) -> Task:
        return Task(
            config=self.tasks_config['risk_task'], # type: ignore[index]
        )

    @task
    def test_protocol_task(self) -> Task:
        return Task(
            config=self.tasks_config['test_protocol_task'], # type: ignore[index]
        )

    @task
    def test_design_task(self) -> Task:
        return Task(
            config=self.tasks_config['test_design_task'], # type: ignore[index]
        )

    @task
    def automation_assessment_task(self) -> Task:
        return Task(
            config=self.tasks_config['automation_assessment_task'], # type: ignore[index]
        )

    @task
    def quality_task(self) -> Task:
        return Task(
            config=self.tasks_config['quality_task'], # type: ignore[index]
        )

    @task
    def reporting_task(self) -> Task:
        return Task(
            config=self.tasks_config['reporting_task'], # type: ignore[index]
        )

    @crew
    def crew(self) -> Crew:
        """Creates the TestStrategyProtocolGenerator crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
