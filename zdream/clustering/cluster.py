from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Counter, Dict, Iterable, List

import numpy as np
from numpy.typing import NDArray

from zdream.clustering.model import Label, Labels
from zdream.utils.io_ import read_json, save_json
from zdream.utils.logger import Logger, SilentLogger
from zdream.utils.types import ScoringUnit
from typing import List

class Cluster:
    ''' 
    Class representing a Cluster collecting a group of Cluster objects
    '''
    
    @dataclass
    class ClusterObject:
        '''
        Class representing an object inside the Cluster
        It has a single attribute label identifying the object
        '''
        
        label : Label
        ''' Label identifying the object (either numeric of symbolic string)'''
        
        # --- STRING REPRESENTATION ---
        
        def __str__ (self) -> str: return f'ClusterObject[label: {self.label}]'
        def __repr__(self) -> str: return str(self)
        
        @property
        def info(self) -> Dict[str, Any]: 
            ''' Provide a JSON-like object representation for object dump '''
            
            return {'label': self.label.tolist()}  # tolist() is used to convert numpy.int32 to int or numpy.str_ to str
        
    def __init__(
        self, 
        labels: Labels, 
    ):
        '''
        Instantiate a new cluster composed of a set of objects. 

        :param labels: Cluster object labels.
        :type labels: Labels
        '''
        
        # Objects with decreasing RANK
        self._objects = [self.ClusterObject(label=label) for label in labels]
    
    # --- MAGIC METHODS ---
    
    def __str__ (self) -> str: return f'Cluster[objects: {len(self)}'
    def __repr__(self) -> str: return str(self)
    def __len__ (self) -> int: return len(self.objects)
    
    def __iter__   (self)           -> Iterable[ClusterObject] : return iter(self.objects)
    def __getitem__(self, idx: int) -> ClusterObject           : return self.objects[idx]
    
    # --- PROPERTIES ---
    
    @property
    def objects(self) -> List[ClusterObject]: return self._objects
    ''' List of objects in the cluster'''

    @property
    def labels(self) -> Labels: 
        ''' List of labels of the objects in the cluster '''
        
        return np.array([obj.label for obj in self]) # type: ignore

    @property
    def scoring_units(self) -> ScoringUnit: 
        ''' 
        Return the scoring units of the cluster
        NOTE:   This is only available if the labels are of type np.int32
                and refer to the specific units index
        '''
        
        # Check if labels are of type np.int32
        other_types = [type(label) for label in self.labels if not isinstance(label, np.int32)]  # type: ignore
        if len(other_types) > 0:
            
            raise TypeError(
                f"Labels have type {set(other_types)}. This is used for symbolic labels. "\
                f"Use labels with type np.int32 for scoring units computation."
            )
        
        return list(self.labels) 
    
    @property
    def info(self) -> Dict[str, List[Dict[str, Any]] | Any]:
        '''
        Return information about the objects in the cluster to be dumped as a JSON
        '''
        
        return {'objects': [obj.info for obj in self]}  # type: ignore
    
    # --- UTILS ---

    def units_mapping(self, arr: NDArray) -> NDArray:
        '''
        Return a uniform weighting of the objects.
        
        NOTE:   This is trivial in the general case, but
                can turn useful in the case of subclasses implementing
                an internal weighting of the objects within the cluster.

        :param arr: Array with units to map
        :type arr: NDArray
        :rtype: UnitsMapping
        '''

        # Perform uniform mapping
        arr[:, self.labels] /= len(self)  # type: ignore
        
        return arr

