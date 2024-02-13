import numpy as np
import torch.nn as nn
from torch import Tensor

from einops import rearrange
from collections import defaultdict
from typing import Dict, Tuple, List
from numpy.typing import DTypeLike, NDArray

from .networks import NetworkSubject
from .utils import SubjectState

class SilicoProbe:
    '''
        Basic probe to attach to an artificial network to
        record the activations of an arbitrary number of
        hidden units in arbitrary layers. 
    '''
    
    def __init__(
        self,
        target : Dict[str, None | Tuple[int, ...] | Tuple[NDArray, ...]], # TODO Define Alias if used in other locations
        format : DTypeLike = np.float32,
    ) -> None:
        '''
        Artificial probe for recording hidden unit activations
        
        :param target: Specification of which units to record from which
            layer. Layers are identified via their name and units by their
            position in the layer (multi-dimensional index). If None is
            provided as specification it is assumed that ALL unit from that
            given layer are to be recorded.
        :type target: Dict[str, None | Tuple[int, ...] | Tuple[np.ndarray, ...]]
        :param format: Numeric format to use to store the data. Useful to
            reduce file size or memory footprint for large recordings
        :type format: np.dtype
        '''
        
        self._target = target
        self._format = format
        
        # Here we define the activations dictionary of the probe.
        # The dictionary is indexed by the layer name and contains
        # a list with all the activations to which it was exposed to.
        self._data : Dict[str, List[NDArray]] = defaultdict(list)
        
    @property
    def features(self) -> SubjectState:
        '''
        Returns a dictionary of probe activations indexed by
        layer name. The activation is a tensor with first dimension
        referring to the specific activation.

        :return: _description_
        :rtype: Dict[str, NDArray]
        '''
        return {
            k : np.concatenate(v) for k, v in self._data.items()
        }
        
    @property
    def target_names(self) -> List[str]:
        '''
        Returns probe target layer names.

        :return: Probe target names.
        :rtype: List[str]
        '''
        return list(self._target.keys())
        
    def __call__(
        self,
        module : nn.Module,
        inp : Tensor,
        out : Tensor
    ) -> None:
        '''
        Custom hook designed to record from an artificial network. This
        function SHOULD NOT be called directly by the user, it should be
        called via the `forward_hook` attached to the network layer.
        This function stores the layer outputs in the data dictionary.
        Function signature is the one expected by the hook mechanism.
        
        NOTE: This function assumes! the module posses the attribute
            `name` which is a unique string identifier for this layer
        
        :param module: Current network layer we are registering from.
        :type module: torch.nn.Module
        :param inp: The torch Tensor the layer received as input
        :type inp: torch.Tensor
        :param out: The torch Tensor the layer produced as output
        :type out: torch.Tensor
        
        :returns: None, data is stored as a side-effect in the class data
            attribute that can be inspected at subsequent times.
        :rtype: None
        '''
        if not hasattr(module, 'name'):
            raise AttributeError(f'Encounter module {module} with unregistered name.')
        
        # Grab the layer output activations and put special care to
        # detach them from torch computational graph, bring them to
        # GPU and convert them to numpy for easier storage and portability
        full_act : np.ndarray = out.detach().cpu().numpy().squeeze()
        
        # From the whole set of activation, we extract the targeted units
        # NOTE: If None is provided as target, we simply retain the whole
        #       set of activations from this layer
        targ_idx = self._target[module.name]
        targ_act = full_act if targ_idx is None else full_act[(slice(None), *targ_idx)]
        
        # Rearrange data to have common shape [batch_size, num_units] and
        # be formatted using the desired numerical format (saving memory)
        targ_act = rearrange(targ_act.astype(self._format), 'b ... -> b (...)')
        
        # Register the network activations in probe data storage
        self._data[module.name].append(targ_act)
        
    def empty(self) -> None:
        '''
        Remove all stored activations from data storage 
        '''
        self._data = defaultdict(list)
        

# TODO Superclass Recording with (SilicoRecording, AnimalRecording)
#      with an abstract method __call__(self, Stimulus) -> SubjectState 
class SilicoRecording:
    '''
        Class representing a recording in silico from a network
        over a set of input stimuli.
    '''
    
    def __init__(self, network : NetworkSubject, probe : SilicoProbe) -> None:
        '''
        The constructor checks consistency between network and
        probe layers names and attach the probe hooks to the network
        
        :param network: Network representing a tasked subject.
        :type network: NetworkSubject
        :param probe: Probe for recording activation.
        :type probe: SilicoProbe
        :param stimuli: Set of visual stimuli.
        :type stimuli: Tensor
        '''
        
        # Check if probe layers exist in the network
        assert all(
            e in network.layer_names for e in probe.target_names 
        ),f"Probe recording sites not in the network: {set(probe.target_names).difference(network.layer_names)}"
        
        self._network: NetworkSubject = network
        self._probe: SilicoProbe = probe
        
        # Attach hooks
        for target in probe.target_names:
            self._network.get_layer(layer_name=target).register_forward_hook(self._probe)  # TODO callback as __call__ method of an object ?
            
    def __call__(self, stimuli: Tensor) -> SubjectState:
        """
        """
        
        self._network(stimuli)
        
        out = self._probe.features
        
        self._probe.empty() # TODO Make sense?
        
        return out