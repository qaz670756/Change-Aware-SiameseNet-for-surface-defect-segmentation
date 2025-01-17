import torch
import torch.nn as nn
import numpy as np
import torch.nn.functional as F
from matplotlib import pyplot as plt
import cv2
from tqdm import tqdm
import os
import torch.nn.init as init
from torch.utils.data import DataLoader,Dataset
from torchvision import transforms
from PIL import Image

class mydataset(Dataset):
    def __init__(self,pathRef,pathGt):
        super().__init__()
        names_ref = os.listdir(pathRef)
        names_gt = os.listdir(pathGt)
        self.ref = [os.path.join(pathRef,x) for x in names_ref]
        self.gt = [os.path.join(pathGt, x) for x in names_gt]
        self.tforms = transforms.Compose([transforms.Resize((64,64),
                                        interpolation=transforms.InterpolationMode.BICUBIC),
                                        transforms.ToTensor(),
                                        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                        std=[0.229, 0.224, 0.225])])
        ok = Image.open(r"./data/SynLCD_with_geoTforms/oksCuted_512/1-1.bmp")
        self.ok = self.tforms(ok)
    def __getitem__(self, idx):

        ref = Image.open(self.ref[idx])
        gt = Image.open(self.gt[idx])

        ref = self.tforms(ref)
        gt = self.tforms(gt)

        return self.ok,ref,gt,torch.cat([self.ok,ref],dim=0)

    def __len__(self):
        return len(self.ref)
def toArray(x):
    out = x[0].permute((1,2,0)).cpu().detach().numpy()
    out = np.uint8((out-np.min(out))/(np.max(out)-np.min(out))*255)
    return out
def visualize(x,y,out,LOSS):
    fontsize = 18
    f, ax = plt.subplots(2, 2, figsize=(8, 8))

    ax[0, 0].imshow(toArray(x))
    ax[0, 0].set_title('Input Image', fontsize=fontsize)

    ax[0, 1].imshow(toArray(y))
    ax[0, 1].set_title('Reference Image', fontsize=fontsize)

    ax[1, 0].imshow(toArray(out))
    ax[1, 0].set_title('Output Image', fontsize=fontsize)

    # ax[1, 1].imshow(np.abs(toArray(y)[...,::-1]-toArray(out)[...,::-1]))
    # ax[1, 1].set_title('Difference Image', fontsize=fontsize)
    ax[1, 1].plot(LOSS)
    ax[1, 1].set_title('MSE loss', fontsize=fontsize)
    ax[1, 1].set_xlabel('Step', fontsize=fontsize)


    plt.show()

class conv_block_nested(nn.Module):
    def __init__(self, in_ch, mid_ch, out_ch):
        super(conv_block_nested, self).__init__()
        self.activation = nn.ReLU(inplace=True)
        self.conv1 = nn.Conv2d(in_ch, mid_ch, kernel_size=3, padding=1, bias=True)
        self.bn1 = nn.BatchNorm2d(mid_ch)
        self.conv2 = nn.Conv2d(mid_ch, out_ch, kernel_size=3, padding=1, bias=True)
        self.bn2 = nn.BatchNorm2d(out_ch)

    def forward(self, x):
        x = self.conv1(x)
        identity = x
        x = self.bn1(x)
        x = self.activation(x)

        x = self.conv2(x)
        x = self.bn2(x)
        output = self.activation(x + identity)
        return output

class predMatrixLinear(nn.Module):
    def __init__(self, num_layer):
        super(predMatrix, self).__init__()
        self.layers = nn.ModuleList()

        for i in range(num_layer):
            if i == 0:
                layer = nn.Linear(25,100,bias=True)#conv_block_nested(2, 16, 16)
            else:
                layer = nn.Linear(100,100,bias=True)#conv_block_nested(16, 16, 16)
            self.layers.append(layer)
        self.xcor_conv = nn.Linear(100,25,bias=True)#nn.Conv2d(100, 25, kernel_size=3, padding=1, bias=True)
        #self.ycor_conv = nn.Conv2d(16, 5, kernel_size=3, padding=1, bias=True)

    def forward(self, x):
        out = x.view(-1)
        for layer in self.layers:
            out = layer(out)
        #xcor = F.softmax(self.xcor_conv(out), dim=1)
        #ycor = F.softmax(self.xcor_conv(out), dim=1)
        #return xcor, ycor
        return self.xcor_conv(out).view(5,5)


