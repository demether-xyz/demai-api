"""
Strategy Registry - Register all available strategies here
"""
from .task_manager import TaskManager
from .hello_world_strategy import HelloWorldStrategy


def register_all_strategies(task_manager: TaskManager):
    """
    Register all available strategies with the task manager
    """
    # Register Hello World strategy
    hello_world = HelloWorldStrategy()
    task_manager.register_strategy(hello_world)
    
    # TODO: Add more strategies here as they are created
    # Examples:
    # - YieldOptimizationStrategy
    # - RebalancingStrategy
    # - DCAStrategy
    # etc.