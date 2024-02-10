import numpy as np
from abc import abstractmethod

from scipy.special import softmax

from utils import default
from utils import lazydefault

from typing import Callable, Dict, Tuple, List
from numpy.typing import NDArray

ObjectiveFunction = Callable[[NDArray | Dict[str, NDArray]], NDArray[np.float32]]
SubjectState = NDArray | Dict[str, NDArray]

class Optimizer:
    '''
    Base class for generic optimizer, which keeps track of current
    parameter set (codes) and defines the abstract `step()` method 
    which every concrete instantiation should implement.
    '''
    
    def __init__(
        self,
        objective_fn : ObjectiveFunction,
        states_space : None | Dict[int | str, Tuple[float | None, float | None]] = None,
        states_shape : None | int | Tuple[int, ...] = None,
        random_state : None | int = None,
        random_distr : None | str = None,
    ) -> None:
        '''
        Create a  gradient-free optimizer by specifying its objective
        function and (optional) state space conditions.
        
        :param objective_fn: Function that accepts a current state
            (type SubjectState) and computes the associated score
            (a single float scalar number)
        :type objective_fn: ObjectiveFunction (Callable with specific
            signature)
        :param states_space: Dictionary specifying the optimization
            domain where each entry is a direction and corresponding
            values are the min-max acceptable values along that dir
        :type states_spaces: Dictionary of int|str -> Tuple[int, int]
        :param states_shape: Shape specifying the dimensionality of
            the optimization domain. If states_space is specified it
            supersedes the states_shape as shape is inferred from the
            dictionary dimensionality.
        :type states_shape: int or tuple of ints
        '''
        assert states_shape is not None or states_space is not None,\
            'Either states_shape or states_space must be specified'
        
        if isinstance(states_shape, int):
            states_shape = (states_shape,)
        
        self.obj_fn = objective_fn
        self._space = lazydefault(states_space, lambda : {i : (None, None) for i in range(len(states_shape))}) # type: ignore
        self._shape = lazydefault(states_shape, lambda : (len(states_space),))                                 # type: ignore
        
        self._param : List[NDArray] = []
        self._score : List[NDArray] = []
        self._distr = random_distr
        
        # Initialize the internal random number generator for reproducibility
        self._rng = np.random.default_rng(random_state)
        
    def init(self, init_cond : str | NDArray = 'normal', **kwargs) -> None:
        '''
        Initialize the optimizer parameters. If initial parameters
        are provided they should have matching dimensionality as 
        expected by provided states shape, otherwise they are sampled
        randomly (distribution can be specified via a name string)
        
        :param init_cond: initial condition for optimizations
        :type init_cond: either string (name of distribution
            to use, default: normal) or numpy array
            
        :param kwargs: parameters that are passed to the random
            generator to sample from the chosen distribution
            (e.g. loc=0, scale=1 for the choice init_cond=normal)
        '''
        
        if isinstance(init_cond, np.ndarray):
            assert init_cond.shape == self._shape,\
                'Provided initial condition does not match expected shape'
            self._param = [init_cond.copy()]
        else:
            self._distr = init_cond
            self._param = [self.rnd_sample(**kwargs)]
    
    @abstractmethod
    def step(self, states : SubjectState) -> NDArray:
        '''
        Abstract step method. The `step()` method collects the set of
        old states from which it obtains the set of new scores via the
        objective function and updates the internal parameters to produce
        a new set of states that would hopefully increase future scores
        
        :param states: Set of current observables (e.g. the activations
            of a hidden population in a neural network)
        :type states: Numpy array or dictionary indexed by string (e.g.
            layer names) and corresponding observables as Numpy array
            
        :returns: Set of new parameters (codes) to be used to improve
            future states scores
        :rtype: Numpy array  
        '''
        raise NotImplementedError('Optimizer is abstract. Use concrete implementations')
    
    @property
    def rnd_sample(self) -> Callable:
        match self._distr:
            case 'normal': return self._rng.normal
            case 'gumbel': return self._rng.gumbel
            case 'laplace': return self._rng.laplace
            case 'logistic': return self._rng.logistic
            case _: raise ValueError(f'Unrecognized distribution: {self._distr}')
    
    @property
    def stats(self) -> Dict[str, NDArray]:
        best_idx = np.argmax(self._score)
        
        return {
            'best_score' : self._score[best_idx],
            'best_param' : self._param[best_idx],
            'curr_score' : self._score[-1],
            'curr_param' : self._param[-1],
        }
        
    @property
    def scores(self) -> NDArray:
        return self._score[-1]
    
    @property
    def param(self) -> NDArray:
        return self._param[-1]
    
