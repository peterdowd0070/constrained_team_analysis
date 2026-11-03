"""Baseball run engine: projection adapters, Markov rewards, and lineup search."""
from .events import Event, Hitter
from .advancement import AdvancementKernel
from .markov import evaluate_lineup, ExpectedRuns
from .monte_carlo import simulate_games
from .optimize import optimize_lineup

__all__ = ["Event", "Hitter", "AdvancementKernel", "evaluate_lineup", "ExpectedRuns",
           "simulate_games", "optimize_lineup"]
