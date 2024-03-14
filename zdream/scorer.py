from _collections_abc import dict_keys
from abc import ABC, abstractmethod
from functools import partial
from typing import Callable, Dict, List, Tuple, cast, Literal

import numpy as np
from einops import rearrange
from einops import reduce
from einops.einops import Reduction
from numpy.typing import NDArray
from scipy.spatial.distance import pdist

from zdream.utils.model import ScoringFunction
from zdream.utils.model import AggregateFunction

from .utils.model import Message, RecordingUnit, ScoringUnit
from .utils.model import StimuliScore
from .utils.model import SubjectState
from .utils.misc import default

# NOTE: This is the same type of _MetricKind from scipy.spatial.distance
#       which we need to redefine for issues with importing private variables from modules.
_MetricKind = Literal[
    'braycurtis', 'canberra', 'chebychev', 'chebyshev',
    'cheby', 'cheb', 'ch', 'cityblock', 'cblock', 'cb',
    'c', 'correlation', 'co', 'cosine', 'cos', 'dice',
    'euclidean', 'euclid', 'eu', 'e', 'hamming', 'hamm',
    'ha', 'h', 'minkowski', 'mi', 'm', 'pnorm', 'jaccard',
    'jacc', 'ja', 'j', 'jensenshannon', 'js', 'kulczynski1',
    'mahalanobis', 'mahal', 'mah', 'rogerstanimoto', 'russellrao',
    'seuclidean', 'se', 's', 'sokalmichener', 'sokalsneath',
    'sqeuclidean', 'sqe', 'sqeuclid', 'yule'
]

class Scorer(ABC):
    '''
    Abstract class for computing subject scores.
    '''

    def __init__(
        self,
        criterion : ScoringFunction,
        aggregate : AggregateFunction,
    ) -> None:
        self.criterion = criterion
        self.aggregate = aggregate

    def __call__(self, data : Tuple[SubjectState, Message]) -> Tuple[StimuliScore, Message]:
        '''
        Compute the subject scores given a subject state.

        :param state: state of subject
        :type state: SubjectState
        :return: array of scores
        :rtype: StimuliScore
        '''
        state, msg = data
        
        layer_scores = self.criterion(state)
        
        scores = self.aggregate(layer_scores)
        
        return (scores, msg)
    
    def _check_key_consistency(self, target: dict_keys, state: dict_keys):
        #we check that our subject state contains at least the keys of target for computing
        #the scores of interest. Keys in excess in subject (i.e.layers only for recording)
        # will be ignored by the scorer (see score/combine methods in children classes)
        
        if not set(target).issubset(set(state)):
            err_msg = f'Keys of test image not in target {set(state).difference(target)}'
            raise ValueError(err_msg)
        
    @property
    @abstractmethod
    def target(self) -> Dict[str, ScoringUnit]:
        pass
        
    @property
    def optimizing_units(self) -> int:
        ''' How many units involved in optimization '''
        return sum(
            [len(v) for v in self.target.values()]
        )
        
    
class MSEScorer(Scorer):
    '''
        Class simulating a neuron score which target state 
        across one or multiple layers can be set.
        The scoring function is the MSE with the target.
    '''
    
    def __init__(
        self,
        target : SubjectState,
        aggregate : AggregateFunction | None = None,
    ) -> None:
        '''
        The constructor uses the target state to create
        the objective function.

        :param target: target state or dictionary of target states 
                        indexed by layer name
        :type target: SubjectState
        '''
        
        self._target : SubjectState = target
        
        # MSEScorer criterion is the mse between the measured subject
        # state and a given fixed target. This is accomplished via the
        # partial higher order function that fixes the second input to
        # the _score method of the class
        criterion = partial(self._score, target=self._target)
        aggregate = default(aggregate, lambda d : cast(NDArray, np.mean(list(d.values()), axis=0)))
        
        super().__init__(
            criterion=criterion,
            aggregate=aggregate,    
        )
        
    def __str__(self) -> str:
        
        dims = ", ".join([f"{k}: {v.shape}" for k, v in self._target.items()])
        
        return f'MSEScorer[target size: ({dims})]'
    
    def __repr__(self) -> str: return str(self)

        
    def _score(self, state: SubjectState, target: SubjectState) -> Dict[str, StimuliScore]:
        # Check for layer name consistency
        self._check_key_consistency(target=target.keys(), state=state.keys())
        
        scores = {
            layer: - self.mse(state[layer], target[layer]) for layer in state.keys()
            if layer in target
        }
                
        return scores
    
    @staticmethod
    def mse(a : NDArray, b : NDArray) -> NDArray:
            a = rearrange(a, 'b ... -> b (...)')
            b = rearrange(b, 'b ... -> b (...)')
            return np.mean(np.square(a - b), axis=1).astype(np.float32)
    
    @property
    def template(self) -> SubjectState:
        return self._target
    
    @property
    def target(self) -> Dict[str, ScoringUnit]:
        return {k: list(range(np.prod(v.shape))) for k, v in self._target.items()}

    
