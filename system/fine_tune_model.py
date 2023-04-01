from haystack.nodes import FARMReader
import os
from haystack.nodes.label_generator import PseudoLabelGenerator
from typing import List
from haystack.utils import EarlyStopping
import logging
import shutil

os.environ['CUDA_VISIBLE_DEVICES'] = '0'
logging.basicConfig(level=logging.INFO)

def fine_tune_reader_model (model_name_or_path, data_dir, train_filename,  save_dir, use_gpu=True):
    
    # Create output directory if doesn't exist already
    try:
        os.path.isdir(save_dir)
    except FileNotFoundError:
        os.mkdir(save_dir)

    reader = FARMReader(model_name_or_path = model_name_or_path)
    #early_stopping = EarlyStopping(metric='f1',save_dir=save_dir, mode='max')
      
    try:
      reader.train(
          data_dir = data_dir,
          train_filename = train_filename,
          use_gpu = use_gpu,
          batch_size= 12,
          n_epochs = 1,
          max_seq_len = 384,
          save_dir  = save_dir,
          num_processes = 1,
          )
      print (f'Model fine-tuning done. Model saved in directory: {save_dir}')
    except Exception as e:
      print (e)

def fine_tune_dense_retriever(document_store, retriever):
    query_doc_pairs  = []
    with open ('data/who/queries1.el.txt', 'r', encoding='utf-8') as q_file:
        with open ('data/who/answers1.el.txt', 'r', encoding='utf-8') as a_file:
            queries = q_file.readlines()
            docs = a_file.readlines()
        for q, d in zip (queries,docs):
            query_doc_pairs.append({"question": q , "document": d})

    psg = PseudoLabelGenerator(query_doc_pairs, retriever, cross_encoder_model_name_or_path="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",  batch_size=32, top_k=10)
    output, pipe_id = psg.run(documents=document_store.get_all_documents(index="documents"))
    retriever.train(output["gpl_labels"])
    retriever.save("adapted_retriever")
    
if __name__ == '__main__':
  model = "deepset/xlm-roberta-base-squad2"
  data_dir = '../data/deepset_covid_qa/dataset'
  train_filename = 'COVID-QA copy-el.json'
  save_dir = './model'
  logging.info('Fine tuning model on SQuAD format dataset...')
  fine_tune_reader_model(model_name_or_path = model, data_dir = data_dir, train_filename= train_filename, save_dir=save_dir)
