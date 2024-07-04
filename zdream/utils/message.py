'''
This file implements the Message dataclass that is used to store the information 
relative to the current state of the Zdream framework. 

The class is designed to store all the information relative to the current state of the framework, 
including the history of all the data that has been processed.
'''

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np
from numpy.typing import NDArray

from .misc import SEM
from .types import Codes, Mask, RFBox, RecordingUnit, ScoringUnit, Scores, States

@dataclass
class Message:
    '''
    The dataclass is an auxiliary generic component that is shared among the entire data-flow.
    The aim of the class is to make different components communicate through the data-passing 
    of a common object they all can manipulate.
    '''
    
    start_time   : float = 0
    end_time     : float = 0
    
    @property
    def elapsed_time(self) -> float:
        
        if not self.start_time:
            raise ValueError('Cannot compute elapsed time: start time not set')
        
        if not self.end_time:
            raise ValueError('Cannot compute elapsed time: end time not set')
        
        return self.end_time - self.start_time


@dataclass
class ZdreamMessage(Message):
    '''
    Subclass of Message dataclass that contains all the information relative to the Zdream framework. 
    
    The class is designed to store all the information relative to the current state of the framework, 
    including the history of all the data that has been processed.
    '''
    
    # --- ZDREAM COMPONENTS ---
    
    codes_history      : List[Codes] = field(default_factory=list)
    ''' Codes  representing the images in a latent space. '''
    
    states_history     : List[States] = field(default_factory=list)
    ''' Subject responses to a visual stimuli.'''
    
    scores_gen_history : List[Scores] = field(default_factory=list)
    ''' Scores associated to each synthetic stimuli. '''
    
    scores_nat_history : List[Scores] = field(default_factory=list)
    ''' Scores associated to each natural stimuli. '''
    
    # NOTE: We are not storing the actual stimuli as they can be
    #       deterministically generated from the codes using the generator.
    
    # --- UNITS ---

    rec_units : Dict[str, RecordingUnit] = field(default_factory=dict)
    '''
    Dictionary containing the recording units associated to the different layers.
    '''
    
    scr_units : Dict[str, ScoringUnit]   = field(default_factory=dict)
    '''
    Dictionary containing the scoring units associated to the different layers.
    '''
    
    # NOTE: The two dictionaries above interact since the scoring units indexes
    #       don't refer to the layer in its entirety but only to the units that
    #       have been recorded.
    
    # --- NATURAL IMAGES ---
    
    masks_history : List[Mask] = field(default_factory=list)
    '''
    Boolean mask associated to a set of stimuli indicating if they are synthetic or natural images. 
    Defaults to empty array indicating no natural images.
    '''
    
    labels_history : List[List[int]] = field(default_factory=list)
    '''
    List of labels associated to the set of natural image stimuli. Defaults to empty list.
    
    NOTE:   Labels are only associated to natural images so they are
            they only refers to 'False' entries in the mask.
    '''
    
    # --- RF MAPS ---
    
    rf_maps   : Dict[Tuple[str, str], List[RFBox]]  = field(default_factory=dict)
    '''
    Receptive fields involved in the optimization process 
    The dictionary saves the mapping from couple of layer names (from and to) to the list of receptive fields.
    '''
    
    # --- OPTIMIZING GROUPS ---
    
    n_group : int = 1
    '''
    Number of entities representing an optimization group.
    By default, the number of groups is set to 1 indicating the optimization refers to a single entity (e.g. a single image).
    The number of groups can be increased to optimize multiple entities at the same time, for example 2 in the case
    of optimizing a metric between a pair of images.
    '''
    
    # --- PROPERTIES ---
    
    # The properties simplify the access to the most recent component information in the history
    # Note they will fail with a 'ValueError' if the history is empty.
    
    @property
    def codes(self) -> Codes:  
        try: return self.codes_history[-1] 
        except IndexError: raise ValueError('No codes in history')
    
    @property
    def states(self) -> States:
        try: return self.states_history[-1]
        except IndexError: raise ValueError('No states in history')
    
    @property
    def scores_gen(self) -> Scores:
        try: return self.scores_gen_history[-1]
        except IndexError: raise ValueError('No synthetic scores in history')
    
    @property
    def scores_nat(self) -> Scores: 
        try: return self.scores_nat_history[-1]
        except IndexError: raise ValueError('No natural scores in history')
        
    @property
    def mask(self) -> Mask:
        try: return self.masks_history[-1]
        except IndexError: raise ValueError('No masks in history')
        
    @property
    def labels(self) -> List[int]:
        try: return self.labels_history[-1]
        except IndexError: raise ValueError('No labels in history')
    
    # --- LAYERS ---
        
    @property
    def rec_layers(self) -> List[str]: return list(self.rec_units.keys())
    ''' Return the list of layers that have been recorded. '''
    
    @property
    def scr_layers(self) -> List[str]: return list(self.scr_units.keys())
    ''' Return the list of layers that have been scored. '''
    
    # --- BEST SOLUTION ---
    
    @property
    def best_code(self) -> Codes:
        '''
        Retrieve the code that produced the highest score from code scores history.

        :return: Best code score.
        :rtype: NDArray
        '''
        
        # Extract indexes for best scores
        flat_idx : np.intp  = np.argmax(self.scores_gen_history)
        best_gen, *best_idx = np.unravel_index(flat_idx, np.shape(self.scores_gen_history))
        
        # Extract the best code from generation and index
        best_code = self.codes_history[best_gen][best_idx]
        
        return best_code
    
    # --- STATISTICS ---    
    
    def _scores_stats(self, scores: List[NDArray], synthetic: bool) -> Dict[str, Any]:
        '''
        Perform basic statics on scores, either associated to natural or synthetic images.

        :param scores: Scores to compute statistics on.
        :type scores: List[NDArray]
        :param synthetic: Flag indicating if the scores are associated to synthetic images.
        :type synthetic: bool
        :return: Computed statistics.
        :rtype: Dict[str, Any]
        '''
        
        # Extract indexes for best scores
        flat_idx : np.intp  = np.argmax(scores)
        best_gen, *best_idx = np.unravel_index(flat_idx, np.shape(scores))
        
        # Extract the best code from generation and index
        gen_idx : List[int]  = np.argmax(scores, axis=1)
        
        # We compute statics relative to scores
        stats = {
            'best_score' : scores[best_gen][best_idx],                          # best score
            'curr_score' : scores[-1],                                          # current score
            'mean_gens'  : np.array([np.mean(s) for s in scores]),              # mean score across generations
            'sem_gens'   : np.array([SEM(s)    for s in scores]),               # standard error of the mean across generations
            'best_gens'  : [score[idx] for score, idx in zip(scores, gen_idx)], # best score for each generation 
        }
        
        # Add information relative to synthetic images relative to the code
        if synthetic:
            
            # Add information relative to codes
            stats_codes = {
                'best_code'       : self.best_code,                     # best code
                'curr_codes'     : self.codes,                         # current code
                'best_codes_gen' : [                                   # best_code per generation
                    codes[idx] 
                    for codes, idx in zip(self.codes_history, gen_idx)
                ]
            }
            
            # Update stats dictionary
            stats.update(stats_codes)
            
        return stats
        
    @property
    def stats_gen(self) -> Dict[str, Any]: return self._scores_stats(scores=self.scores_gen_history, synthetic=True)
    ''' Return statistics for synthetic codes '''
        
    
    @property
    def stats_nat(self) -> Dict[str, Any]: return self._scores_stats(scores=self.scores_nat_history, synthetic=False)
    ''' Return statistics for natural images '''
