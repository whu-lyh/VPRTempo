#MIT License

#Copyright (c) 2023 Adam Hines, Peter G Stratton, Michael Milford, Tobias Fischer

#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:

#The above copyright notice and this permission notice shall be included in all
#copies or substantial portions of the Software.

#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#SOFTWARE.

# Get the 2D patches or the patch normalization

'''
Imports
'''
import cv2
import math
import torch

import numpy as np
import matplotlib.pyplot as plt

def get_patches2D(patch_size,image_pad):
    
    if patch_size[0] % 2 == 0: 
        nrows = image_pad.shape[0] - patch_size[0] + 2
        ncols = image_pad.shape[1] - patch_size[1] + 2
    else:
        nrows = image_pad.shape[0] - patch_size[0] + 1
        ncols = image_pad.shape[1] - patch_size[1] + 1
    patches = np.lib.stride_tricks.as_strided(image_pad , patch_size + (nrows, ncols), 
          image_pad.strides + image_pad.strides).reshape(patch_size[0]*patch_size[1],-1)
    
    return patches

# Run patch normalization on imported RGB images
def patch_normalise_pad(img,patches):
    
    patch_size = (patches, patches)
    patch_half_size = [int((p-1)/2) for p in patch_size ]

    image_pad = np.pad(np.float64(img), patch_half_size, 'constant', 
                                                   constant_values=np.nan)

    nrows = img.shape[0]
    ncols = img.shape[1]
    patches = get_patches2D(patch_size,image_pad)
    mus = np.nanmean(patches, 0)
    stds = np.nanstd(patches, 0)

    with np.errstate(divide='ignore', invalid='ignore'):
        im_norm = (img - mus.reshape(nrows, ncols)) / stds.reshape(nrows, ncols)

    im_norm[np.isnan(im_norm)] = 0.0
    im_norm[im_norm < -1.0] = -1.0
    im_norm[im_norm > 1.0] = 1.0
    
    return im_norm

# Process the loaded images - resize, normalize color, & patch normalize
def processImage(img,dims,patches):
    # gamma correct images
    mid = 0.5
    mean = np.mean(img)
    gamma = math.log(mid*255)/math.log(mean)
    img = np.power(img,gamma).clip(0,255).astype(np.uint8)
    
    # resize image to 28x28 and patch normalize        
    img = cv2.resize(img,(dims[0], dims[1]))
    im_norm = patch_normalise_pad(img,patches) 
    img = np.uint8(255.0 * (1 + im_norm) / 2.0)

    return img

# Image loader function - runs all image import functions
def loadImages(test_true,train_paths,img_names,dims,patches,testPath,testLoc):
    
    # get torch device
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu") 
   
    # Create dictionary of images
    imgs = {'training':[],'testing':[]}
    ids = {'training':[],'testing':[]}
    
    if test_true:
        train_paths = [testPath+testLoc+'/']
    
    for paths in train_paths:
        if testLoc in paths:
            dictEntry = 'testing'
        else:
            dictEntry = 'training'
        for m in img_names:
            fullpath = paths+m
            # read and convert image from BGR to RGB 
            img = cv2.imread(fullpath)[:,:,::-1]
            # convert image
            img = cv2.cvtColor(img,cv2.COLOR_RGB2GRAY)
            imgProc = processImage(img,dims,patches)
            imgs[dictEntry].append(torch.tensor(imgProc,device=device))
            ids[dictEntry].append(m)
    
    return imgs, ids
             
# sets the spike rates from imported images - convert pixel range [0,255] to [0,1]
# spike rates are set as a 3D tensor with dimensions (m x r x s)
# m = module
# r = location repeat
# s = spikes for number of training images
def setSpikeRates(data,ids,device,dims,test_true,numImgs,numMods,intensity,locRep):   
    
     # output tensor dimensions
     n_input = dims[0] * dims[1]
     
     # Set the spike rates based on the number of example training images
     
     # loop through data and append spike rates for each image
     # organise into 3D tensor based on number of expert modules
     if test_true: # if loading testing data (repeat input across modules)
         init_rates = torch.empty(0,device=device) 
         for m in range(numImgs):

             init_rates = torch.cat((init_rates, torch.reshape(data[m]/intensity,(n_input,)))) 
             
         init_rates = torch.unsqueeze(init_rates,0)    
         # define the initial spike rates
         for o in range(numMods):
             if o == 0:
                 spike_rates = torch.unsqueeze(init_rates,0)
             else:
                 spike_rates = torch.concat((spike_rates,torch.unsqueeze(init_rates,0)),0)

                        
     else: # if loading training data, have separate inputs across modules
        for o in range(numMods):
            start = []
            end = []
            for j in range(locRep):
                mod = j * numImgs
                start.append(int(numImgs/numMods)*(o) + mod)
                end.append(int(numImgs/numMods)*(o + 1) + mod)

            # define the initial spike rates for location repeats
            for m in range(locRep):
                rates = torch.empty(0,device=device)
                for jdx, j in enumerate(range(start[m],end[m])):    
                    rates = torch.cat((rates,
                               torch.reshape(data[j]/intensity,(n_input,))),0)  
                if m == 0:
                    init_rates = torch.unsqueeze(rates,0)
                else:
                    init_rates = torch.cat((init_rates,torch.unsqueeze(rates,0)),-1)
            
            # output spike rates into modules
            if o == 0: # append the location repeat initial spikes to a new module
                spike_rates = torch.unsqueeze(init_rates,0)
            else:
                spike_rates = torch.concat((spike_rates,torch.unsqueeze(init_rates,0)),0)
     
     return spike_rates

# plot similarity matrices
def plot_similarity(mat,name,outfold):
    
    fig = plt.figure()
    plt.matshow(mat,fig, cmap=plt.cm.gist_yarg)
    plt.colorbar(label="Spike amplitude")
    fig.suptitle(name,fontsize = 12)
    plt.xlabel("Query",fontsize = 12)
    plt.ylabel("Database",fontsize = 12)
    plt.show()
    fig.savefig(outfold+name+'.png')
    

# plot weight matrices
def plot_weights(W,name,cmap,div,vmax,outfold):
    
    # get the dimensions of the weight matrices
    dims = [len(W[0,:,0]),len(W[0,0,:])]
    
    # calculate the output weight dimensions
    x = int(len(W[:,0,0])/div)
    y = int(len(W[:,0,0])/x)
    newx = x * dims[0]
    newy = y * dims[1]
    
    # loop through expert modules and output weights
    init_weight = np.array([])
    for n in range(len(W[:,0,0])):
        init_weight = np.append(init_weight,np.reshape(W[n,:,:].cpu().numpy(),
                                                        (dims[0]*dims[1],)))
    
    # reshape the weight matrices
    reshape_weight = np.reshape(init_weight,(newx,newy))
    
    if np.any(reshape_weight<0):
        reshape_weight = reshape_weight * -1
    
    fig = plt.figure()
    plt.matshow(reshape_weight,fig, cmap=cmap, vmin=0, vmax=vmax)
    plt.colorbar(label="Weight strength")
    fig.suptitle(name,fontsize = 12)
    plt.xlabel("x-weights",fontsize = 12)
    plt.ylabel("y-weights",fontsize = 12)
    plt.show()
    
    fig.savefig(outfold+'images/training/'+name+'.png')