class GeneticOptimizer(Optimizer):
    '''
    Optimizer that implements a genetic optimization stategy.
    In particular these optimizer devise a population of candidate
    solutions (set of parameters) and iteratively improves the
    given objective function via the following heuristics:
    - The top_k performing solution are left unhaltered
    - The rest of the population pool are recombined to produce novel
      candidate solutions via breeding and random mutations
    - The num_parents contributing to a single offspring are selected
      via importance sampling based on parents fitness scores
    - Mutations rate and sizes can be adjusted independently 
    '''
    
    def __init__(
        self,
        objective_fn: ObjectiveFunction,
        states_space : None | Dict[int | str, Tuple[float | None, float | None]] = None,
        states_shape : None | int | Tuple[int, ...] = None,
        random_state : None | int = None,
        random_distr : None | str = None,
        mutation_size : float = 0.1,
        mutation_rate : float = 0.3,
        population_size : int = 50,
        temperature : float = 1.,
        num_parents : int = 2,
    ) -> None:
        '''
        :param objective_fn: Objective function used to convert
            observables (states) to scores
        :param states_space: Currently NOT USED
        :param states_shape: Tuple defining the shape of the
            optimization space (assumed free of constraints)
        :param random_state: Seed for random number generation
        :param random_distr: Name of distribution to use to sample
            initial conditions if not directly provided
        :param mutation_size: Scale of puntual mutations (how big
            the effect of mutation can be)
        :param muration_rate: Probability of single-point mutation
        :param population_size: Number of subject in the population
        :param temperature: Temperature for controlling the softmax
            conversion from scores to fitness (the actual prob. to
            sample a given parent for breeding)
        :param num_parents: Number of parents contributing their
            genome to a new individual
        '''
        
        super().__init__(
            objective_fn,
            states_space,
            states_shape,
            random_state, 
            random_distr
        )
        
        self.num_parents = num_parents
        self.temperature = temperature
        self.mutation_size = mutation_size
        self.mutation_rate = mutation_rate
        self.population_size = population_size
    
    def step(
        self,
        states : NDArray | Dict[str, NDArray],
        temperature : float | None = None, 
        save_topk : int = 2,   
    ) -> NDArray:
        '''
        Optimizer step function where current observable (states)
        are scored using the internal objective function and a
        novel set of parameter is proposed that would hopefully
        increase future scores.

        :param states: Set of observables gather from the environment
            (i.e. ANN activations). Can be either a numpy array
            collecting observables or a dictionary indexed by the
            observable names (i.e. layer names in an ANN) and values
            being the corresponding observables.
            NOTE: Proper handling of these two different types is
                  derred to the objective function. Optimizer is
                  blind to proper computation of scores from states
        :type states: Either numpy array or Dict[str, NDArray]
        :param temperature: Temperature in the softmax conversion
            from scores to fitness, i.e. the actual probabilities of
            selecting a given subject for reproduction
        :type temperature: positive float (> 0)
        :param save_topk: Number of top-performing subject to preserve
            unhaltered during the current generation (to avoid loss
            of provably decent solutions)
        :type save_topk: positive int (> 0)

        :returns new_pop: Novel set of parameters (new population pool)
        :rtype: Numpy array
        '''
        temperature = default(temperature, self.temperature)

        # Prepare new parameter (population) set
        new_pop = np.empty(shape=(self.population_size, *self._shape))

        # Use objective function to convert states to scores
        scores = self.obj_fn(states)

        # Convert scores to fitness (probability) via temperature-
        # gated softmax function
        fitness = softmax(scores / temperature)

        # Get indices that would sort scores so that we can use it
        # to preserve the top-scoring subject
        sort_idx = np.argsort(scores)
        top_k = self.param[sort_idx[-save_topk:]]
        rest  = self.param[sort_idx[:+save_topk]]

        new_pop[:save_topk] = top_k

        # The rest of the population is obtained by generating
        # children (breed) and mutating them
        new_pop[save_topk:] = self._breed(
            population=rest,
            pop_fitness=fitness,
        )

        new_pop[save_topk:] = self._mutate(
            population=rest,
        )

        # Bookkeping: update internal parameter history
        # and overal score history
        self._score.append(scores)
        self._param.append(new_pop)

        return new_pop
    
    def _mutate(
        self,
        mut_rate : float | None = None,
        mut_size : float | None = None,
        population : NDArray | None = None,
    ) -> NDArray:
        mut_rate = default(mut_rate, self.mutation_rate)
        mut_size = default(mut_size, self.mutation_size)
        population = default(population, self.param)

        # Identify mutations spots for every subject in the population
        mutants = population.copy()
        mut_loc = self._rng.choice([True, False],
            size=mutants.shape,
            p=(mut_rate, 1 - mut_rate),
            replace=True
        )

        mutants[mut_loc] += self.rnd_sample(scale=mut_size, size=mut_loc.sum())

        return mutants 
    
    def _breed(
        self,
        population : NDArray | None = None,
        pop_fitness : NDArray | None = None,
        num_children : int | None = None,
    ) -> NDArray:
        population = default(population, self.param)
        pop_fitness = default(pop_fitness, self.scores)
        num_children = default(num_children, len(population))
        
        # Select the breeding family based on the fitness of each parent
        # NOTE: The same parent can occur more than once in each family
        families = self._rng.choice(
            self.population_size,
            size=(num_children, self.num_parents),
            p=pop_fitness,
            replace=True,
        )
        
        # Identify which parent contributes which genes for every child
        parentage = self._rng.choice(self.num_parents, size=(num_children, *self._shape), replace=True)
        
        children = np.empty(shape=(num_children, *self._shape))
        for c, (child, family, lineage) in enumerate(zip(children, families, parentage)):
            for parent in family:
                genes = lineage == parent
                child[genes] = population[parent][genes]
                
        return children