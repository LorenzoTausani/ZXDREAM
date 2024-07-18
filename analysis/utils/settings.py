
import os
from typing import Dict

from zdream.utils.io_ import read_json

# --- LOCAL DIRECTORIES ---

SETTINGS_FILE = os.path.abspath(os.path.join(__file__, '..', '..', 'local_settings.json'))
settings      = read_json(SETTINGS_FILE)

OUT_DIR             : str = settings['out_dir']
WORDNET_DIR         : str = settings['wordnet_dir']
CLUSTER_DIR         : str = settings['cluster_dir']
NEURON_SCALING_FILE : str = settings['neuron_scaling_file']
NEURON_SCALING_FUN  : str = settings['neuron_scaling_functions']


# --- LAYER SETTINGS ---

LAYER_SETTINGS = {
    'fc8': {
        'directory'          : 'fc8',
        'format_name'        : 'alexnetfc8',
        'has_labels'         : True,
        'number_of_clusters' : 50,
        'feature_map'        : False,
        'neurons'            : 1000,
    },
    'fc7-relu': {
        'directory'          : 'fc7-relu',
        'format_name'        : 'alexnetfc7relu',
        'has_labels'         : False,
        'number_of_clusters' : 127,
        'feature_map'        : False,
        'neurons'            : 4096,
    },
    'fc6-relu': {
        'directory'          : 'fc6-relu',
        'format_name'        : 'alexnetfc6relu',
        'has_labels'         : False,
        'number_of_clusters' : 94,
        'feature_map'        : False,
        'neurons'            : 4096,
    },
    'conv5-maxpool': {
        'directory'          : 'conv5-maxpool',
        'format_name'        : 'alexnetconv5maxpool',
        'has_labels'         : False,
        'number_of_clusters' : 576,
        'feature_map'        : True,
        'neurons'            : 9216
    },
}


# --- CLUSTER ORDER ---

CLU_ORDER = {
    'DominantSet'     : 0,
    'NormalizedCut'   : 1,
    'GaussianMixture' : 2,
    'DBSCAN'          : 3,
    'DBSCANDimTarget' : 3.1,
    'DBSCANSilhouette': 3.2,
    'Adjacent'        : 4,
    'FeatureMap'      : 5,
    'Random'          : 6,
    'True'            : 7,
}