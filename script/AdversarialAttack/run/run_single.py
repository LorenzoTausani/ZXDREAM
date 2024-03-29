"""
TODO Experiment description
"""

import matplotlib
from os import path

from zdream.utils.io_ import read_json
from zdream.utils.misc import overwrite_dict
from zdream.utils.model import DisplayScreen
from script.AdversarialAttack.parser import get_parser
from script.AdversarialAttack.adversarial_attack import AdversarialAttackExperiment

matplotlib.use('TKAgg')

def main(args): 
    
    # Experiment

    json_conf = read_json(args['config'])
    args_conf = {k : v for k, v in args.items() if v}
    
    full_conf = overwrite_dict(json_conf, args_conf) 
    
    # Hold main display screen reference
    if full_conf['render']:
        main_screen = DisplayScreen.set_main_screen()

    # Add close screen flag on as the experiment
    # only involves one run
    full_conf['close_screen'] = True
    
    experiment = AdversarialAttackExperiment.from_config(full_conf)
    experiment.run()


if __name__ == '__main__':

    parser = get_parser()
    
    conf = vars(parser.parse_args())
    
    main(conf)
