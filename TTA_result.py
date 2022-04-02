import torch
from osgeo import gdal
import numpy as np
import glob
import math
import segmentation_models_pytorch as smp
import cv2
from GDILDeepLabmodel import GNDDeepLab
from BDILDeepLabmodel import BNDDeepLab

train_length = 1024

def readTif(fileName):
    dataset = gdal.Open(fileName)
    if dataset == None:
        print(fileName + "�ļ��޷���")
    #  դ����������
    width = dataset.RasterXSize
    #  դ����������
    height = dataset.RasterYSize
    #  ��ȡ����
    data = dataset.ReadAsArray(0, 0, width, height)
    #��ȡ������Ϣ
    geotans = dataset.GetGeoTransform()
    #��ȡͶӰ
    proj = dataset.GetProjection()
    return data, geotans, proj

def writeTiff(im_data, im_geotrans, im_proj, path):
    if 'int8' in im_data.dtype.name:
        datatype = gdal.GDT_Byte
    elif 'int16' in im_data.dtype.name:
        datatype = gdal.GDT_UInt16
    else:
        datatype = gdal.GDT_Float32
    if len(im_data.shape) == 3:
        im_bands, im_height, im_width = im_data.shape
    elif len(im_data.shape) == 2:
        im_data = np.array([im_data])
        im_bands,im_height, im_width =im_data.shape
    # �����ļ�
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(path, int(im_width), int(im_height), int(im_bands), datatype)
    if (dataset != None):
        dataset.SetGeoTransform(im_geotrans)  # д�����任����
        dataset.SetProjection(im_proj)  # д��ͶӰ
    for i in range(im_bands):
        dataset.GetRasterBand(i + 1).WriteArray(im_data[i])
    del dataset

def clipTiff(data, cliplength):
    #�洢�ü�����
    clip_tiff_list = []
    #  ����ͼ�����Ŀ(������)
    RowNum = int((data.shape[1] - cliplength * 2) / (train_length - cliplength * 2))
    #  ����ͼ�����Ŀ(������)
    ColumnNum = int((data.shape[2] - cliplength * 2) / (train_length - cliplength * 2))
    for i in range(RowNum):
        for j in range(ColumnNum):
            clip = data[:, i * (train_length - cliplength * 2) : i * (train_length - cliplength * 2) + train_length,
                           j * (train_length - cliplength * 2) : j * (train_length - cliplength * 2) + train_length]
            clip_tiff_list.append(clip)
    #  ���ǵ����л���ʣ����������ǰ�ü�һ�к�һ��
    #�����ʣ��������ǰ�ü�һ��
    remainder_column = (data.shape[2] - cliplength * 2) % (train_length - cliplength * 2)
    if remainder_column == 0:
        Column_sum = ColumnNum
    else:
        for i in range(RowNum):
            clip = data[:,i * (train_length - cliplength * 2) : i * (train_length - cliplength * 2) + train_length,
                        (data.shape[2] - train_length) : data.shape[2]]
            clip_tiff_list.insert((i + 1)*ColumnNum + i, clip)
        Column_sum = ColumnNum + 1
    #�����ʣ��������ǰ�ü�һ��
    remainder_row = (data.shape[1] - cliplength * 2) % (train_length - cliplength * 2)
    if remainder_row == 0:
        Row_sum = RowNum
    else:
        for i in range(ColumnNum):
            clip = data[:, (data.shape[1] - train_length): data.shape[1],
                       i * (train_length - cliplength * 2) : i * (train_length - cliplength * 2) + train_length]
            clip_tiff_list.append(clip)
        Row_sum = RowNum + 1
    #������½�һС���ȱ
    if remainder_column != 0 and remainder_row != 0:
        clip = data[ : , (data.shape[1] - train_length): data.shape[1], (data.shape[2] - train_length): data.shape[2]]
        clip_tiff_list.append(clip)
    return clip_tiff_list, Row_sum, Column_sum, remainder_row, remainder_column


