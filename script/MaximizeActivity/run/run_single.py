"""
TODO Experiment description
"""

from os import path
import matplotlib

from script.MaximizeActivity.maximize_activity import MaximizeActivityExperiment
from script.MaximizeActivity.parser import get_parser
from zdream.utils.io_ import read_json
from zdream.utils.misc import overwrite_dict
from zdream.utils.model import DisplayScreen

matplotlib.use('TKAgg')

# NOTE: Script directory path refers to the current script file
SCRIPT_DIR     = path.abspath(path.join(__file__, '..', '..', '..'))
LOCAL_SETTINGS = path.join(SCRIPT_DIR, 'local_settings.json')

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
    
    experiment = MaximizeActivityExperiment.from_config(full_conf)
    experiment.run()


if __name__ == '__main__':

    parser = get_parser()
    
    conf = vars(parser.parse_args())
    
    main(conf)