class Clusters:
    '''
    Class for manipulating a set of `Cluster` objects.
    
    The class compute some statistics on clusters and 
    allow to dump them to file.
    '''
    
    # --- INSTANTIATION ---
    
    def __init__(self, clusters: List[Cluster] = []) -> None:
        '''
        Create list of clusters
        
        :param clusters: List of clusters
        :type clusters: List[Cluster]
        '''
        
        self._clusters = clusters
        
    @classmethod
    def from_labels(cls, labeling: NDArray) -> Clusters:
        '''
        Generate a Clusters object from a labeling array.
        '''
        
        clusters = [
            Cluster(
                labels=np.array([j for j, label in enumerate(labeling) if label == i], dtype=np.int32)
            )
            for i in range(max(labeling)+1)
        ]
        
        return Clusters(clusters=clusters)
        
    @classmethod
    def from_file(cls, fp: str, logger: Logger = SilentLogger()) -> Clusters:
        '''
        Load a Cluster state from JSON file

        :param fp: File path to .JSON file where Clusters information is stored.
        :type fp: str
        :param logger: Logger to log i/o information.
        :type logger: Logger
        :return: Loaded clusters object.
        :rtype: Clusters
        '''
        
        logger.info(mess=f'Reading clusters from {fp}')
        data = read_json(path=fp)
        
        clusters = [
            Cluster(labels = np.array(
                [obj['label'] for obj in cluster['objects']
            ], dtype=np.int32))
            for cluster in data.values()
        ]
        
        return Clusters(clusters=clusters)
    
    
    # --- MAGIC METHODS ---   

    def __str__    (self)           -> str                 : return f'Clusters[n-clusters: {len(self)}]'
    def __repr__   (self)           -> str                 : return str(self)
    def __len__    (self)           -> int                 : return len (self.clusters)
    def __iter__   (self)           -> Iterable[Cluster]   : return iter(self.clusters)
    def __getitem__(self, idx: int) -> Cluster             : return self.clusters[idx]
    def __bool__   (self)           -> bool                : return len(self) > 0
    
    # --- PROPERTIES ---
    
    @property
    def clusters(self) -> List[Cluster]: return self._clusters
    ''' List of clusters in the collection'''
    
    @property
    def clusters_counts(self) -> Dict[int, int]:
        '''
        Return a dictionary mapping the cluster cardinality
        to the number of clusters with that number of elements

        :return: Cluster cardinality mapping.
        :rtype: Dict[int, int]
        '''
        
        lens = [len(cluster) for cluster in self] # type: ignore
        return dict(Counter(lens))
    
    @property
    def obj_tot_count(self) -> int:
        '''
        Return the total number of element in the cluster collection

        :return: Cluster cardinality mapping.
        :rtype: Dict[int, int]
        '''
        
        return sum([element * count for element, count in self.clusters_counts.items()])
    
    @property
    def labeling(self) -> NDArray[np.int32]:
        '''
        Assigns labels to each object based on the cluster index.

        :return: A 1-dimensional array of integers representing the labels assigned to each object.
        '''
        
        # Array of minus one
        labeling = np.zeros(self.obj_tot_count, dtype=np.int32) - 1

        # Create one dimensional mapping
        for i, cluster in enumerate(self):   # type: ignore
            labeling[cluster.labels] = int(i)

        # Check correct assignment
        assert not np.any(labeling == -1)

        return labeling
    
    @property
    def info(self) -> Dict[str, List[Dict[str, Any]]]:
        '''
        Return information about the clusters to be dumped as a JSON
        '''
        
        return {
            f"CLU_{i}": cluster.info
            for i, cluster in enumerate(self)  # type: ignore
        }
        
    
    # --- UTILITIES ---
    
    def empty(self):
        '''
        Empty the set of clusters
        '''
        
        self._clusters: List[Cluster] = []
        
    def add(self, cluster: Cluster):
        '''
        Add a new cluster to the connection
        '''
        
        self._clusters.append(cluster)
        
    def dump(
        self, 
        out_fp: str, 
        file_name: str = 'Clusters',
        logger: Logger = SilentLogger()
    ):
        '''
        Store cluster information to file as a .JSON file

        :param out_fp: Output file path where to save clustering information
        :type out_fp: str
        :param logger: Logger to log i/o operation. If not given SilentLogger is set.
        :type logger: Logger | None, optional
        '''
        
        fp = os.path.join(out_fp, f'{file_name}.json')
        logger.info(f'Saving clusters info to {fp}')
        save_json(data=self.info, path=fp)
