# -*- coding: utf-8 -*-
"""AudioStyleTransferTutorialSoundNet.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/19NPkK1gJmLsu-ZKhEvR86oiVeAFXdw29

We will use the original neural style transfer algorithm implemented by Leon A. Gatys, Alexander S. Ecker and Matthias Bethge for sound.

The tutorial is here: https://pytorch.org/tutorials/advanced/neural_style_tutorial.html#sphx-glr-advanced-neural-style-tutorial-py

This paper: https://arxiv.org/pdf/1710.11385.pdf explains how we can use the above algorithm and transport it to audio. We will need to convert the wave forms into 3D images, and feed it through the network. We will then use  Griffin & Lim’s algorithm to get the final waveform.

Additional Resource: 
https://dmitryulyanov.github.io/audio-texture-synthesis-and-style-transfer/
"""

from google.colab import drive
drive.mount("/content/drive/", force_remount=True)

from __future__ import print_function

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from PIL import Image
import matplotlib.pyplot as plt

import torchvision.transforms as transforms
import torchvision.models as models

import copy
import librosa
import numpy as np
import matplotlib.pyplot as plt

import librosa.display

!pip install torchaudio -f https://download.pytorch.org/whl/torch_stable.html
import torchaudio

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

"""**Generate Spectographs**"""

content_filename = "enter_filename_here"
style_filename = "enter_filename_here"

torchaudio.info(content_filename)

hop_length = 512
n_fft = 2048

def generate_spectogram(filename, title_name):
  timeseries, sampling_rate = librosa.load(filename)
  S = librosa.feature.melspectrogram(timeseries, sr=sampling_rate, n_fft=n_fft, hop_length=hop_length) 
  S_DB = librosa.power_to_db(S, ref=np.max)
  librosa.display.specshow(S_DB, sr=sampling_rate, hop_length=hop_length, 
                          x_axis='time', y_axis='mel');
  plt.title(title_name)
  plt.colorbar(format='%+2.0f dB');

generate_spectogram(content_filename, "Content Spectrogram")

generate_spectogram(style_filename, "Style Spectrogram")

"""**Prepare Inputs for Transfer**"""

music_content = torchaudio.load(content_filename)
music_style = torchaudio.load(style_filename)
sample_rate = music_content[1]

print(music_content[0].shape)
print(music_style[0].shape)
music_content= music_content[0] * (2^-23)
# music_content = music_content[0, 0:300000]
music_content = music_content.view(1,1,-1,1)

music_style= music_style[0] * (2^-23)
# music_style = music_style[0, 0:300000]
music_style = music_style.view(1,1,-1,1)

# music_input = music_content.clone().detach()
music_input = torch.rand(music_content.shape)

print("CONTENT", music_content.shape)
print("STYLE", music_style.shape)
print("INPUT", music_input.shape)
print("SAMPLE RATE", sample_rate)

music_content = music_content.cuda()
music_style = music_style.cuda()
music_input = music_input.cuda()

"""**Original Image Style Transfer Code Below**"""

class ContentLoss(nn.Module):

    def __init__(self, target,):
        super(ContentLoss, self).__init__()
        # we 'detach' the target content from the tree used
        # to dynamically compute the gradient: this is a stated value,
        # not a variable. Otherwise the forward method of the criterion
        # will throw an error.
        self.target = target.detach()

    def forward(self, input):
        self.loss = F.mse_loss(input, self.target)
        return input

def gram_matrix(input):
    a, b, c, d = input.size()  # a=batch size(=1)
    # b=number of feature maps
    # (c,d)=dimensions of a f. map (N=c*d)

    features = input.view(a * b, c * d)  # resise F_XL into \hat F_XL

    G = torch.mm(features, features.t())  # compute the gram product

    # we 'normalize' the values of the gram matrix
    # by dividing by the number of element in each feature maps.
    return G.div(a * b * c * d)

class StyleLoss(nn.Module):

    def __init__(self, target_feature):
        super(StyleLoss, self).__init__()
        self.target = gram_matrix(target_feature).detach()

    def forward(self, input):
        G = gram_matrix(input)
        self.loss = F.mse_loss(G, self.target)
        # self.loss = F.mse_loss(input, self.target)
        return input

