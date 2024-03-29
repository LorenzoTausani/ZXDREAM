from abc import ABC, abstractmethod
from typing import Callable, Dict, Literal, Tuple, List

import numpy as np
from numpy.typing import NDArray
from scipy.special import softmax

from .utils.model import Codes, Score
from .utils.misc import default, lazydefault
from .message import Message

RandomDistribution = Literal['normal', 'gumbel', 'laplace', 'logistic']
''' Name of distributions for random initial codes '''

class Optimizer(ABC):
    '''
    Base class for generic optimizer, which keeps track of current
    codes and defines the abstract `step()` method which every 
    concrete subclass must implement.
    '''
    
    def __init__(
        self,
        states_space : None | Dict[int | str, Tuple[float | None, float | None]] = None,
        states_shape : None | int | Tuple[int, ...] = None,
        random_seed : None | int = None,
        random_distr : RandomDistribution = 'normal',
    ) -> None:
        '''
        Create a  gradient-free optimizer.

        :param states_space: Dictionary specifying the optimization domain where 
                             each entry is a direction and corresponding values
                             are the min-max acceptable values along that dir, defaults to None.
        :type states_space: None | Dict[int  |  str, Tuple[float  |  None, float  |  None]], optional
        :param states_shape: Dictionary specifying the optimization domain where 
                             each entry is a direction and corresponding values are 
                             the min-max acceptable values along that direction, defaults to None.
        :type states_shape: None | int | Tuple[int, ...], optional
        :param random_seed: Random state for pseudo-random numbers generation.
        :type random_seed: None | int, optional
        :param random_distr: Nature of the random distribution for initial
                             random codes generation, defaults to `normal`.
        :type random_distr: RandomDistribution
        '''
        
        # At parameters `states_shape` and `states_space`
        if not (states_shape or states_space):
            err_msg = 'Either `states_shape` or `states_space` must be specified, but both weren\'t.'
            raise ValueError(err_msg)
                
        # States shape - int to tuple conversion
        if isinstance(states_shape, int):
            states_shape = (states_shape,)
        
        # Defaults states and shape
        # TODO Why not just default if the lambda returns simply the value ?
        # TODO If they are None, the second expression access them as None ? 
        # TODO @Paolo
        self._space = lazydefault(states_space, lambda : {i : (None, None) for i in range(len(states_shape))})  # type: ignore
        self._shape = lazydefault(states_shape, lambda : (len(states_space),))                                  # type: ignore
        
        # Random distribution
        # NOTE: We also initialize the internal random number generator 
        #       for reproducibility, if not given it isn't set.
        self._distr = random_distr
        self._rng   = np.random.default_rng(random_seed)
        
        self._prev_codes : None | Codes = None
        
    @property
    def n_states(self) -> int: return 1
    ''' 
    Number of codes the optimizer is optimizing for.
    By defaults it optimizes only one code at a time.
    '''
    
    @abstractmethod
    def step(self, data: Tuple[Score, Message]) -> Tuple[Codes, Message]:
        '''
        Abstract step method. The `step()` method collects the set of
        old states from which it obtains the set of new scores via the
        objective function and updates the internal parameters to produce
        a new set of states that would hopefully increase future scores.

        :param data: Tuple containing a score associated to each old code and
                     a message containing a masking information about some natural
                     images to be filtered out.
        :type data: Tuple[Score, Message]
        :return: Set of new codes to be used to improve future states scores
        :rtype: Codes
        '''        
        pass
    
    @property
    def codes(self) -> Codes:
        '''
        Returns codes after the last step.
        '''
        if self._prev_codes is None:
            err_msg = 'Codes are not available yet'
            raise ValueError(err_msg)
        return self._prev_codes
        
    # --- CODE INITIALIZATION ---
    
    def init(self, init_codes : NDArray | None = None, **kwargs) -> Codes:
        '''
        Initialize the optimizer codes. If initial codes are provided 
        as arrays they should have matching dimensionality as 
        expected by the provided states shape, otherwise they are randomly sampled.
        
        :param init_codes: Initial codes for optimizations, optional.
        :type init_codes: NDArray | None.
        :param kwargs: Parameters that are passed to the random
                       generator to sample from the chosen distribution
                       (e.g. loc=0, scale=1 for the choice init_cond=normal).
        '''
        
        # Codes were provided
        if isinstance(init_codes, np.ndarray):
            # Check shape consistency
            if init_codes.shape != (self.n_states, *self._shape):
                err_msg = 'Provided initial condition does not match expected shape'
                raise Exception(err_msg)
            # Use input codes as first codes
            self._prev_codes = init_codes.copy()
        # Codes were not provided: random generation
        else:
            # Use the specified distribution to randomly sample initial codes
            self._prev_codes = self._rnd_sample(size=(self.n_states, *self._shape), **kwargs)

        return self._prev_codes.copy()
    
    @property
    def _rnd_sample(self) -> Callable:
        '''
        Uses the distribution attribute to return the specific
        distribution function.
        
        :return: Distribution function.
        :rtype: Callable
        '''
        match self._distr:
            case 'normal':   return self._rng.normal
            case 'gumbel':   return self._rng.gumbel
            case 'laplace':  return self._rng.laplace
            case 'logistic': return self._rng.logistic
            case _: raise ValueError(f'Unrecognized distribution: {self._distr}')
    
