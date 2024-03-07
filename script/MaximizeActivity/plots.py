from os import path
from typing import Any, Dict, List, Tuple

from matplotlib import pyplot as plt
import numpy as np
from numpy.typing import NDArray
from zdream.logger import Logger, MutedLogger
from zdream.optimizer import Optimizer
from zdream.utils.dataset import MiniImageNet
from zdream.utils.misc import SEM, default
from zdream.utils.plotting import customize_axes_bounds, set_default_matplotlib_params


def plot_scores(
    scores: Tuple[NDArray, NDArray],
    stats:  Tuple[Dict[str, Any], Dict[str, Any]],
    style: Dict[str, Dict[str, str]] = {
        'gen': {'lbl': 'Synthetic', 'col': 'k'},
        'nat': {'lbl':   'Natural', 'col': 'g'}
    },
    num_bins: int  = 25, 
    out_dir: str | None = None,
    display_plots: bool = False,
    logger: Logger | None = None
):
    '''
    Plot two views of scores trend through optimization steps.
    
    1. The first plot displays the score of the best stimulus per optimization step (left) 
       and the average stimuli score pm SEM per iteration (right), for both natural and synthetic images. 

    2. The second plot displays the histograms of scores for both natural and synthetic images.
    
    :param scores: Scores history of synthetic and natural images.
    :type scores: Tuple[NDArray, NDArray]
    :param stats: Collection of statistics for synthetic and natural images through optimization steps.
    :type stats: Tuple[Dict[str, Any], Dict[str, Any]]
    :param style: Style dictionary setting labels and colors of synthetic and natural images.
                    They default to black for synthetic and to green for natural.
    :type style: Dict[str, Dict[str, str]]
    :param num_bins: Number of bins to display in the histogram, defaults to 25.
    :type num_bins: int
    :param out_dir: Directory where to save output plots, default is None indicating not to save.
    :type out_dir: str | None
    :param display_plots: If to display plots, default to False.
    :type out_dir: bool
    :param logger: Logger to log information relative to plot saving paths.
                   Defaults to None indicating no logging.
    :type logger: Logger | None
    '''

    # Preprocessing input
    scores_gen, scores_nat = scores
    stats_gen,  stats_nat  = stats

    logger = default(logger, MutedLogger())

    
    # Retrieve default parameters and retrieve `alpha` parameter
    def_params = set_default_matplotlib_params(shape='rect_wide', l_side = 30)
    
    # PLOT 1. BEST and AVG SCORE TREND
    fig_trend, ax = plt.subplots(1, 2)
    
    # Define label and colors for both generated and natural images
    lbl_gen = style['gen']['lbl']; col_gen = style['gen']['col']
    lbl_nat = style['nat']['lbl']; col_nat = style['nat']['col']

    # We replicate the same reasoning for the two subplots by accessing 
    # the different key of the score dictionary whether referring to max or mean.
    for i, k in enumerate(['best_shist', 'mean_shist']):
        
        # Lineplot of both synthetic and natural scores
        ax[i].plot(stats_gen[k], label=lbl_gen, color=col_gen)
        ax[i].plot(stats_nat[k], label=lbl_nat, color=col_nat)
        
        # When plotting mean values, add SEM shading
        if k =='mean_shist':
            for stat, col in zip([stats_gen, stats_nat], [col_gen, col_nat]):
                ax[i].fill_between(
                    range(len(stat[k])),
                    stat[k] - stat['sem_shist'],
                    stat[k] + stat['sem_shist'], 
                    color=col, alpha=def_params['grid.alpha']
                )
                
        # Names
        ax[i].set_xlabel('Generation cycles')
        ax[i].set_ylabel('Target scores')
        ax[i].set_title(k.split('_')[0].capitalize())
        ax[i].legend()
        customize_axes_bounds(ax[i])
    
    # Save or display  
    if out_dir:
        out_fp = path.join(out_dir, 'scores_trend.png')
        logger.info(f'Saving score trend plot to {out_fp}')
        fig_trend.savefig(out_fp, bbox_inches="tight")
    else:
        plt.show()
    
    # PLOT 2. SCORES HISTOGRAM 
    fig_hist, ax = plt.subplots(1) 
        
    # Compute min and max values
    data_min = min(scores_nat.min(), scores_gen.min())
    data_max = max(scores_nat.max(), scores_gen.max())

    # Create histograms for both synthetic and natural with the same range and bins
    hnat = plt.hist(
        scores_nat.flatten(),
        bins=num_bins,
        range=(data_min, data_max),
        alpha=1, 
        label=lbl_nat,
        density=True,
        edgecolor=col_nat, 
        linewidth=3
    )
    
    hgen = plt.hist(
        scores_gen.flatten(),
        bins=num_bins,
        range=(data_min, data_max),
        density=True,
        color = col_gen,
        edgecolor=col_gen
    )
    
    # For generated images set alpha as a function of the generation step.
    # NOTE: Since alpha influences also edge transparency, 
    #       histogram needs to be separated into two parts for edges and filling
    hgen_edg = plt.hist(
        scores_gen.flatten(), 
        bins=num_bins, 
        range=(data_min, data_max), 
        label= lbl_gen,
        density=True,
        edgecolor=col_gen,
        linewidth=3
    )
    
    # Set transparent columns for natural images and edges of synthetic ones
    for bins in [hnat, hgen_edg]:
        for bin in bins[-1]: # type: ignore
            bin.set_facecolor('none')
    
    # Retrieve number of iterations
    n_gens = scores_gen.shape[0]
    
    # Set alpha value of each column of the hgen histogram.
    # Iterate over each column, taking its upper bound and its histogram bin
    for up_bound, bin in zip(hgen[1][1:], hgen[-1]): # type: ignore
        
        # Compute the probability for each generation of being
        # less than the upper bound of the bin of interest
        is_less = np.mean(scores_gen < up_bound, axis = 1)
        
        # Weight the alpha with the average of these probabilities.
        # Weights are the indexes of the generations. The later the generation, 
        # the higher its weight (i.e. the stronger the shade of black).
        # TODO Is weighting too steep in this way?
        
        alpha_col = np.sum(is_less*range(n_gens)) / np.sum(range(n_gens))
        bin.set_alpha(alpha_col)
        
    # Plot names
    plt.xlabel('Target score')
    plt.ylabel('Prob. density')
    plt.legend()
    customize_axes_bounds(ax)
    
    # Save or display  
    if out_dir:
        out_fp = path.join(out_dir, 'scores_histo.png')
        logger.info(f'Saving score histogram plot to {out_fp}')
        fig_hist.savefig(out_fp, bbox_inches="tight")
    if display_plots:
        plt.show()


