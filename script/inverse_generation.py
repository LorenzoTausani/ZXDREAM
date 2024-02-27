from argparse import ArgumentParser
from argparse import BooleanOptionalAction
import os
from os import path
import numpy as np
import torch
from PIL import Image
from einops import rearrange
from torchvision.utils import make_grid
from torchvision.transforms.functional import to_pil_image
from typing import Any, Dict, cast, Tuple

from zdream.generator import InverseAlexGenerator
from zdream.utils.model import Message
from zdream.subject import NetworkSubject
from zdream.utils import read_json, device, default
from zdream.probe import RecordingProbe


def main(args):
    
    network_name    = args.net_name
    layer_name      = args.layer
    img_size        = args.img_size
    network_variant = args.gen_variant
    image_path      = args.test_img
    weights_path    = args.gen_root
    out_dir         = args.save_dir
    
    # Probe to register all activations
    rec_probe = RecordingProbe(target = {layer_name: None})
    
    # Create network subject
    net_sbj = NetworkSubject(network_name=network_name, record_probe=rec_probe)

    # Load test images
    img = np.asarray(Image.open(image_path).convert("RGB").resize(img_size)) / 255    
    img = torch.tensor(rearrange(img, 'h w c -> 1 c h w'))
    img = img.to(device)

    # Load generator with specified variant
    generator = InverseAlexGenerator(root=weights_path, variant=network_variant)
    generator.to(device=device)
    generator.eval()

    # Compute activations
    message = Message(mask=np.ones(img.shape[0], dtype=bool))
    activations, _ = net_sbj((img, message))
    activation = activations[layer_name]
    
    activation = activation.reshape(1, *generator.input_dim)
    synthetic_images, _ = generator(activation)

    # Save images
    out_dir = path.join(out_dir, 'inverse_generation')
    os.makedirs(out_dir, exist_ok=True)

    image_name = path.splitext(path.basename(image_path))[0]
        
    out_image = make_grid([img[0], synthetic_images.cpu()[0]], nrow=2)
    out_image = cast(Image.Image, to_pil_image(out_image))
        
    fp = path.join(out_dir, f'{image_name}-{network_variant}-{layer_name}.png')
    out_image.save(fp)
    
    Image.open(fp).show()

valid_config = [
    ('06_conv2d_03', 'conv3'),
    ('06_conv2d_03', 'conv4'),
    ('07_relu_03', 'conv3'),
    ('07_relu_03', 'conv4'),
    ('12_maxpool2d_03', 'pool5'),
    ('13_adaptiveavgpool2d_01', 'pool5'),
    ('15_linear_01', 'fc6'),
    ('15_linear_01', 'fc7'),
    ('16_relu_06', 'fc6'),
    ('16_relu_06', 'fc7'),
    ('17_dropout_02', 'fc6'),
    ('17_dropout_02', 'fc7'),
    ('18_linear_02', 'fc6'),
    ('18_linear_02', 'fc7'),
    ('19_relu_07', 'fc6'),
    ('19_relu_07', 'fc7'),
    ('20_linear_03', 'fc8')
]

if __name__ == "__main__":
    
    # Loading `local_settings.json` for custom local settings
    local_folder = path.dirname(path.abspath(__file__))
    script_settings_fp = path.join(local_folder, 'local_settings.json')
    script_settings: Dict[str, Any] = read_json(path=script_settings_fp)
    
    test_image = script_settings['test_image']
    gen_root   = script_settings['inverse_alex_net']
    image_out  = script_settings['image_out']
    
    parser = ArgumentParser()
        
    parser.add_argument('-net_name',    type=str,   default='alexnet',      help='Name of the network')    
    parser.add_argument('-layer',       type=str,   default='20_linear_03',          help='Activations layer name')
    parser.add_argument('-img_size',    type=tuple, default=(256, 256),     help='Size of a given image', nargs=2)
    parser.add_argument('-gen_variant', type=str,   default='fc8', help='Variant of InverseAlexGenerator to use')
    parser.add_argument('-gen_root',    type=str,   default=gen_root,       help='Path to root folder of generator checkpoints')
    parser.add_argument('-test_img',    type=str,   default=test_image,     help='Path to test image')
    parser.add_argument('-save_dir',    type=str,   default=image_out,      help='Path to store synthetic image')
    
    # If to evaluate all possible combinations
    parser.add_argument('--all', action=BooleanOptionalAction,  help='If yo evaluate all possible layer-variant configuration')
    
    args = parser.parse_args()
    args.all = default(args.all, False)
    
    if not args.all:
    
        if (args.layer, args.gen_variant) not in valid_config:
            raise ValueError (f"No valid configuration ({args.layer}, {args.gen_variant})")

        main(args=args)
    
    else:
        
        for layer, variant in valid_config:
            args.layer = layer
            args.gen_variant = variant
            
            main(args=args)