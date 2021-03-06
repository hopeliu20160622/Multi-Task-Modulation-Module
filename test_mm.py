""" Code for paper: A Modulation Module for Multi-task Learning with Applications in Image Retrieval: https://arxiv.org/abs/1807.06708
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import os.path
import time
import sys
import tensorflow as tf
import numpy as np
import importlib
import itertools
import argparse
import facenet
import cv2
import random
import pdb
import h5py
import math
import matplotlib as mp
import matplotlib.pyplot as plt
import scipy.io

from tensorflow.python.ops import data_flow_ops

def main(args):
    network = importlib.import_module(args.model_def)

    subdir = datetime.strftime(datetime.now(), '%Y%m%d-%H%M%S') + args.experiment_name
    log_dir = os.path.join(os.path.expanduser(args.logs_base_dir), subdir)
    if not os.path.isdir(log_dir):  # Create the log directory if it doesn't exist
        os.makedirs(log_dir)
    model_dir = os.path.join(os.path.expanduser(args.models_base_dir), subdir)
    if not os.path.isdir(model_dir):  # Create the model directory if it doesn't exist
        os.makedirs(model_dir)

    # Write arguments to a text file
    facenet.write_arguments_to_file(args, os.path.join(log_dir, 'arguments.txt'))
        
    # Store some git revision info in a text file in the log directory
    src_path,_ = os.path.split(os.path.realpath(__file__))
    facenet.store_revision_info(src_path, log_dir, ' '.join(sys.argv))

    np.random.seed(seed=args.seed)
    class_name = ['smile','oval_face','5_ocloc_shadow','bald','archied_eyebrows','big_lips', 'big_nose']
    class_num = len(class_name)
    class_index = [31,25,0,4,1,6,7]


    all_image_list = []
    all_label_list = []
    for i in range(class_num):

        image_list = []
        label_list = []

        train_set = facenet.get_sub_category_dataset(args.data_dir, class_index[i])

        image_list_p, label_list_p = facenet.get_image_paths_and_labels_triplet(train_set[0], args)
        image_list_n, label_list_n = facenet.get_image_paths_and_labels_triplet(train_set[1], args)

        image_list.append(image_list_p)
        image_list.append(image_list_n)
        label_list.append(label_list_p)
        label_list.append(label_list_n)

        all_image_list.append(image_list)
        all_label_list.append(label_list)

    print('Model directory: %s' % model_dir)
    print('Log directory: %s' % log_dir)
    if args.pretrained_model:
        print('Pre-trained model: %s' % os.path.expanduser(args.pretrained_model))
        
    image_size = args.image_size
    batch_size = args.batch_size
    with tf.Graph().as_default():
        tf.set_random_seed(args.seed)
        global_step = tf.Variable(0, trainable=False)

        # Placeholder for the learning rate
        learning_rate_placeholder = tf.placeholder(tf.float32, name='learning_rate')
        
        batch_size_placeholder = tf.placeholder(tf.int32, name='batch_size')
        
        phase_train_placeholder = tf.placeholder(tf.bool, name='phase_train')


        # image_paths_placeholder = tf.placeholder(tf.string, shape=(None,3), name='image_paths')
        image_placeholder = tf.placeholder(tf.float32, shape=(batch_size, image_size, image_size,3), name='images')
        labels_placeholder = tf.placeholder(tf.int64, shape=(batch_size,3), name='labels')

        code_placeholder = tf.placeholder(tf.float32, shape=(batch_size,class_num,1,1), name='code')

        image_batch = normalized_image(image_placeholder)
        code_batch = code_placeholder

        control_code = tf.tile(code_placeholder,[1,1,args.embedding_size,1])
        mask_array = np.ones((1 ,class_num,args.embedding_size,1),np.float32)

        # for i in range(class_num):
        #     mask_array[:,i,(args.embedding_size/class_num)*i:(args.embedding_size/class_num)*(i+1)] = 1


        mask_tensor = tf.get_variable('mask', dtype=tf.float32, trainable=args.learned_mask, initializer=tf.constant(mask_array))
        mask_tensor = tf.tile(mask_tensor,[batch_size,1,1,1])
        control_code = tf.tile(code_placeholder,[1,1,args.embedding_size,1])

        mask_out = tf.multiply(mask_tensor, control_code)
        mask_out = tf.reduce_sum(mask_out,axis=1)
        mask_out = tf.squeeze(mask_out)
        mask_out = tf.nn.relu(mask_out)

        mask0_array = np.ones((1, class_num, 128, 1), np.float32)
        mask0_tensor = tf.get_variable('mask0', dtype=tf.float32, trainable=args.learned_mask,
                                      initializer=tf.constant(mask0_array))
        mask0_tensor = tf.tile(mask0_tensor, [batch_size, 1, 1, 1])
        control0_code = tf.tile(code_placeholder,[1,1,128,1])

        mask0_out = tf.multiply(mask0_tensor, control0_code)
        mask0_out = tf.reduce_sum(mask0_out, axis=1)
        mask0_out = tf.squeeze(mask0_out)
        mask0_out = tf.nn.relu(mask0_out)
        mask0_out = tf.expand_dims(mask0_out,1)
        mask0_out = tf.expand_dims(mask0_out,1)

        mask1_array = np.ones((1, class_num, 128, 1), np.float32)
        mask1_tensor = tf.get_variable('mask1', dtype=tf.float32, trainable=args.learned_mask,
                                      initializer=tf.constant(mask1_array))
        mask1_tensor = tf.tile(mask1_tensor, [batch_size, 1, 1, 1])
        control1_code = tf.tile(code_placeholder,[1,1,128,1])

        mask1_out = tf.multiply(mask1_tensor, control1_code)
        mask1_out = tf.reduce_sum(mask1_out, axis=1)
        mask1_out = tf.squeeze(mask1_out)
        mask1_out = tf.nn.relu(mask1_out)
        mask1_out = tf.expand_dims(mask1_out,1)
        mask1_out = tf.expand_dims(mask1_out,1)


        # Build the inference graph
        prelogits, features = network.inference(image_batch, mask0_out, mask1_out, args.keep_probability,
            phase_train=phase_train_placeholder, bottleneck_layer_size=args.embedding_size,
            weight_decay=args.weight_decay)

        embeddings_pre = tf.multiply(mask_out, prelogits)

        embeddings = tf.nn.l2_normalize(embeddings_pre, 1, 1e-10, name='embeddings')
        anchor_index = list(range(0,batch_size,3))
        positive_index = list(range(1,batch_size,3))
        negative_index = list(range(2,batch_size,3))

        a_indice = tf.constant(np.array(anchor_index))
        p_indice = tf.constant(np.array(positive_index))

        n_indice = tf.constant(np.array(negative_index))

        anchor = tf.gather(embeddings,a_indice)
        positive = tf.gather(embeddings,p_indice)
        negative = tf.gather(embeddings,n_indice)

        triplet_loss = facenet.triplet_loss(anchor, positive, negative, args.alpha)
        
        learning_rate = tf.train.exponential_decay(learning_rate_placeholder, global_step,
            args.learning_rate_decay_epochs*args.epoch_size, args.learning_rate_decay_factor, staircase=True)
        tf.summary.scalar('learning_rate', learning_rate)

        # Calculate the total losses
        regularization_losses = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)
        total_loss = tf.add_n([triplet_loss] + regularization_losses, name='total_loss')

        # Build a Graph that trains the model with one batch of examples and updates the model parameters
        train_op = facenet.train(total_loss, global_step, args.optimizer, 
            learning_rate, args.moving_average_decay, tf.global_variables())
        
        # Create a saver
        trainable_variables = tf.trainable_variables()
        saver = tf.train.Saver(trainable_variables, max_to_keep=3)

        # Build the summary operation based on the TF collection of Summaries.
        summary_op = tf.summary.merge_all()

        # Start running operations on the Graph.
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=args.gpu_memory_fraction)
        sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options))        

        # Initialize variables
        sess.run(tf.global_variables_initializer(), feed_dict={phase_train_placeholder:True})
        sess.run(tf.local_variables_initializer(), feed_dict={phase_train_placeholder:True})

        summary_writer = tf.summary.FileWriter(log_dir, sess.graph)
        coord = tf.train.Coordinator()
        tf.train.start_queue_runners(coord=coord, sess=sess)

        with sess.as_default():

            if args.pretrained_model:
                print('Restoring pretrained model: %s' % args.pretrained_model)
                saver.restore(sess, os.path.expanduser(args.pretrained_model))

            # Training and validation loop
            epoch = 0
            Accuracy = [0]
            while epoch < args.max_nrof_epochs:
                step = sess.run(global_step, feed_dict=None)
                # epoch = step // args.epoch_size
                # Train for one epoch
                code_list = []
                triplets_list = []
                if (epoch+1)%args.lr_epoch == 0:
                    args.learning_rate = 0.1*args.learning_rate
                if args.random_trip:

                 for i in range(class_num):

                    code = np.zeros((batch_size, class_num, 1, 1), np.float32)
                    _class = i
                    code[:, _class, :, :] = 1

                    Triplets = triplet_random(args, sess, all_image_list[i], all_image_list, epoch, image_placeholder,
                                              batch_size_placeholder, learning_rate_placeholder,
                                              phase_train_placeholder, global_step,
                                              embeddings, total_loss, train_op, summary_op, summary_writer,
                                              args.learning_rate_schedule_file,
                                              args.embedding_size, anchor, positive, negative, triplet_loss)
                    triplets_list.append(Triplets)
                    code_list.append(code)



                for i in range(class_num):
                   Accuracy = test(args, sess, image_list, epoch, image_placeholder,code_placeholder,
                          batch_size_placeholder, learning_rate_placeholder, phase_train_placeholder, global_step,
                          embeddings, total_loss, train_op, summary_op, summary_writer, args.learning_rate_schedule_file,
                          args.embedding_size, anchor, positive, negative, triplet_loss, triplets_list, Accuracy, features,
                          mask0_out, mask1_out, mask_out, class_name, i)
		     
                # Save variables and the metagraph if it doesn't exist already
    sess.close()
    return model_dir

def normalized_image(img_sym, resnet_mean = [102.9801, 115.9465, 122.7717]):
    return tf.scalar_mul(0.0078125, tf.subtract(tf.cast(img_sym, tf.float32), tf.constant(resnet_mean)))

def triplet_random(args, sess, dataset, image_list, epoch, image_placeholder,
          batch_size_placeholder, learning_rate_placeholder, phase_train_placeholder, global_step,
          embeddings, loss, train_op, summary_op, summary_writer, learning_rate_schedule_file,
          embedding_size, anchor, positive, negative, triplet_loss):

    batch_number = 0

    images_data = h5py.File('./data/train_classification.h5')
    images = images_data['data']

    image_list_p = dataset[0]
    image_list_n = dataset[1]


    random.shuffle(image_list_n)

    start_time = time.time()
    nrof_examples = len(image_list_p)
    triplets = []
    nrof_neg = len(image_list_n)

    for i in range(nrof_examples):

        a_idx = i
        p_idx = np.random.randint(i,nrof_examples)
        n_idx = np.random.randint(nrof_neg)
        triplets.append((image_list_p[a_idx], image_list_p[p_idx], image_list_n[n_idx]))



    return triplets


def get_code_batch(code, triplets, batch_size, batch_index):

    nrof_examples = len(triplets)

    j = batch_index * batch_size % nrof_examples

    if j + batch_size < nrof_examples:
        code_array = code[j: j+ batch_size]

    else:
        code_array1 = code[j:nrof_examples]
        code_array2 = code[0:batch_size - (nrof_examples-j)]
        code_array = np.vstack((code_array1,code_array2))
    return code_array
def test(args, sess, dataset, epoch, image_placeholder, code_placeholder,
          batch_size_placeholder, learning_rate_placeholder, phase_train_placeholder, global_step,
          embeddings, loss, train_op, summary_op, summary_writer, learning_rate_schedule_file,
          embedding_size, anchor, positive, negative, triplet_loss, triplet_list, Accuracy, features,res4_mask, res5_mask,
          fc_mask, name_list, class_index):

    test_hdf5_dir = '../data/test_triplet_' + name_list[class_index]+'.h5'
    print(test_hdf5_dir)
    images_data = h5py.File(test_hdf5_dir)
    images_a = images_data['anchors']
    images_p = images_data['positive']
    images_n = images_data['negative']

    nrof_images = images_a.shape[0]
    nrof_batches = int(math.ceil(1.0 * nrof_images / (args.batch_size/3)))

    batch_number = 0
    correct_num = 0
    class_num = len(triplet_list)
    batch_size = args.batch_size

    print('load mean image done!')
    code_list = []
    for i in range(class_num):
        _class = i
        code = np.zeros((batch_size, class_num, 1, 1), np.float32)
        code[:, _class, :, :] = 1
        code_list.append(code)
 

    check = 0
    while batch_number < nrof_batches:

            # batch_size = min(nrof_images - batch_number * args.batch_size, args.batch_size)
            batch_inter = int(batch_size/3)
            if (nrof_images - batch_number*batch_inter) < batch_inter:
                check = check + 1
                anchor_array1 = images_a[batch_number * batch_inter:nrof_images]
                anchor_array2 = images_a[0:batch_inter - (nrof_images - batch_number * batch_inter)]
                anchor_array = np.vstack((anchor_array1,anchor_array2))

                positive_array1 = images_p[batch_number * batch_inter:nrof_images]
                positive_array2 = images_p[0:batch_inter - (nrof_images - batch_number * batch_inter)]
                positive_array = np.vstack((positive_array1, positive_array2))

                negative_array1 = images_n[batch_number * batch_inter:nrof_images]
                negative_array2 = images_n[0:batch_inter - (nrof_images - batch_number * batch_inter)]
                negative_array = np.vstack((negative_array1, negative_array2))
            else:
                anchor_array = images_a[batch_number*batch_inter:batch_number*batch_inter + batch_inter]
                positive_array = images_p[batch_number * batch_inter:batch_number * batch_inter + batch_inter]
                negative_array = images_n[batch_number * batch_inter:batch_number * batch_inter + batch_inter]

            image_array = np.vstack((anchor_array,positive_array,negative_array))
       

            feed_dict = {batch_size_placeholder: batch_size, phase_train_placeholder: False, image_placeholder: image_array, code_placeholder: code_list[class_index]}

            emb = sess.run(embeddings, feed_dict=feed_dict)

            batch_number += 1


            for i in range(int(batch_size/3)):
                an_feature = emb[i,:]
                pos_feature = emb[i+batch_size/3, :]
                neg_feature = emb[i+2*batch_size/3, :]

                if np.sum(np.square(an_feature - pos_feature),0) < np.sum(np.square(an_feature - neg_feature),0):
                    correct_num = correct_num + 1
    nrof_images = nrof_batches*batch_inter
    accuracy = correct_num/nrof_images
    Accuracy.append(accuracy)
    print('accuracy:', Accuracy)
    return Accuracy





def save_variables_and_metagraph(sess, saver, summary_writer, model_dir, model_name, step):
    # Save the model checkpoint
    print('Saving variables')
    start_time = time.time()
    checkpoint_path = os.path.join(model_dir, 'model-%s.ckpt' % model_name)
    saver.save(sess, checkpoint_path, global_step=step, write_meta_graph=False)
    save_time_variables = time.time() - start_time
    print('Variables saved in %.2f seconds' % save_time_variables)
    metagraph_filename = os.path.join(model_dir, 'model-%s.meta' % model_name)
    save_time_metagraph = 0  
    if not os.path.exists(metagraph_filename):
        print('Saving metagraph')
        start_time = time.time()
        saver.export_meta_graph(metagraph_filename)
        save_time_metagraph = time.time() - start_time
        print('Metagraph saved in %.2f seconds' % save_time_metagraph)
    summary = tf.Summary()
    #pylint: disable=maybe-no-member
    summary.value.add(tag='time/save_variables', simple_value=save_time_variables)
    summary.value.add(tag='time/save_metagraph', simple_value=save_time_metagraph)
    summary_writer.add_summary(summary, step)
  
  
def get_learning_rate_from_file(filename, epoch):
    with open(filename, 'r') as f:
        for line in f.readlines():
            line = line.split('#', 1)[0]
            if line:
                par = line.strip().split(':')
                e = int(par[0])
                lr = float(par[1])
                if e <= epoch:
                    learning_rate = lr
                else:
                    return learning_rate
    

def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--is_training', type=bool,default= True)
    parser.add_argument('--lr_epoch', type=int,default= 30)
    parser.add_argument('--random_trip', type=bool, default= False)
    parser.add_argument('--experiment_name', type=str,default='triplet')
    parser.add_argument('--category', type=int, default=31)
    parser.add_argument('--learned_mask', type=bool, default=True)
    parser.add_argument('--logs_base_dir', type=str, 
        help='Directory where to write event logs.', default='~/logs/facenet')
    parser.add_argument('--models_base_dir', type=str,
        help='Directory where to write trained models and checkpoints.', default='~/models/facenet')
    parser.add_argument('--gpu_memory_fraction', type=float,
        help='Upper bound on the amount of GPU memory that will be used by the process.', default=1.0)
    parser.add_argument('--pretrained_model', type=str,
        help='Load a pretrained model before training starts.', default = '')
    parser.add_argument('--data_dir', type=str,
        help='Path to the data directory containing aligned face patches. Multiple directories are separated with colon.',
        default='')
    parser.add_argument('--model_def', type=str,
        help='Model definition. Points to a module containing the definition of the inference graph.', default='models.inception_resnet_v1')
    parser.add_argument('--max_nrof_epochs', type=int,
        help='Number of epochs to run.', default=40)
    parser.add_argument('--batch_size', type=int,
        help='Number of images to process in a batch.', default=90)
    parser.add_argument('--image_size', type=int,
        help='Image size (height, width) in pixels.', default=160)
    parser.add_argument('--epoch_size', type=int,
        help='Number of batches per epoch.', default=1000)
    parser.add_argument('--alpha', type=float,
        help='Positive to negative triplet distance margin.', default=0.2)
    parser.add_argument('--num_attribute', type=int,
        help='', default=1)
    parser.add_argument('--embedding_size', type=int,
        help='Dimensionality of the embedding.', default=128)
    parser.add_argument('--keep_probability', type=float,
        help='Keep probability of dropout for the fully connected layer(s).', default=1.0)
    parser.add_argument('--weight_decay', type=float,
        help='L2 weight regularization.', default=0.0)
    parser.add_argument('--optimizer', type=str, choices=['ADAGRAD', 'ADADELTA', 'ADAM', 'RMSPROP', 'MOM'],
        help='The optimization algorithm to use', default='ADAGRAD')
    parser.add_argument('--learning_rate', type=float,
        help='Initial learning rate. If set to a negative value a learning rate ' +
        'schedule can be specified in the file "learning_rate_schedule.txt"', default=0.1)
    parser.add_argument('--learning_rate_decay_epochs', type=int,
        help='Number of epochs between learning rate decay.', default=100)
    parser.add_argument('--learning_rate_decay_factor', type=float,
        help='Learning rate decay factor.', default=1.0)
    parser.add_argument('--moving_average_decay', type=float,
        help='Exponential decay for tracking of training parameters.', default=0.9999)
    parser.add_argument('--seed', type=int,
        help='Random seed.', default=666)
    return parser.parse_args(argv)
  

if __name__ == '__main__':
    main(parse_arguments(sys.argv[1:]))
