import os
import torch
import warnings
import numpy as np
import torch.nn as nn
from torch import Tensor
from pathlib import Path
from einops.layers.torch import Rearrange
from abc import abstractmethod
from PIL import Image
from torch.utils.data import DataLoader
from zdream.utils import device
# from diffusers.models.unets.unet_2d import UNet2DModel

from torch.optim import AdamW

from tqdm.auto import trange

from functools import partial
from collections import OrderedDict

from typing import Iterable, List, Dict, cast, Callable, Tuple
from numpy.typing import NDArray

from .utils import exists
from .utils import default
from .utils import lazydefault
from .utils import multichar_split
from .utils import multioption_prompt

from .utils import Stimuli
from .utils import Message


class Generator(nn.Module):
    '''
    Base class for generic generators. A generator
    implements its generative logic in the `_forward`
    method that converts latent codes (i.e. parameters 
    from optimizers) into images.
    
    A Generator allows to interleave synthetic images
    with natural images by the specification of a mask.

    Generator are also responsible for tracking the
    history of generated images.
    '''

    def __init__(
        self,
        name : str,
        output_pipe : Callable[[Tensor], Tensor] | None = None,
        nat_img_loader: DataLoader | None = None,
    ) -> None:
        '''
        Create a new instance of a generator

        :param name: _description_
        :type name: str
        :param output_pipe: Pipeline of postprocessing operation to be applied to 
                            raw generated images.
        :type output_pipe: Callable[[Tensor], Tensor] | None, optional
        :param nat_img_loader: Dataloader for natural images to be interleaved with synthetic ones.
                                In the case it is not specified at time of initialization if can be
                                set or changed with a proper setter method.
        :type nat_img_loader: DataLoader | None, optional
        '''
        
        super().__init__()
        
        self.name = name

        # Underlying torch module that generates images
        self._network = None

        # List for tracking image history
        self._im_hist : List[Image.Image] = []
        
        self._output_pipe = default(output_pipe, cast(Callable[[Tensor], Tensor], lambda x : x))
        
        # Settings dataloader
        self.set_nat_img_loader(nat_img_loader=nat_img_loader)

    def set_nat_img_loader(self, nat_img_loader : DataLoader | None) -> None:
        '''
        Set a new data loader for natural images. 
        It will also instantiate a new iterator.

        :param data_loader: Data loader for natural images.
        :type data_loader: DataLoader | None
        '''
        
        # When no dataloader is set both variables takes None value
        self._nat_img_loader = nat_img_loader
        self._nat_img_iter   = iter(self._nat_img_loader) if self._nat_img_loader else None

    def find_code(
        self,
        target : Tensor,
        num_iter : int = 500,
        rel_tol : float = 1e-1,
    ) -> Tuple[Tensor, Tuple[Tensor, Tensor]]:
        '''
        '''
        assert self._network, 'Unspecified underlying network model'
        self._network = cast(nn.Module, self._network)

        b, c, h, w = target.shape

        loss = nn.MSELoss()
        code = torch.zeros(b, *self.input_dim, device=self.device, requires_grad=True)

        optim = AdamW(
            [code],
            lr=1e-3,
        )

        epoch = 0
        found_solution = False
        progress = trange(num_iter, desc='Code retrieval | avg. err: --- | rel. err: --- |')
        while not found_solution and (epoch := epoch + 1) < num_iter:
            optim.zero_grad()

            # Generate a novel set of images from the current
            # set of latent codes
            imgs = self._network(code)
            imgs = self._output_pipe(imgs)

            errs : Tensor = loss(imgs, target)
            errs.backward()

            optim.step()

            a_errs = errs.mean()
            r_errs = a_errs / imgs.mean()
            p_desc = f'Code retrieval | avg. err: {a_errs:.2f} | rel. err: {r_errs:.4f}'
            progress.set_description(p_desc)
            progress.update()

            if torch.all(errs / imgs.mean() < rel_tol):
                found_solution = True
        
        progress.close()

        if not found_solution:
            warnings.warn(
                'Cannot find codes within specified relative tolerance'
            )


        return code, (imgs.detach(), errs)

    @abstractmethod
    def load(self, path : str | Path) -> None:
        '''
        '''
        pass
    
    def _masking_sanity_check(
        self, 
        mask : List[bool] | None, 
        num_gen_img : int
    ) -> List[bool]:
        '''
        The method is an auxiliary routine for the forward method
        responsible for checking consistency of the masking for 
        synthetic and natural images, possibly raising errors.

        :param mask: Binary mask specifying the order of synthetic and natural images
                        in the stimuli (True for synthetic, False for natural).
        :type mask: List[bool] | None
        :param num_gen_img: Number of synthetic images.
        :type num_gen_img: int
        :return: Sanitized binary mask.
        :rtype: List[bool]
        '''
        
        # In the case the mask contains only True values no 
        # natural image is expected. This condition should be
        # activated by no specifying a mask at all.
        # In the case the mask length is coherent with the number of
        # synthetic images we reset default condition, that is the mask to be None,
        # otherwise we raise an error.
        if mask and all(mask):
            if len(mask) == num_gen_img: 
                mask = None # default condition
            else:
                err_msg = f'{num_gen_img} images were generated, but {len(mask)} were indicated in the mask'
                raise ValueError(err_msg)
        
        # If natural images are expected but no dataloader is 
        # available we raise an error
        if mask and self._nat_img_loader is None:
            err_msg =   'Mask for natural images were provided but no dataloader is available. '\
                        'Use `set_nat_img_loader()` to set one.'
            raise AssertionError(err_msg)
    
        # If the mixing mask was not specified we set the trivial one.
        # mask = default(mask, [True] * b) -> better, but not for type checker :(
        if not mask: mask = [True] * num_gen_img
        
        # If the number of True values in the mask doesn't match 
        # the number of synthetic images we raise a error.
        if sum(mask) != num_gen_img:
            err_msg = f'Mask expects {num_gen_img} True values, but {sum(mask)} were provided'
            raise ValueError(err_msg)
            
        return mask
    
    def _load_natural_images(self, 
            num_nat_img: int, 
            gen_img_shape: Tuple[int, ...]
        ) -> Stimuli:
        '''
        The method is an auxiliary routine for the forward method
        responsible for loading a specified number of natural 
        images from the dataloader.

        :param num_nat_img: Number of natural images to load. 
                            It also allow for zero natural images to be loaded
                            resulting in an empty set of stimuli.
        :type num_nat_img: int
        :param gen_img_shape: Shape of synthetic images used to ensure size consistency
                                for generated and natural images.
        :type gen_img_shape: Tuple[int, ...]
        :return: Loaded natural images stimuli.
        :rtype: Stimuli
        '''
        
        if num_nat_img > 0:
            
            # NOTE: At this point of the execution flow the dataloader in ensured
            #       to be not None after sanitization checks. The extra check 
            #       is made for the type checker.
            if not self._nat_img_loader or not self._nat_img_iter:
                err_msg = 'No available data loader for natural images'
                raise ValueError(err_msg)

            # List were to save batches of images
            nat_img_list : List[Tensor] = []
            
            # We create a new iterator on the fly to check shape consistency
            # between synthetic and natural images, we raise an error if they disagree.
            nat_img_shape = next(iter(self._nat_img_loader)).shape[1:]
            if nat_img_shape != gen_img_shape:
                err_msg = f'Natural images have shape {nat_img_shape}, '\
                          f'but synthetic ones have shape {gen_img_shape}.'
                raise ValueError(err_msg)
            
            # We continue extracting batches of natural images
            # until the required number
            batch_size = cast(int, self._nat_img_loader.batch_size)
            while len(nat_img_list) * batch_size < num_nat_img:
                try:
                    image_batch = next(self._nat_img_iter)
                    nat_img_list.append(image_batch)
                except StopIteration:
                    # Circular iterator: when all images are loaded, we start back again.
                    self.set_nat_img_loader(nat_img_loader=self._nat_img_loader)
                    
            # We combine the extracted batches in a single tensor
            # NOTE: Since we necessary extract images in batches,
            #       we can have extracted more than required, for this purpose
            #       we may need to chop out the last few to match required number
            nat_img = torch.cat(nat_img_list)[:num_nat_img]
        
        # In the case of no natural images we create an empty stimuli
        else:
            nat_img = torch.empty((0,) + gen_img_shape, device=self.device)
            
        return nat_img

    def forward(
        self, 
        codes: Tensor | NDArray,
        mask : List[bool] | None = None
    ) -> Tuple[Stimuli, Message]:
        '''
        Produce the stimuli using latent image codes, along with some
        auxiliary information in the form of a message.
        The method of the possibility to specify a mask for interleaving 
        synthetic images with natural ones.

        :param codes: Latent images code for synthetic images generation.
        :type codes: Tensor | NDArray
        :param mask: Binary mask specifying the order of synthetic and natural images
                        in the stimuli (True for synthetic, False for natural).
        :type mask: List[bool] | None, optional
        :return: Produced stimuli set and auxiliary information in the form of a message.
        :rtype: Tuple[Stimuli, Message]
        '''
        
        # Extract the number of codes from batch size
        num_gen_img, *_ = codes.shape

        # Mask sanity check
        mask = self._masking_sanity_check(mask=mask, num_gen_img=num_gen_img)
    
        # Get synthetic images form the _forward method
        # which is specific for each subclass architecture
        gen_img, message = self._forward(codes=codes)
    
        # We use a tensor version of the mask for the interleaving 
        mask_ten = torch.tensor(mask)
        num_gen_img = int(torch.sum( mask_ten).item())
        num_nat_img = int(torch.sum(~mask_ten).item())
        
        # Extract synthetic images shape
        _, *gen_img_shape = gen_img.shape
        gen_img_shape = tuple(gen_img_shape)
        
        # Load natural images
        nat_img = self._load_natural_images(num_nat_img=num_nat_img, gen_img_shape=gen_img_shape)
        
        # Interleave synthetic and generated according to the mask
        out = torch.empty( ((num_nat_img + num_gen_img),) + gen_img_shape, device=self.device)
        out[ mask_ten] = gen_img
        out[~mask_ten] = nat_img
        
        # Attach information to the message
        message.mask = np.array(mask)
        
        return out, message
    
    @torch.no_grad()
    @abstractmethod 
    def _forward(
        self, 
        codes : Tensor | NDArray
    ) -> Tuple[Stimuli, Message]:
        '''
        The abstract method will be implemented in each 
        subclass that need to specify the architecture logic of 
        image generation from a latent code.

        :param codes: Latent images code for synthetic images generation.
        :type codes: Tensor | NDArray
        :return: Generated stimuli set and auxiliary information in the form of a message.
        :rtype: Tuple[Stimuli, Message]
        '''
        pass

    @property
    def device(self):
        return next(self.parameters()).device
    
    @property
    def dtype(self) -> torch.dtype:
        return next(self.parameters()).dtype

    @property
    @abstractmethod
    def input_dim(self) -> Tuple[int, ...]:
        pass

