#-*- coding: utf-8 -*-
from bson import Code
# from django.shortcuts import render
# from django.http import HttpResponse, JsonResponse
# from django.views.decorators.csrf import csrf_exempt
import os
import allel
import numpy as np
import json
import multiprocessing
import pickle
from lockfile import LockFile
from pymongo import MongoClient
import re
import zipfile
#from django.http import StreamingHttpResponse
from wsgiref.util import FileWrapper
from functools import partial
import time
import sys
#import zerorpc

class MyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.int_, np.intc, np.intp, np.int8,
                            np.int16, np.int32, np.int64, np.uint8,
                            np.uint16, np.uint32, np.uint64)):
            return int(obj)
        elif isinstance(obj, (np.float_, np.float16, np.float32,
                              np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return list(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return json.JSONEncoder.default(self, obj)

def RenameJsonKey(strJson):
    if isinstance(strJson,dict):
        strJson = json.dumps(strJson)
    #先默认json的key中没有特殊符号
    pattern = re.compile(r"\"([\w.$:]+)\":")
    strJson = pattern.sub(lambda m: m.group(0).replace('.', "_").replace('$', "^"), strJson)
    return strJson


#class Transform(object):
def addhead(header, filepath_json):
    record_head = []
    for line in header:
        record_head.append(line)
    record = {
       "header": record_head
    }
    with open(filepath_json, 'a') as fp:
        recordstring = json.dumps(record, cls=MyEncoder) + '\n'
        fp.write(recordstring)
    return

def chunker2string(chunker, fields, samples, mode='MergeSamples'):
    li = []
    infoNum = 0
    if mode == 'MergeAll':
        for i in range(chunker[1]):
            #basic
            recorddict1 = {
                "CHROM": chunker[0]['variants/CHROM'][i],
                "POS" : chunker[0]['variants/POS'][i],
                "ID": chunker[0]['variants/ID'][i],
                "REF": chunker[0]['variants/REF'][i],
                "ALT": chunker[0]['variants/ALT'][i],
                "QUAL": chunker[0]['variants/QUAL'][i],
            }
            #filter
            recorddict2 = {
                "FILTER": {
                    k_filter[9:] : chunker[0][k_filter][i] for k_filter in fields if 'variants/FILTER' in k_filter
                }
            }

            #Info
            recorddict3 = {
                "Info": {
                    k_Info[9:] : chunker[0][k_Info][i] for k_Info in fields if k_Info not in ['variants/CHROM', 'variants/POS', 'variants/ID', 'variants/REF', 'variants/ALT', 'variants/QUAL', 'variants/numalt', 'variants/svlen', 'variants/is_snp']
                    and 'variants/FILTER' not in k_Info and 'calldata/' not in k_Info
                }
            }

            infoNum += len(recorddict3['Info'])

            #Samples
            recordsamples = []
            for k_sample, j in zip(samples, range(samples.size)):
                recordsample1 = {
                    "SampleNo": k_sample
                }
                recordsample2 = {
                    k_field[9:]: [chunker[0][k_field][i][j][n] for n in
                                  range(chunker[0][k_field][i][j].size)] if type(
                        chunker[0][k_field][i][j]) == np.ndarray else chunker[0][k_field][i][j] for k_field in
                    fields if "calldata/" in k_field
                }
                recordsample = dict(recordsample1, **recordsample2)
                recordsamples.append(recordsample)
            recorddict4 = {
                "Samples": recordsamples
            }

            recorddictMerge = dict(dict(dict(recorddict1, **recorddict2), **recorddict3),**recorddict4)
            #recorddictMerge = dict(recorddict1, **recorddict2, **recorddict3, **recorddict4)
            #recorddictMerge = dict(recorddict1, recorddict2, recorddict3, recorddict4)
            li.append(recorddictMerge)

    elif mode == 'MergeSamples':
        for i in range(chunker[1]):
            recorddict1 = {
                k_field[9:]: [chunker[0][k_field][i][m] for m in range(chunker[0][k_field][i].size)] if type(
                    chunker[0][k_field][i]) == np.ndarray else chunker[0][k_field][i] for k_field in fields if
                'variants/' in k_field and k_field not in  ['variants/numalt', 'variants/svlen', 'variants/is_snp']
            }
            recordsamples = []
            for k_sample, j in zip(samples, range(samples.size)):
                recordsample1 = {
                    "SampleNo": k_sample
                }
                recordsample2 = {
                    k_field[9:]: [chunker[0][k_field][i][j][n] for n in
                                  range(chunker[0][k_field][i][j].size)] if type(
                        chunker[0][k_field][i][j]) == np.ndarray else chunker[0][k_field][i][j] for k_field in
                    fields if "calldata/" in k_field
                }
                recordsample = dict(recordsample1, **recordsample2)
                recordsamples.append(recordsample)
            recorddict2 = {
                "Samples": recordsamples
            }

            recorddict = dict(recorddict1, **recorddict2)
            li.append(recorddict)

    recordstring = json.dumps(li, cls=MyEncoder) + '\n'
    return recordstring, infoNum


def IoOperat_multi(tmpfile, mode, statisticArr, chunker):
    # tmpfile = "value_" + md5 + ".dat"
    with open(tmpfile, "rb") as f:
        fields = pickle.load(f)
        samples = pickle.load(f)
        headers = pickle.load(f)
        filepath_json = pickle.load(f)
    recordstring, infonum = chunker2string(chunker, fields, samples, mode)
    lock = LockFile(filepath_json)
    lock.acquire()
    with open(filepath_json, "a") as fp:
        statisticArr[0] += chunker[1]
        statisticArr[1] += infonum
        fp.write(recordstring)
    lock.release()
    return


def vcf2json_Single(filepath_vcf, filepath_json, mode):
    fields, samples, headers, chunks = allel.iter_vcf_chunks(filepath_vcf, fields=['*'], chunk_length=50)

    if os.path.exists(filepath_json):
        os.remove(filepath_json)
    addhead(headers[0], filepath_json)

    for chunker in chunks:
        with open(filepath_json, 'a') as fp:
            recordstring = chunker2string(chunker, fields, samples, mode)
            fp.write(recordstring)

    return


def vcf2json_multi2(filepath_vcf, filepath_json, md5, mode):
    #统计数据
    time_start = time.time()
    manager = multiprocessing.Manager()
    statisticArr = manager.Array("i", [0, 0])

    fields, samples, headers, chunks = allel.iter_vcf_chunks(filepath_vcf, fields=['variants/*', 'calldata/*'],chunk_length=500)

    if os.path.exists(filepath_json):
        os.remove(filepath_json)
    #增加原vcf文件的头部信息, 用于逆向转换
    addhead(headers[0], filepath_json)



    tmpfile = "value_" + md5 + ".dat"
    with open(tmpfile, "wb") as f:
        pickle.dump(fields, f)
        pickle.dump(samples, f)
        pickle.dump(headers, f)
        pickle.dump(filepath_json, f)

    cores = multiprocessing.cpu_count()
    #processnum = max(int(cores / 2), 2)
    processnum = cores
    #pool = multiprocessing.Pool(processes=max(int(cores/2), 2))

    #自己调度迭代器 防止内存溢出
    pool = multiprocessing.Pool(processes=processnum)
    index = 0
    tmpchunks = []
    for chunker in chunks:
        index+=1
        tmpchunks.append(chunker)
        if index % (processnum*50) == 0:
            pool.map(partial(IoOperat_multi, tmpfile, mode, statisticArr), tmpchunks)
            # time.sleep(10)
            tmpchunks.clear()

    pool.map(partial(IoOperat_multi, tmpfile, mode, statisticArr), tmpchunks)
    pool.close()
    pool.join()  # 主进程阻塞等待子进程的退出
    os.remove(tmpfile)  # 删除该分片，节约空间

    #保存统计数据
    time_end = time.time()
    time_cost = time_end - time_start
    dir = os.path.splitext(filepath_vcf)[0]
    statisticFile = dir + '.txt'
    with open(statisticFile, mode='a') as fp:
        result = (filepath_vcf + '\t' + 'chrom: ' + '{0}' + '\t' + 'info: ' + '{1}' + '\t' + 'sample: ' + '{2}' + '\t' +'total cost: ' + '{3}' + '\n').format(statisticArr[0], statisticArr[1], samples.size, time_cost)
        fp.write(result)



def dotranform(filepath_vcf, mode):
    file_json = os.path.splitext(filepath_vcf)[0] + ".json"
    vcf2json_multi2(filepath_vcf, file_json, "tmpdat", mode)
    #self.vcf2json_Single(filepath_vcf, file_json, mode)


#with output path
def dotransformWithOutPath(filepath_vcf, filepath_json, mode):
    vcf2json_multi2(filepath_vcf, filepath_json, "tmpdat", mode)


def preview(filepath_vcf, mode):
    fields, samples, headers, chunks = allel.iter_vcf_chunks(filepath_vcf, fields=['*'], chunk_length=2)
    #get first 2 lines for example
    #get json
    for chunker in chunks:
        recordstring = chunker2string(chunker, fields, samples, mode)
        recordstring = RenameJsonKey(recordstring)
        break

    #get vcf
    linenum = 0
    vcfline = str()
    with open(filepath_vcf) as file:
        while True:
            line = file.readline()
            if not line:
                break
            else:
                if line[1] != '#':
                    vcfline += line
                    linenum += 1
                    if linenum == 3:
                        break

    result = {"vcf": vcfline, "json": recordstring}
    return result


if __name__ == "__main__":
    filepath = sys.argv[1]
    #transform = Transform()
    dotranform(filepath, mode='MergeAll')



    # multiprocessing.freeze_support()
    # s = zerorpc.Server(Transform(), heartbeat=None)
    # s.bind("tcp://0.0.0.0:42142")
    # s.run()