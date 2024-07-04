from experiment.utils.args import Args
from experiment.ClusterOptimization.args import ARGS
from experiment.ClusterOptimization.cluster_optimization import ClusteringOptimizationExperiment, UnitsWeightingMultiExperiment


if __name__ == '__main__':
    
    parser = Args.get_parser(args=ARGS, multirun=True)
    args   = vars(parser.parse_args())

    mrun_experiment = UnitsWeightingMultiExperiment.from_args(
        args=args, 
        exp_type=ClusteringOptimizationExperiment
    )

    mrun_experiment.run()