# TODO: This is @Lorenzo's job!
class InverseAlexGenerator(Generator):

    def __init__(
        self,
        root : str,
        variant : str | None = 'fc8',
        output_pipe : Callable[[Tensor], Tensor] | None = None,
        nat_img_loader : DataLoader | None = None,
    ) -> None:
        super().__init__(
            name='inv_alexnet',
            output_pipe=output_pipe,
            nat_img_loader=nat_img_loader
        )
        
        # Get the networks paths based on provided root folder
        nets_path = self._get_net_paths(base_nets_dir=root)

        # If variant is not provided at initialization, we ask the experimenter
        # for generator variant of choice (from option list).
        user_in = cast(
                Callable[[], str],
                partial(
                    multioption_prompt,
                    opt_list=list(nets_path.keys()),
                    in_prompt='select your generator:',
                )
            )
        self.variant = lazydefault(variant, user_in)
        
        # Build the network layers based on provided generator variant
        self._network = self._build(self.variant)
        
        # Load the corresponding checkpoint
        self.load(nets_path[self.variant])

        # Put the generator in evaluate mode by default
        self.eval()

    def load(self, path : str | Path) -> None:
        '''
        Load generator neural networks weights from file.

        Args:
        - path (str): Path to the network weights.
        '''
        
        self._network.load_state_dict(
            torch.load(path, map_location=device)
        )
        
    @torch.no_grad()
    def _forward(
        self, 
        codes : Tensor | NDArray
    ) -> Tuple[Stimuli, Message]:
        '''
        Generated synthetic images starting with their latent code

        :param codes: Latent images code for synthetic images generation.
        :type codes: Tensor | NDArray
        :return: Generated stimuli set and auxiliary information in the form of a message.
        :rtype: Tuple[Stimuli, Message]
        '''
        
        # Convert codes to tensors in the case of Arrays
        if isinstance(codes, np.ndarray):
            codes = torch.from_numpy(codes).to(self.device).to(self.dtype)
            
        # Generate the synthetic images and apply the output pipe
        gens = self._network(codes)
        gens = self._output_pipe(gens)

        # TODO: @Lorenzo Why this scaling here?
        # TODO: @Paolo Kreimann does it in his code. I don't know why this is
        if self.type_net in ['conv','norm']:
            gens *= 255
            
        # Generate message
        # NOTE: The information regarding it's in practice useless as it
        #       will be overloaded in the forward method.
        # NOTE: At this moment it's trivial but it offers the possibility
        #       to attach auxiliary information in the future.
        message = Message(mask=np.array([True]*gens.shape[0])) 

        return gens, message

    @property
    def input_dim(self) -> Tuple[int, ...]:
        match self.variant:
            case 'fc8':   return (1000,)
            case 'fc7':   return (4096,)
            case 'fc6':   return (4096,)
            case 'conv3': return (384, 13, 13)
            case 'conv4': return (384, 13, 13)
            case 'norm1': return (96, 27, 27)
            case 'norm2': return (256, 13, 13)
            case 'pool5': return (256, 6, 6)
            case _: raise ValueError(f'Unsupported variant {self.variant}')

    @property
    def output_dim(self) -> Tuple[int, int, int]:
        match self.variant:
            case 'norm1': return (3, 240, 240) # TODO this makes the test fail
            case 'norm2': return (3, 240, 240) # TODO this makes the test fail
            case _: return (3, 256, 256)

    def _build(self, variant : str = 'fc8') -> nn.Module:
        # Get type of network (i.e: norm, conv, pool, fc)
        self.type_net = multichar_split(variant)[0][:-1]

        match variant:
            case 'fc8': num_inputs = 1000
            case 'fc7': num_inputs = 4096
            case 'fc6': num_inputs = 4096
            case 'norm1': inp_par = ( 96, 128, 3, 2)
            case 'norm2': inp_par = (256, 256, 3, 1)
            case _: pass
            
        templates = {
            'fc'   : lambda : nn.Sequential(OrderedDict([
                    ('fc7',       nn.Linear(num_inputs, 4096)),
                    ('lrelu01',   nn.LeakyReLU(negative_slope=0.3)),
                    ('fc6',       nn.Linear(4096, 4096)),
                    ('lrelu02',   nn.LeakyReLU(negative_slope=0.3)),
                    ('fc5',       nn.Linear(4096, 4096)),
                    ('lrelu03',   nn.LeakyReLU(negative_slope=0.3)),
                    ('rearrange', Rearrange('b (c h w) -> b c h w', c=256, h=4, w=4)),
                    ('tconv5_0',  nn.ConvTranspose2d(256, 256, 4, stride=2, padding=1, bias=False)),
                    ('lrelu04',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv5_1',  nn.ConvTranspose2d(256, 512, 3, stride=1, padding=1, bias=False)),
                    ('lrelu05',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_0',  nn.ConvTranspose2d(512, 256, 4, stride=2, padding=1, bias=False)),
                    ('lrelu06',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_1',  nn.ConvTranspose2d(256, 256, 3, stride=1, padding=1, bias=False)), 
                    ('lrelu07',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_0',  nn.ConvTranspose2d(256, 128, 4, stride=2, padding=1, bias=False)),
                    ('lrelu08',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_1',  nn.ConvTranspose2d(128, 128, 3, stride=1, padding=1, bias=False)),
                    ('lrelu09',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv2',    nn.ConvTranspose2d(128, 64, 4, stride=2, padding=1, bias=False)),
                    ('lrelu10',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv1',    nn.ConvTranspose2d(64, 32, 4, stride=2, padding=1, bias=False)),
                    ('lrelu11',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv0',    nn.ConvTranspose2d(32, 3, 4, stride=2, padding=1, bias=False)),
                ])
            ),
            'pool' : lambda : nn.Sequential(OrderedDict([
                    ('conv6',    nn.Conv2d(256, 512, 3, padding=1)),
                    ('lrelu01',  nn.LeakyReLU(negative_slope=0.3)),
                    ('conv7',    nn.Conv2d(512, 512, 3, padding=1)),
                    ('lrelu02',  nn.LeakyReLU(negative_slope=0.3)),
                    ('conv8',    nn.Conv2d(512, 512, 3, padding=0)),
                    ('lrelu03',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv5_0', nn.ConvTranspose2d(512, 256, 4, stride=2, padding=1, bias=False)),
                    ('lrelu04',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv5_1', nn.ConvTranspose2d(256, 512, 3, stride=1, padding=1, bias=False)),
                    ('lrelu05',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_0', nn.ConvTranspose2d(512, 256, 4, stride=2, padding=1, bias=False)),
                    ('lrelu06',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_1', nn.ConvTranspose2d(256, 256, 3, stride=1, padding=1, bias=False)), 
                    ('lrelu07',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_0', nn.ConvTranspose2d(256, 128, 4, stride=2, padding=1, bias=False)),
                    ('lrelu08',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_1', nn.ConvTranspose2d(128, 128, 3, stride=1, padding=1, bias=False)),
                    ('lrelu09',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv2',   nn.ConvTranspose2d(128, 64, 4, stride=2, padding=1, bias=False)),
                    ('lrelu10',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv1',   nn.ConvTranspose2d(64, 32, 4, stride=2, padding=1, bias=False)),
                    ('lrelu11',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv0',   nn.ConvTranspose2d(32, 3, 4, stride=2, padding=1, bias=False)),
                ])
            ),
            'conv' : lambda : nn.Sequential(OrderedDict([
                    ('conv6',    nn.Conv2d(384, 384, 3, padding=0)),
                    ('lrelu01',  nn.LeakyReLU(negative_slope=0.3)),
                    ('conv7',    nn.Conv2d(384, 512, 3, padding=0)),
                    ('lrelu02',  nn.LeakyReLU(negative_slope=0.3)),
                    ('conv8',    nn.Conv2d(512, 512, 2, padding=0)),
                    ('lrelu03',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv5_0', nn.ConvTranspose2d(512, 256, 4, stride=2, padding=1, bias=False)),
                    ('lrelu04',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv5_1', nn.ConvTranspose2d(256, 256, 3, stride=1, padding=1, bias=False)),
                    ('lrelu05',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_0', nn.ConvTranspose2d(256, 128, 4, stride=2, padding=1, bias=False)),
                    ('lrelu06',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_1', nn.ConvTranspose2d(128, 128, 3, stride=1, padding=1, bias=False)),
                    ('lrelu07',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_0', nn.ConvTranspose2d(128, 128, 4, stride=2, padding=1, bias=False)),
                    ('lrelu08',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_1', nn.ConvTranspose2d(128, 128, 3, stride=1, padding=1, bias=False)),
                    ('lrelu09',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv2_0', nn.ConvTranspose2d(128, 64, 4, stride=2, padding=1, bias=False)),
                    ('lrelu10',  nn.LeakyReLU(negative_slope=0.3)),
                    ('conv2_1',  nn.Conv2d(64, 32, 3, stride=1, padding=1, bias=False)),
                    ('lrelu11',  nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv1_0', nn.ConvTranspose2d(32, 16, 4, stride=2, padding=1, bias=False)),
                    ('lrelu12',  nn.LeakyReLU(negative_slope=0.3)),
                    ('conv1_1',  nn.Conv2d(16, 3, 3, stride=1, padding=1, bias=False)),
                    ('tanh',     nn.Tanh()),
                ])
            ),
            'norm' : lambda : nn.Sequential(OrderedDict([
                    ('conv6',    nn.Conv2d(*inp_par, padding=2)),
                    ('lrelu1',   nn.LeakyReLU(negative_slope=0.3)),
                    ('conv7',    nn.Conv2d(inp_par[1], 128, 3, stride=1, padding=1)),
                    ('lrelu2',   nn.LeakyReLU(negative_slope=0.3)),
                    ('conv8',    nn.Conv2d(128, 128, 3, stride=1, padding=1)),
                    ('lrelu3',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv4_0', nn.ConvTranspose2d(128, 128, 4, stride=2, padding=1, bias=False)),
                    ('lrelu4',   nn.LeakyReLU(negative_slope=0.3)),
                    ('conv4_1',  nn.Conv2d(128, 128, 3, stride=1, padding=1, bias=False)),
                    ('lrelu5',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv3_0', nn.ConvTranspose2d(128, 64, 4, stride=2, padding=1, bias=False)),
                    ('lrelu6',   nn.LeakyReLU(negative_slope=0.3)),
                    ('conv3_1',  nn.Conv2d(64, 64, 3, stride=1, padding=1, bias=False)),
                    ('lrelu7',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv2_0', nn.ConvTranspose2d(64, 32, 4, stride=2, padding=1, bias=False)),
                    ('lrelu8',   nn.LeakyReLU(negative_slope=0.3)),
                    ('conv2_1',  nn.Conv2d(32, 32, 3, stride=1, padding=1, bias=False)),
                    ('lrelu9',   nn.LeakyReLU(negative_slope=0.3)),
                    ('tconv1_0', nn.ConvTranspose2d(32, 16, 4, stride=2, padding=1, bias=False)),
                    ('conv1_1',  nn.Conv2d(16, 3, 3, stride=1, padding=1, bias=False)),
                    ('tanh',     nn.Tanh()),
                ]))
            }
        
        return templates[self.type_net]() 
            
    def _get_net_paths(self, base_nets_dir : str) -> Dict[str, Path]:
        """
        Retrieves the paths of the files of the weights of pytorch neural nets within a base directory and returns a dictionary
        where the keys are the file names and the values are the full paths to those files.

        Args:
            base_nets_dir (str): The path of the base directory (i.e. the dir that contains all nn files). Default is '/content/drive/MyDrive/XDREAM'.

        Returns:
            Dict[str, str]: A dictionary where the keys are the nn file names and the values are the full paths to those files.
        """
        root = Path(base_nets_dir)
        nets_dict = {
            Path(file).stem : Path(base, file)
            for base, _, files in os.walk(root)
            for file in files if file.endswith(('.pt', 'pth'))
        }
        
        return nets_dict  

# TODO: This is @Paolo's job!
class SDXLTurboGenerator(Generator):
    '''
    '''