#Ӱ���һ��������������������
def normalization_generator(data_list):
    for data in data_list:
        result = np.zeros(data.shape, dtype=np.float32)
        cv2.normalize(src=data, dst=result, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX, dtype=cv2.CV_32F, mask=None)
        yield result


#Ӱ��ƴ��
def mosicTiff(pred_data_list, row_sum, col_sum, remainder_row, remainder_column, shape, cliplength):
    #����һ��ȫ��0��������������ƴ�ӵ�ֵ
    result = np.zeros(shape)
    #������������
    #������С��ȥ�ü���С�ı�,���Ͻ�Ӱ��ƴ�ӵı߳�
    a_length = train_length - cliplength
    # ������С��ȥ2���ü���С�ı�,���Ͻ�Ӱ��ƴ�ӵı߳�
    b_length = train_length - 2*cliplength
    for i,item in enumerate(pred_data_list):
        #�ü������һ��һ�У���������½���һС��
        #����������ʣ��Ҳ������û��ʣ������
        #if remainder_row !=0 and  remainder_column != 0:
        #  �����һ�����⿼�ǣ���ߵı�ԵҪƴ�ӽ�ȥ
        if i % col_sum == 0:
            #  ��һ�е�Ҫ�����⿼�ǣ��ϱߵı�ԵҪ���ǽ�ȥ
            if i == 0:
                result[0 : a_length, 0 : a_length] = item[0 : a_length, 0 : a_length]
            # ���һ��
            elif i/col_sum == row_sum - 1:
                result[shape[0] - remainder_row - cliplength: shape[0], 0 : a_length] = \
                    item[train_length - remainder_row -cliplength: train_length, 0 : a_length]
            else:
                j = int(i/col_sum)
                result[a_length + (j-1) * b_length : a_length + j * b_length, 0 : a_length] = item[cliplength : a_length, 0 :a_length]
        #  ���Ҳ�һ�����⿼�ǣ��ұߵı�ԵҪƴ�ӽ�ȥ
        elif (i+1) % col_sum == 0:
            #  ��һ�е�Ҫ�����⿼�ǣ��ϱߵı�ԵҪ���ǽ�ȥ
            if i + 1 == col_sum:
                result[0: a_length, shape[1] - cliplength - remainder_row: shape[1]] = item[0 :a_length, train_length - remainder_row - cliplength: train_length]
            #���һ�У����һ��Ӱ��
            elif (i + 1)/col_sum == row_sum :
                result[shape[0] - remainder_row - cliplength: shape[0], shape[1] - remainder_column: shape[1]] = \
                    item[train_length - remainder_row - cliplength: train_length,train_length - remainder_column:train_length]
            else:
                j = int((i + 1) / col_sum) - 1
                result[a_length + (j - 1) * b_length : a_length + j * b_length, shape[1] - cliplength - remainder_column: shape[1]] = \
                    item[cliplength : a_length, train_length - remainder_column - cliplength : train_length]
        else:
            #�м�������һ��
            if  i > 0 and i < col_sum-1:
                result[0:a_length, a_length + (i-1) *b_length: a_length + i * b_length] = item[0:a_length, cliplength:a_length]
                #�м���
            elif i > col_sum -1 and i < row_sum * col_sum - col_sum:
                #j������λ�ڼ��У���0��ʼ����
                j = int(i/col_sum)
                #k������λ�ڼ��У���0��ʼ����
                k = i % col_sum
                result[a_length + (j-1) * b_length: a_length + j * b_length, a_length + (k - 1) * b_length: a_length + k * b_length] = \
                    item[ cliplength: a_length, cliplength: a_length]
            else:
                #���һ�е����
                #j��λ���һ�е���������0��ʼ��
                j = col_sum - (row_sum * col_sum - i)
                result[shape[0] - remainder_row -cliplength: shape[0], a_length + (j - 1) * b_length: a_length + j * b_length] = \
                    item[train_length - remainder_row - cliplength: train_length, cliplength: a_length]
    return result