"""**Sound Net Model**"""

class SoundNet(nn.Module):
    def __init__(self):
        super(SoundNet, self).__init__()

        self.conv1 = nn.Conv2d(1, 16, kernel_size=(64, 1), stride=(2, 1),
                               padding=(32, 0))
        self.batchnorm1 = nn.BatchNorm2d(16, eps=1e-5, momentum=0.1)
        self.relu1 = nn.ReLU(True)
        self.maxpool1 = nn.MaxPool2d((8, 1), stride=(8, 1))

        self.conv2 = nn.Conv2d(16, 32, kernel_size=(32, 1), stride=(2, 1),
                               padding=(16, 0))
        self.batchnorm2 = nn.BatchNorm2d(32, eps=1e-5, momentum=0.1)
        self.relu2 = nn.ReLU(True)
        self.maxpool2 = nn.MaxPool2d((8, 1), stride=(8, 1))

        self.conv3 = nn.Conv2d(32, 64, kernel_size=(16, 1), stride=(2, 1),
                               padding=(8, 0))
        self.batchnorm3 = nn.BatchNorm2d(64, eps=1e-5, momentum=0.1)
        self.relu3 = nn.ReLU(True)

        self.conv4 = nn.Conv2d(64, 128, kernel_size=(8, 1), stride=(2, 1),
                               padding=(4, 0))
        self.batchnorm4 = nn.BatchNorm2d(128, eps=1e-5, momentum=0.1)
        self.relu4 = nn.ReLU(True)

        self.conv5 = nn.Conv2d(128, 256, kernel_size=(4, 1), stride=(2, 1),
                               padding=(2, 0))
        self.batchnorm5 = nn.BatchNorm2d(256, eps=1e-5, momentum=0.1)
        self.relu5 = nn.ReLU(True)
        self.maxpool5 = nn.MaxPool2d((4, 1), stride=(4, 1))

        self.conv6 = nn.Conv2d(256, 512, kernel_size=(4, 1), stride=(2, 1),
                               padding=(2, 0))
        self.batchnorm6 = nn.BatchNorm2d(512, eps=1e-5, momentum=0.1)
        self.relu6 = nn.ReLU(True)

        self.conv7 = nn.Conv2d(512, 1024, kernel_size=(4, 1), stride=(2, 1),
                               padding=(2, 0))
        self.batchnorm7 = nn.BatchNorm2d(1024, eps=1e-5, momentum=0.1)
        self.relu7 = nn.ReLU(True)

        self.conv8_objs = nn.Conv2d(1024, 1000, kernel_size=(8, 1),
                                    stride=(2, 1))
        self.conv8_scns = nn.Conv2d(1024, 401, kernel_size=(8, 1),
                                    stride=(2, 1))

    def forward(self, waveform):
        x = self.conv1(waveform)
        x = self.batchnorm1(x)
        x = self.relu1(x)
        x = self.maxpool1(x)

        x = self.conv2(x)
        x = self.batchnorm2(x)
        x = self.relu2(x)
        x = self.maxpool2(x)

        x = self.conv3(x)
        x = self.batchnorm3(x)
        x = self.relu3(x)

        x = self.conv4(x)
        x = self.batchnorm4(x)
        x = self.relu4(x)

        x = self.conv5(x)
        x = self.batchnorm5(x)
        x = self.relu5(x)
        x = self.maxpool5(x)

        x = self.conv6(x)
        x = self.batchnorm6(x)
        x = self.relu6(x)

        x = self.conv7(x)
        x = self.batchnorm7(x)
        x = self.relu7(x)

        return x

import copy
soundnet = SoundNet()
soundnet.load_state_dict(torch.load("/content/drive/My Drive/AudioStyleTransfer/soundnet8_final.pth"))
soundnet = soundnet.cuda()

# desired depth layers to compute style/content losses :
content_layers_default = ['conv_1']
style_layers_default = ['conv_1', 'conv_2', 'conv_3', 'conv_4', 'conv_5']