class predImage(nn.Module):
    def __init__(self, num_layer,input_size):
        super(predImage, self).__init__()
        self.size = input_size
        self.layers = nn.ModuleList()
        self.layers.append(nn.Sequential(
                        nn.Conv2d(6, 64, kernel_size=3, padding=1, bias=True),
                        nn.BatchNorm2d(64, momentum=1, affine=True),
                        nn.ReLU(),
                        nn.MaxPool2d(2)))
        self.layers.append(nn.Sequential(
                        nn.Conv2d(64, 64, kernel_size=3, padding=1, bias=True),
                        nn.BatchNorm2d(64, momentum=1, affine=True),
                        nn.ReLU(),
                        nn.MaxPool2d(2)))
        self.layers.append(nn.Sequential(
                        nn.Conv2d(64, 64, kernel_size=3, padding=1, bias=True),
                        nn.BatchNorm2d(64, momentum=1, affine=True),
                        nn.ReLU(),
                        nn.MaxPool2d(2)))
        for i in range(num_layer):
            if i == 0:
                layer = nn.Conv2d(64, input_size, kernel_size=input_size//8, bias=True)
            else:
                layer = nn.Conv2d(64, 64, kernel_size=1, bias=True)
            self.layers.append(layer)
        self.head_conv = nn.Conv2d(input_size, input_size*input_size*3, kernel_size=1, bias=True)
        self._initialize_weights()
    def _initialize_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                init.kaiming_normal_(m.weight.data, mode='fan_out',
                                     nonlinearity='relu')
                m.bias.data.fill_(0)
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
    def forward(self, x):
        out = x
        for layer in self.layers:
            out = layer(out)
        out = self.head_conv(out)
        return out.view(out.shape[0],3,self.size,self.size)

def prepareMatrix(input_size):
    x = torch.eye(input_size).view((1,1,input_size,input_size))#torch.randn([1,1,50, 50])
    y = torch.from_numpy(x.numpy()[..., ::-1].copy())
    #x.requires_grad_(True)
    y.requires_grad_(True)

    data = torch.cat([x,y],dim=1)
    data.requires_grad_(True)
    return x,y.cuda(),data.cuda()

def toTensor(x):
    x = (x-np.min(x))/(np.max(x)-np.min(x))
    x = x.transpose([2,0,1])
    return torch.from_numpy(x).unsqueeze(0).float()

def prepareImage(input_size):
    x = toTensor(cv2.imread(r"D:\Datasets\DefectImage\Face\exp3\oksCuted_512\1-1.bmp"))
    y = toTensor(cv2.imread(r"D:\Datasets\DefectImage\Face\exp3\SynLCD_OKandNG\bg1_onlyGeo\mixed\A\3.png"))
    gt = toTensor(cv2.imread(r"D:\Datasets\DefectImage\Face\exp3\SynLCD_OKandNG\bg1_onlyGeo\mixed\B\3.png"))
    #x.requires_grad_(True)
    y.requires_grad_(True)
    data = torch.cat([x,y],dim=1)
    data.requires_grad_(True)
    return x,y,gt.cuda(),data.cuda()

if __name__ == '__main__':
    # 准备数据
    path = r'./work_dirs/tformsTest'
    input_size = 64
    #x,y,gt,data = prepareImage(input_size)
    model = predImage(1,input_size)
    model.train()
    model.cuda()
    criteria = nn.MSELoss(reduction='mean')
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    LOSS = []
    dset = mydataset(r'./data/SynLCD_OKandNG/bg1/mixed/A',
                     r'./data/SynLCD_OKandNG/bg1/mixed/B')

    train_data = DataLoader(dset,
                            shuffle=True,
                            batch_size=4,
                            num_workers=4)
    for epoch in range(200):
        with tqdm(train_data) as t:
            for ok,ref,gt,data in t:
                # Zero the gradient
                data = data.cuda()
                gt = gt.cuda()
                optimizer.zero_grad()
                out = model(data)
                loss = criteria(out, gt)
                loss.backward()
                optimizer.step()
                LOSS.append(loss.item())
                t.set_description('Epoch:{} loss:{:.2f}'.format(epoch,LOSS[-1]))
        if epoch%5==0:
            cv2.imwrite(os.path.join(path,'epoch_%d.png'%epoch),toArray(out)[...,::-1])

    weight_path = os.path.join(path,'weights')
    os.makedirs(weight_path,exist_ok=True)
    #torch.save(model.state_dict(),os.path.join(weight_path,'weight.pth'))
    visualize(ok,ref,out,LOSS)

    print(loss.item())