class GeneticOptimizer(Optimizer):
    '''
    Optimizer that implements a genetic optimization strategy.
    In particular these optimizer devise a population of candidate
    solutions (set of parameters) and iteratively improves the
    given objective function via the following heuristics:
    
    - The top_k performing solution are left unaltered
    - The rest of the population pool are recombined to produce novel
      candidate solutions via breeding and random mutations
    - The num_parents contributing to a single offspring are selected
      via importance sampling based on parents fitness scores
    - Mutations rate and sizes can be adjusted independently 
    '''
    
    def __init__(
        self,
        states_space : None | Dict[int | str, Tuple[float | None, float | None]] = None,
        states_shape : None | int | Tuple[int, ...] = None,
        random_seed  : None | int = None,
        random_distr : RandomDistribution = 'normal',
        mutation_size : float = 0.1,
        mutation_rate : float = 0.3,
        population_size : int = 50,
        temperature : float = 1.,
        num_parents : int = 2,
        topk: int = 2
    ) -> None:
        '''
        Initialize a new GeneticOptimizer

        :param states_space: NOTE: Currently NOT supported.
        :type states_space: None | Dict[int  |  str, Tuple[float  |  None, float  |  None]], optional
        :param states_shape: Tuple defining the shape of the optimization 
                             space (assumed free of constraints).
        :type states_shape: None | int | Tuple[int, ...], optional
        :param random_seed: Seed for random number generation
        :type random_seed: None | int, optional.
        :param random_distr: Nature of the random distribution for initial
                             random codes generation, defaults to `normal`.
        :type random_distr: RandomDistribution
        :param mutation_size: Probability of single-point mutation, defaults to 0.3
        :type mutation_size: float, optional
        :param mutation_rate: Scale of punctual mutations (how big the effect of 
                              mutation can be), defaults to 0.1
        :type mutation_rate: float, optional
        :param population_size: Number of subject in the population, defaults to 50
        :type population_size: int, optional
        :param temperature: Temperature for controlling the softmax conversion
                            from scores to fitness (the actual prob. to sample 
                            a given parent for breeding), defaults to 1.
        :type temperature: float, optional
        :param num_parents: Number of parents contributing their genome
                            to a new individual, defaults to 2
        :type num_parents: int, optional
        '''
        
        super().__init__(
            states_space=states_space,
            states_shape=states_shape,
            random_seed=random_seed, 
            random_distr=random_distr,
        )
        
        # Optimization hyperparameters
        self._num_parents   = num_parents
        self._temperature   = temperature
        self._mutation_size = mutation_size
        self._mutation_rate = mutation_rate
        self._init_pop_size = population_size
        self._topk          = topk
        
    def __str__(self) -> str:
        ''' Return a string representation of the object for logging'''
        return f'GeneticOptimizer[n_states: {self.n_states}; n_parents: {self._num_parents};'\
               f' temperature: {self._temperature}; mutation_size: {self._mutation_size}; mutation_rate: {self._mutation_rate}]'
    
    def __repr__(self) -> str: return str(self)

    @property
    def n_states(self) -> int:
        '''
        The number of states is the number of produced codes.
        If no code was produced yet, it is simply the initial population size.
        '''
        return len(self._prev_codes) if self._prev_codes is not None else self._init_pop_size
    
    def step(
        self,
        data : Tuple[Score, Message],
        out_pop_size: int   | None = None,
        temperature : float | None = None, 
        save_topk : int     | None = None,   
    ) -> Tuple[Codes, Message]:
        '''
        Optimizer step function that uses an associated score
        to each code to produce a new set of stimuli.

        :param data: Scores associated to each code and message containing masking
                     information for natural images filtering.
        :type data: Tuple[Score, Message]
        :param out_pop_size: Population size for the next generation. 
                             If not given the old one is used.
        :type out_pop_size: int | None, optional
        :param temperature: Temperature for softmax conversion from scores to fitness, 
                            (i.e. the actual probabilities of selecting a given subject for 
                            reproduction), if not given default one is used.
        :type temperature: float | None, optional
        :param save_topk: Number of top-performing subject to preserve unaltered
                          during the current generation (to avoid loss of provably 
                          decent solutions).
        :type save_topk: int, optional
        :return: Optimized set of codes.
        :rtype: Codes
        '''
        
        # Extract score and message
        scores, msg = data
        
        # Optimization parameter
        pop_size    = default(out_pop_size, self.n_states)      # Use previous number of states as default
        temperature = default(temperature,  self._temperature)  # Use optimizer temperature as default
        save_topk   = default(save_topk,    self._topk)         # Use topk as default

        # Prepare data structure for the optimized codes
        codes_new = np.empty(shape=(pop_size, *self._shape), dtype=np.float32)

        # Get indices that would sort scores so that we can use it
        # to preserve the top-scoring stimuli
        sort_s = np.argsort(scores)
        topk_c = self.codes[sort_s[-save_topk:]]
        
        # Convert scores to fitness (probability) via 
        # temperature-gated softmax function (needed only for rest of population)
        fitness = softmax(scores / temperature)
        
        # The rest of the population is obtained by generating
        # children using breeding and mutation.
        
        # Breeding
        next_gen = self._breed(
            pop_fitness=fitness,
            num_children=pop_size - save_topk,
        )
        
        # Mutating
        next_gen = self._mutate(population=next_gen)

        # New codes combining previous top-k codes and new generated ones
        codes_new[:save_topk] = topk_c
        codes_new[save_topk:] = next_gen
        
        self._prev_codes = codes_new.copy()

        return codes_new, msg
    
    def _mutate(
        self,
        population    : NDArray | None = None,
        mutation_rate : float   | None = None,
        mutation_size : float   | None = None,
    ) -> NDArray:
        '''
        Perform punctual mutation to given population using input parameters.

        :param population: Population of codes to mutate, default to old codes.
        :type population: NDArray | None, optional
        :param mutation_rate: Scale of punctual mutations (how big the effect of 
                              mutation can be).
        :type mutation_rate: float | None, optional
        :param mutation_size: Probability of single-point mutation.
        :type mutation_size: float | None, optional
        :return: Mutated population.
        :rtype: NDArray
        '''
        
        # If not given we use default values
        population    = default(population, self.codes)
        mutation_rate = default(mutation_rate, self._mutation_rate)
        mutation_size = default(mutation_size, self._mutation_size)

        # Identify mutations spots for every subject in the population
        mutants = population.copy()
        
        mut_loc = self._rng.choice(
            [True, False],
            size=mutants.shape,
            p=(mutation_rate, 1 - mutation_rate),
            replace=True
        )

        # TODO Sometimes produces runtime warnings
        mutants[mut_loc] += self._rnd_sample(
            scale=mutation_size, 
            size=mut_loc.sum()
        )

        return mutants 
    
    def _breed(
        self,
        pop_fitness : NDArray,
        num_children : int | None = None,
        allow_clones : bool = False,
    ) -> NDArray:
        '''
        Perform breeding on the given population with given parameters.

        :param population: Population to breed, defaults to None
        :type population: NDArray | None, optional
        :param pop_fitness: Population fitness (i.e. probability to be selected
                            as parents for the next generation).
        :type pop_fitness: NDArray | None, optional
        :param num_children: Number of children in the new population, defaults to None
        :type num_children: int | None, optional
        :param allow_clones: If a code can occur as a parent multiple times, default to False.
        :type allow_clones: bool, optional
        :return: Breed population.
        :rtype: NDArray
        '''

        # NOTE: We use lazydefault here because .param and .score might
        #       not be populated (i.e. first call to breed) but we don't
        #       want to fail if either population or fitness are provided
        population  = self.codes
        num_children = default(num_children, len(population))
        
        # Select the breeding family based on the fitness of each parent
        # NOTE: The same parent can occur more than once in each family
        
        families = self._rng.choice(
            len(population),
            size=(num_children, self._num_parents),
            p=pop_fitness,
            replace=True,
        ) if allow_clones else np.stack([ # TODO avoid resampling with only two parents
            self._rng.choice(
                len(population),
                size=self._num_parents,
                p=pop_fitness,
                replace=False,
            ) for _ in range(num_children)
        ])

        # Identify which parent contributes which genes for every child
        parentage = self._rng.choice(self._num_parents, size=(num_children, *self._shape), replace=True)
        children = np.empty(shape=(num_children, *self._shape))

        for child, family, lineage in zip(children, families, parentage):
            for i, parent in enumerate(family):
                genes = lineage == i
                child[genes] = population[parent][genes]
                
        return children