import os
import argparse
from trainer import Pet_Classifier
import pandas as pd
from data_utils.csv_reader import csv_reader_single
from config import INIT_TRAINER, SETUP_TRAINER, VERSION, CURRENT_FOLD, FOLD_NUM, WEIGHT_PATH_LIST, TTA_TIMES

import time
import torch
import numpy as np
import random

from analysis.pre_process import get_class_split_multiply,get_cross_val_by_class

RULE = {0:"AD",
        1:"NC",
        2:"MCI"
        }

def get_cross_validation(path_list, fold_num, current_fold):

    _len_ = len(path_list) // fold_num

    train_id = []
    validation_id = []
    end_index = current_fold * _len_
    start_index = end_index - _len_
    if current_fold == fold_num:
        validation_id.extend(path_list[start_index:])
        train_id.extend(path_list[:start_index])
    else:
        validation_id.extend(path_list[start_index:end_index])
        train_id.extend(path_list[:start_index])
        train_id.extend(path_list[end_index:])

    print("Train set length:", len(train_id),
          "Val set length:", len(validation_id))
    return train_id, validation_id


def get_parameter_number(net):
    total_num = sum(p.numel() for p in net.parameters())
    trainable_num = sum(p.numel() for p in net.parameters() if p.requires_grad)
    return {'Total': total_num, 'Trainable': trainable_num}


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--mode', default='train-cross', choices=["train-cross", "inf-cross", "train", "test", "inf"],
                        help='choose the mode', type=str)
    parser.add_argument('-s', '--save', default='no', choices=['no', 'n', 'yes', 'y'],
                        help='save the forward middle features or not', type=str)
    parser.add_argument('-p', '--path', default='/staff/shijun/torch_projects/PET_CLS/dataset/post_data/val/AD&CN&MCI',
                        help='the directory path of input image', type=str)
    args = parser.parse_args()
    
    label_dict = {}
    # Set data path & classifier
    
    pre_csv_path = './converter/pre_shuffle_label.csv'
    pre_label_dict = csv_reader_single(pre_csv_path, key_col='id', value_col='label')

    label_dict.update(pre_label_dict)

    if args.mode != 'train-cross' and args.mode != 'inf-cross':
        classifier = Pet_Classifier(**INIT_TRAINER)
        print(get_parameter_number(classifier.net))

    # Training with cross validation
    ###############################################
    if args.mode == 'train-cross':
        path_list = list(label_dict.keys())
        # random.shuffle(path_list)
        print("dataset length is %d"%len(path_list))

        loss_list = []
        acc_list = []

        for current_fold in range(1, FOLD_NUM+1):
            print("=== Training Fold ", current_fold, " ===")
            classifier = Pet_Classifier(**INIT_TRAINER)

            if current_fold == 0:
                print(get_parameter_number(classifier.net))

            train_path, val_path = get_cross_validation(
                path_list, FOLD_NUM, current_fold)
            # train_path, val_path = get_cross_val_by_class(
            #     path_list, FOLD_NUM, current_fold) # split by class
            SETUP_TRAINER['train_path'] = train_path
            SETUP_TRAINER['val_path'] = val_path
            SETUP_TRAINER['label_dict'] = label_dict
            SETUP_TRAINER['cur_fold'] = current_fold

            start_time = time.time()
            val_loss, val_acc = classifier.trainer(**SETUP_TRAINER)
            loss_list.append(val_loss)
            acc_list.append(val_acc)

            print('run time:%.4f' % (time.time()-start_time))

        print("Average loss is %f, average acc is %f" %
              (np.mean(loss_list), np.mean(acc_list)))
    ###############################################

    # Training
    ###############################################
    elif args.mode == 'train':
        path_list = list(label_dict.keys())
        random.shuffle(path_list)
        print("dataset length is %d"%len(path_list))

        train_path, val_path = get_cross_validation(
            path_list, FOLD_NUM, CURRENT_FOLD)
        SETUP_TRAINER['train_path'] = train_path
        SETUP_TRAINER['val_path'] = val_path
        SETUP_TRAINER['label_dict'] = label_dict
        SETUP_TRAINER['cur_fold'] = CURRENT_FOLD

        start_time = time.time()
        classifier.trainer(**SETUP_TRAINER)

        print('run time:%.4f' % (time.time()-start_time))
    ###############################################

    # Testing
    ###############################################
    elif args.mode == 'test':
        path_list = list(label_dict.keys())
        random.shuffle(path_list)
        test_path = path_list[10000:]
        save_path = './analysis/result/{}_test.csv'.format(VERSION)

        start_time = time.time()
        if args.save == 'no' or args.save == 'n':
            result, _, _ = classifier.test(test_path, label_dict)
            print('run time:%.4f' % (time.time()-start_time))
        else:
            result, feature_in, feature_out = classifier.test(
                test_path, label_dict, hook_fn_forward=True)
            print('run time:%.4f' % (time.time()-start_time))
            # save the avgpool output
            print(feature_in.shape, feature_out.shape)
            feature_dir = './analysis/mid_feature/{}'.format(VERSION)
            if not os.path.exists(feature_dir):
                os.makedirs(feature_dir)
            from converter.common_utils import save_as_hdf5
            for i in range(len(test_path)):
                name = os.path.basename(test_path[i])
                feature_path = os.path.join(feature_dir, name)
                save_as_hdf5(feature_in[i], feature_path, 'feature_in')
                save_as_hdf5(feature_out[i], feature_path, 'feature_out')
        info = {}
        info['id'] = test_path
        info['label'] = result['true']
        info['pred'] = result['pred']
        info['prob'] = result['prob']
        csv_file = pd.DataFrame(info)
        csv_file.to_csv(save_path, index=False)
    ###############################################

    # Inference
    ###############################################
    elif args.mode == 'inf':
        test_path = [os.path.join(args.path, case)
                     for case in os.listdir(args.path)]
        save_path = './analysis/result/{}_submission.csv'.format(VERSION)

        start_time = time.time()

        result = classifier.inference(test_path)
        print('run time:%.4f' % (time.time()-start_time))

        info = {}
        info['uuid'] = [os.path.splitext(os.path.basename(case))[
            0] for case in test_path]
        info['label'] = [RULE[case] for case in result['pred']]
        info['prob'] = result['prob']
        csv_file = pd.DataFrame(info)
        csv_file.to_csv(save_path, index=False)
    ###############################################

    # Inference with cross validation
    ###############################################
    elif args.mode == 'inf-cross':
        test_path = [os.path.join(args.path, case)
                     for case in os.listdir(args.path)]
        save_path_vote = './analysis/result/{}_new_submission_vote.csv'.format(VERSION)
        save_path = './analysis/result/{}_new_submission_ave.csv'.format(VERSION)

        result = {
            'pred': [],
            'vote_pred': [],
            'prob': []
        }

        all_prob_output = []
        all_vote_output = []

        start_time = time.time()
        for i, weight_path in enumerate(WEIGHT_PATH_LIST):
            print("Inference %d fold..." % (i+1))
            INIT_TRAINER['weight_path'] = weight_path
            classifier = Pet_Classifier(**INIT_TRAINER)

            prob_output, vote_output = classifier.inference_tta(
                test_path, TTA_TIMES)
            all_prob_output.append(prob_output)
            all_vote_output.append(vote_output)

        avg_output = np.mean(all_prob_output, axis=0)
        result['prob'].extend(avg_output.tolist())

        result['pred'].extend(np.argmax(avg_output, 1).tolist())
        vote_array = np.asarray(all_vote_output).astype(int)
        result['vote_pred'].extend([max(list(vote_array[:,i]),key=list(vote_array[:,i]).count) for i in range(vote_array.shape[1])])

        print('run time:%.4f' % (time.time()-start_time))

        info = {}
        info['uuid'] = [os.path.splitext(os.path.basename(case))[0] for case in test_path]
        info['label'] = [RULE[case] for case in result['pred']]
        info['prob'] = result['prob']
        csv_file = pd.DataFrame(info)
        csv_file.to_csv(save_path, index=False)

        info = {}
        info['uuid'] = [os.path.splitext(os.path.basename(case))[0] for case in test_path]
        info['label'] = [RULE[case] for case in result['vote_pred']]
        info['prob'] = result['prob']
        csv_file = pd.DataFrame(info)
        csv_file.to_csv(save_path_vote, index=False)
    ###############################################
