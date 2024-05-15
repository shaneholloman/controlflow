import functools
import inspect

import prefect
from marvin.beta.assistants import Thread

import controlflow
from controlflow.core.agent import Agent
from controlflow.core.flow import Flow
from controlflow.core.task import Task
from controlflow.utilities.logging import get_logger
from controlflow.utilities.marvin import patch_marvin
from controlflow.utilities.tasks import resolve_tasks
from controlflow.utilities.types import ToolType

logger = get_logger(__name__)


def flow(
    fn=None,
    *,
    thread: Thread = None,
    instructions: str = None,
    tools: list[ToolType] = None,
    agents: list["Agent"] = None,
    resolve_results: bool = None,
):
    """
    A decorator that wraps a function as a ControlFlow flow.

    When the function is called, a new flow is created and any tasks created
    within the function will be run as part of that flow. When the function
    returns, all tasks created in the flow will be run to completion (if they
    were not already completed) and their results will be returned. Any tasks
    that are returned from the function will be replaced with their resolved
    result.

    Args:
        fn (callable, optional): The function to be wrapped as a flow. If not provided,
            the decorator will act as a partial function and return a new flow decorator.
        thread (Thread, optional): The thread to execute the flow on. Defaults to None.
        instructions (str, optional): Instructions for the flow. Defaults to None.
        tools (list[ToolType], optional): List of tools to be used in the flow. Defaults to None.
        agents (list[Agent], optional): List of agents to be used in the flow. Defaults to None.
        resolve_results (bool, optional): Whether to resolve the results of tasks. Defaults to True.

    Returns:
        callable: The wrapped function or a new flow decorator if `fn` is not provided.
    """
    ...

    if fn is None:
        return functools.partial(
            flow,
            thread=thread,
            instructions=instructions,
            tools=tools,
            agents=agents,
            resolve_results=resolve_results,
        )

    if resolve_results is None:
        resolve_results = True
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(
        *args,
        flow_kwargs: dict = None,
        **kwargs,
    ):
        # first process callargs
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        flow_kwargs = flow_kwargs or {}

        if thread is not None:
            flow_kwargs.setdefault("thread", thread)
        if tools is not None:
            flow_kwargs.setdefault("tools", tools)
        if agents is not None:
            flow_kwargs.setdefault("agents", agents)

        p_fn = prefect.flow(fn)

        flow_obj = Flow(**flow_kwargs, context=bound.arguments)

        logger.info(
            f'Executing AI flow "{fn.__name__}" on thread "{flow_obj.thread.id}"'
        )

        with flow_obj, patch_marvin():
            with Task(
                fn.__name__,
                instructions="Complete all subtasks of this task.",
                is_auto_completed_by_subtasks=True,
                context=bound.arguments,
            ) as parent_task:
                with controlflow.instructions(instructions):
                    result = p_fn(*args, **kwargs)

                    # ensure all subtasks are completed
                    parent_task.run()

                    if resolve_results:
                        # resolve any returned tasks; this will raise on failure
                        result = resolve_tasks(result)

            return result

    return wrapper


def task(
    fn=None,
    *,
    objective: str = None,
    instructions: str = None,
    agents: list["Agent"] = None,
    tools: list[ToolType] = None,
    user_access: bool = None,
):
    """
    A decorator that turns a Python function into a Task. The Task objective is
    set to the function name, and the instructions are set to the function
    docstring. When the function is called, the arguments are provided to the
    task as context, and the task is run to completion. If successful, the task
    result is returned; if failed, an error is raised.

    Args:
        fn (callable, optional): The function to be wrapped as a task. If not provided,
            the decorator will act as a partial function and return a new task decorator.
        objective (str, optional): The objective of the task. Defaults to None, in which
            case the function name is used as the objective.
        instructions (str, optional): Instructions for the task. Defaults to None, in which
            case the function docstring is used as the instructions.
        agents (list[Agent], optional): List of agents to be used in the task. Defaults to None.
        tools (list[ToolType], optional): List of tools to be used in the task. Defaults to None.
        user_access (bool, optional): Whether the task requires user access. Defaults to None,
            in which case it is set to False.

    Returns:
        callable: The wrapped function or a new task decorator if `fn` is not provided.
    """

    if fn is None:
        return functools.partial(
            task,
            objective=objective,
            instructions=instructions,
            agents=agents,
            tools=tools,
            user_access=user_access,
        )

    sig = inspect.signature(fn)

    if objective is None:
        objective = fn.__name__

    if instructions is None:
        instructions = fn.__doc__

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # first process callargs
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        task = Task(
            objective=objective,
            instructions=instructions,
            agents=agents,
            context=bound.arguments,
            result_type=fn.__annotations__.get("return"),
            user_access=user_access or False,
            tools=tools or [],
        )

        task.run()
        return task.result

    return wrapper