def plot_scores_by_cat(
    scores: Tuple[NDArray, NDArray], 
    lbls: List[int], 
    dataset: MiniImageNet,
    k: int = 3, 
    gens_window: int = 5,
    out_dir: str | None = None,
    display_plots: bool = False,
    logger: Logger | None = None
):
    '''
    Plot illustrating the average pm SEM scores of the top-k and bottom-k categories of natural images.
    Moreover it also shows the average pm SEM scores of synthetic images within the first and last
    iteration of a considered generation window.
    
    :param scores: Scores history of synthetic and natural images.
    :type scores: Tuple[NDArray, NDArray]
    :param lbls: List of the labels seen during optimization.
    :type lbls: List[int]
    :param dataset: Dataset of natural images allowing for id to category mapping.
    :type dataset: MiniImageNet
    :param k: Number of natural images classes to consider for the top-k and bottom-k.
              Default is 3
    :type k: int
    :param gens_window: Generations window to consider scores at the beginning and end 
                        of the optimization. Default is 5.
    :type n_gens_considered: int
    :param out_dir: Directory where to save output plots, default is None indicating not to save.
    :type out_dir: str | None
    :param display_plots: If to display plots, default to False.
    :type out_dir: bool
    :param logger: Logger to log information relative to plot saving paths.
                   Defaults to None indicating no logging.
    :type logger: Logger | None
    '''

    # Preprocessing input
    scores_gen, scores_nat = scores 

    logger = default(logger, MutedLogger())
    
    # Cast scores and labels as arrays.
    # NOTE: `nat_scores` are flattened to be more easily 
    #        indexed by the `nat_lbls` vector
    gen_scores = scores_gen
    nat_scores = scores_nat.flatten()
    
    # Convert class indexes to labels
    class_to_lbl = np.vectorize(lambda x: dataset.class_to_lbl(lbl=x))
    nat_lbls = class_to_lbl(lbls)
    
    # Get the unique labels present in the dataset
    unique_lbls, _ = np.unique(nat_lbls, return_counts=True)
    
    # Save score statistics of interest (mean, SEM and max) for each of the labels
    lbl_acts = {}
    for lb in unique_lbls:
        lb_scores = nat_scores[np.where(nat_lbls == lb)[0]]
        lbl_acts[lb] = (np.mean(lb_scores), SEM(lb_scores), np.amax(lb_scores))
    
    # Sort scores by their mean
    # NOTE: x[1][0] first takes values of the dictionary 
    #       and then uses the mean as criterion for sorting
    best_labels = sorted(lbl_acts.items(), key=lambda x: x[1][0])
    
    # Extracting top-k and bottom-k categories
    # NOTE: Scores are in ascending order    
    top_categories = best_labels[-k:]
    bot_categories = best_labels[:k]
    
    # Unpacking top and bottom categories for plotting
    top_labels, top_values = zip(*top_categories)
    bot_labels, bot_values = zip(*bot_categories)
    
    # Define the mean and standard deviation of early and late generations
    gen_dict = {
        'Early': (
            np.mean(gen_scores[:gens_window,:]), 
            SEM    (gen_scores[:gens_window,:].flatten())
        ),
        'Late': (
            np.mean(gen_scores[-gens_window:,:]), 
            SEM    (gen_scores[-gens_window:,:].flatten())
        )}
    
    # Plot using default configurations
    set_default_matplotlib_params(shape='rect_wide', l_side = 30)
    fig, ax = plt.subplots(2, 1)
    
    # Plot averages pm SEM of the top-p and worst-k natural images and of early 
    # and late generation windows.
    ax[0].barh(
        top_labels, 
        [val[0] for val in top_values], 
        xerr=[val[1] for val in top_values], 
        label='Top 3', 
        color='green'
    )
    ax[0].barh(
        bot_labels, 
        [val[0] for val in bot_values], 
        xerr=[val[1] for val in bot_values], 
        label='Bottom 3', 
        color='red'
    )
    ax[0].barh(
        list(gen_dict.keys()),
        [v[0] for v in gen_dict.values()],
        xerr=[v[1] for v in gen_dict.values()],
        label='Synthetic',
        color='black'
    )

    # Labels
    ax[0].set_xlabel('Average activation')
    ax[0].legend()
    customize_axes_bounds(ax[0])
    
    # Replicate the same reasoning sorting by the best score
    sorted_lblA_bymax = sorted(lbl_acts.items(), key=lambda x: x[1][2]) # We sort for the 2 index, i.e. the max
    
    # Best and worst categories
    top_categories = sorted_lblA_bymax[-k:]
    bot_categories = sorted_lblA_bymax[:k]
    
    # Unpack labels and values
    top_labels, top_values = zip(*top_categories)
    bot_labels, bot_values = zip(*bot_categories)
    
    # Plot
    ax[1].barh(top_labels, [val[2] for val in top_values], label='Top 3',    color='green')
    ax[1].barh(bot_labels, [val[2] for val in bot_values], label='Bottom 3', color='red')
    customize_axes_bounds(ax[1])
    
    # Save
    if out_dir:
        out_fp = path.join(out_dir, 'scores_labels.png')
        logger.info(f'Saving score labels plot to {out_fp}')
        fig.savefig(out_fp, bbox_inches="tight")
    if display_plots:
        plt.show()

#