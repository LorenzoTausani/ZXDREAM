'''
This script allows the user to select the superclass for each output unit of the ImageNet dataset.
The superclass is selected from a list of 50 predefined superclasses.
The superclass labeling is intended to be used as a ground truth labeling for the ImageNet dataset.
'''

import os

import numpy as np
from analysis.utils.misc import load_wordnet
from analysis.utils.settings import ALEXNET_DIR, LAYER_SETTINGS, WORDNET_DIR
from analysis.utils.wordnet import ImageNetWords, WordNet

from experiment.utils.settings import FILE_NAMES
from pxdream.clustering.cluster import Clusters
from pxdream.utils.io_ import save_json
from pxdream.utils.logger import LoguruLogger

# ------------------------------------------- SETTINGS ---------------------------------------

LAYER = 'fc8'

SUPER_LABELS = [
    'mollusk, mollusc, shellfish',
    'arthropod',
    'invertebrate',
    'plant, flora, plant life',
    'fish',
    'bird',
    'amphibian',
    'reptile, reptilian',
    'aquatic mammal',
    'dog, domestic dog, Canis familiaris',
    'canine, canid',
    'cat, true cat',
    'feline, felid',
    'carnivore(2)',
    'rodent, gnawer',
    'primate',
    'mammal, mammalian',
    'clothing, article of clothing, vesture, wear, wearable, habiliment',
    'machine',
    'musical instrument, instrument',
    'ship',
    'wheeled vehicle',
    'aircraft',
    'structure, construction',
    'measuring instrument, measuring system, measuring device',
    'container',
    'weapon, arm, weapon system',
    'sports equipment',
    'implement',
    'covering(2)',
    'furnishing(2)',
    'piece of cloth, piece of material',
    'instrument',
    'restraint, constraint',
    'public transport',
    'electronic equipment',
    'toiletry, toilet articles',
    'vessel, watercraft',
    'mechanical device',
    'game equipment',
    'home appliance, household appliance',
    'device',
    'equipment',
    'instrumentality, instrumentation',
    'artifact, artefact',
    'dish(2)',
    'bread, breadstuff, staff of life',
    'vegetable, veggie, veg',
    'fruit(2)',
    'food, nutrient',
    'geological formation, formation',
    'fungus',
    'person, individual, someone, somebody, mortal, soul',
    'abstraction, abstract entity'
]

# ---------------------------------------------------------------------------------------------

if __name__ == '__main__':
    
    # Initialize logger
    logger = LoguruLogger(to_file=False)
    
    # WordNet paths
    wordnet = load_wordnet(logger)

    # Load ImageNet
    logger.info(msg='Loading ImageNet')
    inet_fp = os.path.join(WORDNET_DIR, FILE_NAMES['imagenet'])
    inet    = ImageNetWords(imagenet_fp=inet_fp, wordnet=wordnet)

    # Save superclasses for each output unit
    out = {}

    for word in inet:  # type: ignore
        
        logger.info(msg='')
        logger.info(msg=f"Step {word.id} - {word.name}")
        
        # Compute all word ancestors
        ancestors = [wordnet[a] for a in word.ancestors_codes]  # type: ignore
        ancestors = sorted(ancestors, key=lambda word: word.depth, reverse=True)
        
        # A) Check if the ancestors are superclasses list
        found = False
        
        for a in ancestors:
            if a.name in SUPER_LABELS:
                logger.info(f'> Automatically selected class: {a.name}')
                out[word.id] = [a.code, a.name]
                found = True
                break
        
        # If the class is found, go to the next one
        if found: continue
        
        # B) Ask the user to select one
        
        logger.info(msg='No class found. Please select one from the list below:')
        for j, a in enumerate(ancestors): logger.info(msg=f'> {j}. {a.name}')
        k = int(input('Enter the number of the class: '))
        chosen_class = ancestors[k]
        out[word.id] = [chosen_class.code, chosen_class.name]
        logger.info(msg=f'Chosen class: {chosen_class}')
    
    # Log the total number of superclasses used
    logger.info(msg='')
    selected_classes = set([code for code, _ in out.values()])
    logger.info(msg=f"TOTAL CLASSES: {len(selected_classes)}")
    
    # Save superclasses to file
    superclass_fp = os.path.join(WORDNET_DIR, FILE_NAMES['imagenet_super'])
    logger.info(msg=f'Saving superclasses to {superclass_fp}')
    save_json(out, superclass_fp)
    logger.info(msg='')
    
    # Save cluster
    class_mapping = {code: i for i, code in enumerate(selected_classes)}
    labeling = np.array([class_mapping[code] for code, _ in out.values()])
    
    clusters = Clusters.from_labeling(labeling)
    setattr(clusters, "NAME", "True")
    out_fp = os.path.join(ALEXNET_DIR, LAYER_SETTINGS[LAYER]['directory'])  # type: ignore
    clusters.dump(out_fp=out_fp, logger=logger)
    
    logger.close()