#ģ������ָ�
def predict(Model_Path, img_nor):
    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    model = BNDDeepLab(in_ch=4, num_classes=1, backbone="resnet34", downsample_factor=16)
    model.to(device)
    model.load_state_dict(torch.load(Model_Path))
    Pred_list = []
    a = 0
    model.eval()
    for i in img_nor:
        with torch.no_grad():
            img = np.array([i])
            img_tensor = torch.from_numpy(img)
            # ��tensor������device�У�ֻ��cpu���ǿ�����cpu�У���cuda���ǿ�����cuda�С�
            img_tensor = img_tensor.to(device=device)
            pred = model(img_tensor)
            # ��ȡ���
            if class_style == 'two_class':
                pred = torch.sigmoid(pred)
                #��ȡonehot����±꣬�Ϳ��Եó����ֳ������ĸ���
                print(pred.shape)
                #����ά��Ϊ��ά
                pred = np.array(pred.data.cpu()[0])[0]
            else:
                pred = pred[0]
                pred = torch.softmax(pred, dim=0).cpu()
                _, pred = torch.max(pred, dim=0)
                print(pred.shape)
                pred = np.array(pred)
            #savepath = 'G:/DL/list2/' + str(a) + '.tif'
            a = a + 1
            #writeTiff(pred, img_trans, img_proj, savepath)
            print('finish')
            print(pred.shape)
            Pred_list.append(pred)
            print('finish')
    return Pred_list

#Ԥ����
def processing(im_data,ClipLength, Model_Path):
    # ����Ӱ��
    clip_list, row_sum, col_sum, re_row, re_col = clipTiff(im_data, ClipLength)
    print(row_sum, col_sum)
    # �����ݽ��й�һ������
    img_normalization = normalization_generator(clip_list)
    # ����Ԥ��
    pred_list = predict(Model_Path, img_normalization)
    result_shape = (im_data.shape[1], im_data.shape[2])
    # ƴ��Ӱ��
    result = mosicTiff(pred_list, row_sum, col_sum, re_row, re_col, result_shape, ClipLength)
    return result

# ������ǿ
def TTA(im_data, ClipLength, Model_Path):
    #  ͼ��ˮƽ��ת
    im_data_hor = np.flip(im_data, axis=2)  # ������3ά
    #  ͼ��ֱ��ת
    im_data_vec = np.flip(im_data, axis=1)
    #  ͼ��ԽǾ���
    im_data_dia = np.flip(im_data_vec, axis=2)
    # ͼƬ˳ʱ����ת90��
    im_data_rotz = np.rot90(im_data, -1, (1, 2))
    # ͼƬ��ʱ����ת90��
    im_data_rotn = np.rot90(im_data, 1, (1, 2))
    #Ԥ��
    data_result = processing(img_data, ClipLength, Model_Path)
    data_hor_result = processing(im_data_hor, ClipLength, Model_Path)
    data_vec_result = processing(im_data_vec, ClipLength, Model_Path)
    data_dia_result = processing(im_data_dia, ClipLength, Model_Path)
    data_rotz_result = processing(im_data_rotz, ClipLength, Model_Path)
    data_rotn_result = processing(im_data_rotn, ClipLength, Model_Path)
    #��ԭ
    data_hor_result = np.flip(data_hor_result, axis=1)
    data_vec_result = np.flip(data_vec_result, axis=0)
    data_dia_result = np.flip(np.flip(data_dia_result, axis=0), axis=1)
    data_rotz_result = np.rot90(data_rotz_result, 1, (0, 1))
    data_rotn_result = np.rot90(data_rotn_result, -1, (0, 1))
    tta_result = (data_result + data_hor_result + data_vec_result + data_dia_result + data_rotz_result + data_rotn_result)/6
    return tta_result


model_path = r''
img_list = glob.glob(r"")
class_style = 'two_class'

in_area = 0.8
clipLength = int((1 - math.sqrt(in_area)) * train_length / 2)
img_data, img_trans, img_proj = readTif(img_list[0])
data_result = TTA(img_data , clipLength, model_path)
savepath = r'H:\DL\ģ�Ͳ���\GF2_PMS1_E89.8_N35.6_20201231\att\TTA.tif'
writeTiff(data_result, img_trans, img_proj, savepath)
