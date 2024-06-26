
import random
from typing import List, Tuple

import numpy as np

from zdream.utils.misc import copy_exec

def generate_log_numbers(N, M): return list(sorted(list(set([int(a) for a in np.logspace(0, np.log10(M), N)]))))

NAME = 'neuron_scaling_alexnetfc7_50points'

ITER        = 200
SAMPLE      = 10

# Neurons Scaling
LAYER       = 19
MAX_NEURONS = 1000
N_POINTS    = 50
NEURONS     = generate_log_numbers(N_POINTS, MAX_NEURONS)

# Layer Correlation
LAYERS         = [16,     20,   21]
LAYERS_NEURONS = [4096, 4096, 1000]
N_POINTS_      = 2

def neuron_scaling_args(layer: int, neurons: List[int], sample: int) -> Tuple[str, str, str]:

    args = [
        ( f'{layer}={neuron}r[]', f'{layer}=[]', str(random.randint(1000, 1000000)) )
        for neuron in neurons for _ in range(sample)]
    
    rec_layer_str = '#'.join(a for a, _, _ in args)
    scr_layer_str = '#'.join(a for _, a, _ in args)
    rand_seed_str = '#'.join(a for _, _, a in args)
    
    return rec_layer_str, scr_layer_str, rand_seed_str

def layers_correlation_arg(layers: List[int], neuron_len: List[int], n_points: int,  sample: int) -> Tuple[str, str, str]:

    rec_layers_str = ','.join([f'{layer}=[]' for layer in layers])
    
    args = [
        ( f'{layer}={neuron}r[]', str(random.randint(1000, 1000000)) )
        for layer, neu_len in zip(layers, neuron_len) 
        for neuron in generate_log_numbers(n_points, neu_len)
        for _ in range(sample)]
    
    scr_layers_str = '#'.join(a for a, _ in args)
    rand_seed_str  = '#'.join(a for _, a in args)
    
    return rec_layers_str, scr_layers_str, rand_seed_str


if __name__ == '__main__':

    print('Multiple run: ')
    print('[1] Neural scaling')
    print('[2] Layers correlation')
    
    option = int(input('Choose option: '))
    
    match option:
        
        case 1:
            
            rec_layer_str, scr_layer_str, rnd_seed_str = neuron_scaling_args(layer=LAYER, neurons=NEURONS, sample=SAMPLE)
            
            args = {
                'rec_layers'  : rec_layer_str,
                'scr_layers'  : scr_layer_str,
                'random_seed' : rnd_seed_str,
            }
            
            file = 'run_multiple_neuronal_scaling.py'
            
        case 2:
            
            rec_layer_str, scr_layer_str, rnd_seed_str = layers_correlation_arg(
                layers=LAYERS,      neuron_len=LAYERS_NEURONS,
                n_points=N_POINTS_, sample=SAMPLE
            )
            
            args = {
                'rec_layers'  : rec_layer_str,
                'scr_layers'  : scr_layer_str,
                'random_seed' : rnd_seed_str,
            }
            
            file = 'run_multiple_layer_correlation.py'
            
        case _:
            
            print('Invalid option')
            
    args['name'] = NAME
    args['iter'] = ITER
    args['template'] = 'T'

    copy_exec(file=file, args=args)