def get_style_model_and_losses(cnn,
                               style_img, content_img,
                               content_layers=content_layers_default,
                               style_layers=style_layers_default):
    cnn = copy.deepcopy(cnn)

    # just in order to have an iterable access to or list of content/syle
    # losses
    content_losses = []
    style_losses = []

    # assuming that cnn is a nn.Sequential, so we make a new nn.Sequential
    # to put in modules that are supposed to be activated sequentially
    model = nn.Sequential()

    i = 0  # increment every time we see a conv
    for layer in cnn.children():
        if isinstance(layer, nn.Conv2d):
            i += 1
            name = 'conv_{}'.format(i)
        elif isinstance(layer, nn.ReLU):
            name = 'relu_{}'.format(i)
            # The in-place version doesn't play very nicely with the ContentLoss
            # and StyleLoss we insert below. So we replace with out-of-place
            # ones here.
            layer = nn.ReLU(inplace=False)
        elif isinstance(layer, nn.MaxPool2d):
            name = 'pool_{}'.format(i)
        elif isinstance(layer, nn.BatchNorm2d):
            name = 'bn_{}'.format(i)
        else:
            raise RuntimeError('Unrecognized layer: {}'.format(layer.__class__.__name__))

        model.add_module(name, layer)

        if name in content_layers:
            # add content loss:
            target = model(content_img).detach()
            content_loss = ContentLoss(target)
            model.add_module("content_loss_{}".format(i), content_loss)
            content_losses.append(content_loss)

        if name in style_layers:
            # add style loss:
            target_feature = model(style_img).detach()
            style_loss = StyleLoss(target_feature)
            model.add_module("style_loss_{}".format(i), style_loss)
            style_losses.append(style_loss)

    # now we trim off the layers after the last content and style losses
    for i in range(len(model) - 1, -1, -1):
        if isinstance(model[i], ContentLoss) or isinstance(model[i], StyleLoss):
            break

    model = model[:(i + 1)]

    return model, style_losses, content_losses

def get_input_optimizer(input_img):
    # this line to show that input is a parameter that requires a gradient
    optimizer = optim.LBFGS([input_img.requires_grad_()])
    return optimizer

def run_style_transfer(cnn,
                       content_img, style_img, input_img, num_steps=5000,
                       style_weight=1000000, content_weight=1):
    """Run the style transfer."""
    print('Building the style transfer model..')
    model, style_losses, content_losses = get_style_model_and_losses(cnn,
        style_img, content_img)
    optimizer = get_input_optimizer(input_img)
    print("MODEL PARAMETERS", model.parameters)

    print('Optimizing..')
    run = [0]
    while run[0] <= num_steps:

        def closure():
            optimizer.zero_grad()
            model(input_img)
            style_score = 0
            content_score = 0

            for sl in style_losses:
                style_score += sl.loss
            for cl in content_losses:
                content_score += cl.loss

            style_score *= style_weight
            content_score *= content_weight

            loss = style_score + content_score
            loss.backward()

            run[0] += 1
            if run[0] % 50 == 0:
                print("run {}:".format(run))
                print('Style Loss : {:4f} Content Loss: {:4f}'.format(
                    style_score.item(), content_score.item()))
                print()

            return style_score + content_score

        optimizer.step(closure)

    return input_img

output = run_style_transfer(soundnet, music_content, music_style, music_input)

"""**Save Output to Image & Audio**"""

print(output.shape)
output = output.squeeze()
output= output.unsqueeze(0)
output = output / (2^-23)
print(output.shape)

S = librosa.feature.melspectrogram(output.squeeze().cpu().detach().numpy(), sr=sample_rate, n_fft=n_fft, hop_length=hop_length)
S_DB = librosa.power_to_db(S, ref=np.max)
librosa.display.specshow(S_DB, sr=sample_rate, hop_length=hop_length, 
                        x_axis='time', y_axis='mel');
plt.title("Output Spectrogram")
plt.colorbar(format='%+2.0f dB');

print(output)

torchaudio.save("enter_filename_here", output.cpu(), sample_rate)