class MaxActivityScorer(Scorer):
    
    def __init__(
            self, 
            trg_neurons: Dict[str, ScoringUnit], 
            aggregate: AggregateFunction,
            reduction: Reduction = np.mean,
        ) -> None:
        
        
        self._trg_neurons = trg_neurons
        criterion = partial(self._combine, neurons=trg_neurons)
                
        self.reduction = partial(reduce, pattern='b u -> b', reduction=reduction)
                
        super().__init__(criterion, aggregate)
        
    def __str__(self) -> str:
        
        dims = ", ".join([f"{k}: {len(v)} units" for k, v in self.target.items()])
        
        return f'MaximizeActivityScorer[target neurons: ({dims})]'
    
    def __repr__(self) -> str: return str(self)
        
    def _combine(self, state: SubjectState, neurons: Dict[str, List[int]]) -> Dict[str, StimuliScore]:
        
        self._check_key_consistency(target=neurons.keys(), state=state.keys())
        
        scores = {
            layer: self.reduction(activations[:, neurons[layer] if neurons[layer] else slice(None)])
            for layer, activations in state.items()
            if layer in neurons
        }
        
        return scores    
    
    @property
    def target(self) -> Dict[str, ScoringUnit]:
        ''' How many units involved in optimization '''
        return self._trg_neurons
    
    
class WeightedPairSimilarityScorer(Scorer):
    '''
    This scorer computes weighted similarities (negative distances)
    between groups of subject states. Weights can either be positive
    or negative. Groups are defined via a grouping function. 
    '''

    # TODO: We are considering all recorded neurons
    def __init__(
        self,
        signature : Dict[str, float],
        metric : _MetricKind = 'euclidean',
        filter_distance_fn : Callable[[NDArray], NDArray] | None = None,
    ) -> None: 
        '''
        
        :param signature: Dictionary containing for each recorded state
            (the str key in the dict) the corresponding weight (a float)
            to be used in the final aggregation step. Positive weights
            (> 0) denote desired similarity, while negative weights (< 0)
            denote desired dissimilarity.
        :type signature: Dictionary of string with float values
        :param metric: Which kind of distance to use. Should be one of
            the supported scipy.spatial.distance function
        :type metric: string
        :param pair_fn: Grouping function defining (within a given state,
            i.e. a given recorded layer) which set of activations should be
            compared against.
            Default: Odd-even pairing, i.e. given the subject state:
                state = {
                    'layer_1' : [+0, +1, -1, +3, +2, +4],
                    'layer_2' : [-4, -5, +9, -2, -7, +8],
                }
            the default pairing build the following pairs:
                'layer_1' : {
                    'l1_pair_1: [+0, -1, +2],
                    'l1_pair_2: [+1, +3, +4],
                }
                'layer_2' : {
                    'l2_pair_1': [-4, +9, -7],
                    'l2_pair_2': [-5, -2, +8],
                }
            so that the similarities will be computed as:
                'layer_1' : similarity(l1_pair_1, l1_pair_2)
                'layer_2' : similarity(l2_pair_1, l2_pair_2)
        :type pair_fn: Callable[[NDArray], Tuple[NDArray, NDArray]] | None
        '''
        
        
        # If grouping function is not given use even-odd split as default
        filter_distance_fn = default(filter_distance_fn, lambda x : x)
        
        # If similarity function is not given use euclidean distance as default
        self._metric = partial(pdist, metric=metric)
        
        criterion = partial(self._score, filter_distance_fn=filter_distance_fn)
        aggregate = partial(self._dprod, signature=signature)
        
        self._signature = signature

        super().__init__(
            criterion=criterion,
            aggregate=aggregate,
        )
        
    def __str__(self) -> str:
        
        weights = ", ".join([f"{k}: {v}" for k, v in self._signature.items()])
        
        return f'WeightedPairSimilarityScorer[metric: {self._metric}; target size: ({weights})]'
        
    def __repr__(self) -> str: return str(self)

    @property
    def optimizing_units(self) -> int:
        ''' How many units involved in optimization '''
        return 0

    def _score(
        self,
        state : SubjectState,
        filter_distance_fn : Callable[[NDArray], NDArray]
    ) -> Dict[str, NDArray]:
        scores = {
            k: -self._metric(v) for k, v in state.items()
        }
        
        scores = {
            k: filter_distance_fn(v) for k, v in scores.items()
        }
        
        return scores

    def _dprod(self, state : Dict[str, StimuliScore], signature : Dict[str, float]) -> StimuliScore:
        return cast(
            StimuliScore,
            np.sum(
                [v * state[k] for k, v in signature.items()],
                axis=0
            )
        )
        
