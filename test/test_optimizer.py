'''
Collection of codes for testing the workings of zdream optimizers
'''

import unittest
import numpy as np
from numpy.typing import NDArray
from zdream.utils.types import Codes
from zdream.optimizer import GeneticOptimizer, RandomDistribution

from zdream.utils.types import Message

from typing import cast

def ackley_function(state : Codes) -> Codes:
    x, y = cast(NDArray, state)

    a1 = -20 * np.exp(-0.2 * np.sqrt(0.5 * (x * x + y * y)))
    a2 = -np.exp(0.5 * (np.cos(2 * np.pi * x) + np.cos(2 * np.pi * y)))
    score = -a1 - a2 + 20
    return score

def beale_function(state : Codes) -> Codes:
    '''
    Beale function. Global minimum f(x = 3, y = 0.5) = 0
    In the domain -4.5 < x, y < +4.5
    '''
    x, y = state

    a = (1.500 - x + x * y   )**2
    b = (2.250 - x + x * y**2)**2
    c = (2.625 - x + x * y**3)**2

    return -(a + b + c)

class GeneticOptimizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.states_shape = (2,)
        self.random_seed = 31415
        self.rnd_distr: RandomDistribution = 'normal'

        self.mut_size = 0.3
        self.mut_rate = 0.3
        self.population_size = 10
        self.temperature = 1.

        self.num_iteration = 200

    def non_convex_score(self, state : Codes) -> NDArray:
        # Scorer each subject in the population individually
        scores = [beale_function(subj) for subj in state]

        return np.array(scores)
    
    def test_improvement_2_parents(self):
        optim = GeneticOptimizer(
            states_shape=self.states_shape,
            random_seed=self.random_seed,
            rnd_distr=self.rnd_distr,
            mut_rate=self.mut_rate,
            mut_size=self.mut_size,
            pop_size=self.population_size,
            temp=self.temperature,
            n_parents=2,
        )

        # Initialize optimizer with random condition
        state = optim.init()
        
        # Compute the score of the initial state
        score = self.non_convex_score(state)
        init_score = score.copy()
        
        msg = Message(mask=np.ones(self.population_size, dtype=bool))

        for t in range(self.num_iteration):
            state = optim._step((score, msg))
            score = self.non_convex_score(state)

        # Extract optimizer states, in particular the
        # final score which is tested against the initial
        curr_score = cast(NDArray, optim.stats['curr_score'])

        self.assertGreater(curr_score.max(), init_score.max())

