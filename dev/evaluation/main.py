from typing import List, Optional, Dict, Any, Union, Callable, Tuple
from tqdm import tqdm
import os
import sys
import tempfile
import json
from pathlib import Path
from typing import List, Optional
from haystack import Pipeline
from haystack.document_stores import InMemoryDocumentStore, ElasticsearchDocumentStore
from haystack.nodes import PreProcessor
from haystack.nodes import FARMReader, EmbeddingRetriever, DensePassageRetriever, BM25Retriever, SentenceTransformersRanker
from transformers import AutoTokenizer

import requests
import logging
from datasets import load_dataset

logging.basicConfig(format="%(levelname)s - %(name)s -  %(message)s", level=logging.INFO)
logging.getLogger("haystack").setLevel(logging.INFO)

tokenizer = AutoTokenizer.from_pretrained("nlpaueb/bert-base-greek-uncased-v1")

def index_eval_labels(document_store, eval_filename: str):
    """
    Index evaluation labels into the document store.

    document_store (DocumentStore): The document store instance.
    eval_filename (str): The path to the evaluation dataset file.
    """
    index = 'eval_docs'
    label_index = 'label_index'
    document_store.delete_index(index=index)
    document_store.delete_index (index=label_index)

    
    label_preprocessor = PreProcessor(
        split_by="word",
        split_length=128,
        split_respect_sentence_boundary=False,
        clean_empty_lines=False,
        clean_whitespace=False,
        language='el'
    )
 
    document_store.add_eval_data(
        filename=eval_filename,
        doc_index=index,
        label_index=label_index,
        preprocessor=label_preprocessor,
    )

def get_eval_labels_and_paths(document_store, tempdir) -> Tuple[List[dict], List[Path]]:
    """
    Retrieve evaluation labels and file paths for documents in the document store.

    document_store (DocumentStore): The document store instance.
    tempdir: A temporary directory instance for storing document files.
    """
    file_paths = []
    docs = document_store.get_all_documents()

    for doc in docs:
        file_name = f"{doc.id}.txt"
        file_path = Path(tempdir.name) / file_name
        file_paths.append(file_path)
        
        with open(file_path, "w") as f:
            f.write(doc.content)
    
    evaluation_set_labels = document_store.get_all_labels_aggregated(drop_negative_labels=True, drop_no_answers=True)

    return evaluation_set_labels, file_paths


def evaluate_retriever(
        retriever:Union[BM25Retriever, EmbeddingRetriever, DensePassageRetriever],
        document_store: ElasticsearchDocumentStore,
        eval_filename: str,
        top_k: Optional[int] = None,
        top_k_list: Optional[List[int]] = None) -> Dict[int, dict]:
    
    """
    Evaluate a retriever on a SQuAD format evaluation dataset. 
    If a top_k_list is provided, the evaluation is iterative for each top_k value, generating one evaluation report for each value.
    """

    index_eval_labels(document_store, eval_filename)
    if isinstance(retriever, (EmbeddingRetriever, DensePassageRetriever)):
        document_store.update_embeddings(retriever= retriever,index="eval_docs")

    if top_k_list is not None:
        reports = {}
        for k in tqdm(top_k_list):
            reports[k] = retriever.eval(label_index="label_index", doc_index="eval_docs", top_k=k, document_store=document_store)
        return reports
    else:
        if top_k is None:
            top_k = retriever.top_k
        report = retriever.eval(label_index=document_store.label_index, doc_index=document_store.index, top_k=top_k, document_store=document_store)
        return report

def evaluate_reader(
        reader:FARMReader,
        eval_filename: str,
        top_k: Optional[int] = None,
        top_k_list: Optional[List[int]] = None) -> Dict[int, dict]:
    """
    Evaluate reader on a SQuAD format evaluation dataset.
    """

    data_dir = os.path.dirname(eval_filename)

    if top_k_list is not None:
        reports = {}
        for k in tqdm(top_k_list, desc="Evaluating reader"):
            reader.top_k = k
            reports[k] = reader.eval_on_file(data_dir, eval_filename)
        return reports
    elif top_k is not None:
        reader.top_k = top_k
        return reader.eval_on_file(data_dir, eval_filename)
    else:
        return reader.eval_on_file(data_dir, eval_filename)

def evaluate_retriever_ranker_pipeline(
        retriever:Union[BM25Retriever, EmbeddingRetriever, DensePassageRetriever],
        ranker:SentenceTransformersRanker,
        document_store: ElasticsearchDocumentStore,
        eval_filename: str,
        top_k: Optional[int] = None,
        top_k_list: Optional[List[int]] = None) -> Dict[int, dict]:

    index_eval_labels(document_store, eval_filename)
    if isinstance(retriever, (EmbeddingRetriever, DensePassageRetriever)):
        document_store.update_embeddings(retriever=retriever,index="eval_docs")
    
    
    p = Pipeline()
    p.add_node(retriever, name="Retriever", inputs=["Query"])
    p.add_node(ranker, name="Ranker", inputs=["Retriever"])
    
    #documents = document_store.get_all_documents(index="eval_docs", return_embedding=True)
    labels = document_store.get_all_labels_aggregated(index="label_index")

    if top_k_list is not None:
        reports = {}
        for top_k in tqdm(top_k_list):

            report = p.eval(
                labels=labels,
                params={"top_k": top_k}
                )
            
            reports[top_k] = report.calculate_metrics()
        return reports

    report = p.eval(labels=labels,
            add_isolated_node_eval=True
            )
    return report


    
def run_experiment(exp_name: str, eval_filename: str, pipeline_path: str, run_name: str, query_params={"Retriever": {"top_k": 10}, "Reader": {"top_k": 5}}):
    """
    Run an experiment with the given parameters.

    exp_name: The name of the experiment.
    eval_filename: The path to the evaluation dataset file.
    pipeline_path: The path to the pipeline YAML file.
    run_name: The name of the experiment run.
    query_params: Parameters for query pipeline
    """

    # Create a temporary directory and document store to get eval data file paths
    temp_dir = tempfile.TemporaryDirectory()
    
    eval_ds = InMemoryDocumentStore()

    index_eval_labels(eval_ds, eval_filename)

    evaluations_set_labels, file_paths = get_eval_labels_and_paths(eval_ds, temp_dir)
    
    # Load pipelines from YAML file
    query_pipeline = Pipeline.load_from_yaml(path=Path(pipeline_path), pipeline_name='query')
    index_pipeline = Pipeline.load_from_yaml(path=Path(pipeline_path), pipeline_name='indexing')
    
    # TODO define the index in the yaml pipelines for evaluation (?). Build a seperate index pipeline
    # Get document store from index pipeline and delete existing documents
    
    # Execute experiment run
    Pipeline.execute_eval_run(
        index_pipeline=index_pipeline,
        query_pipeline=query_pipeline,
        evaluation_set_labels=evaluations_set_labels,
        corpus_file_paths=file_paths,
        experiment_name=exp_name,
        experiment_run_name=run_name,
        evaluation_set_meta=os.path.basename(eval_filename),
        add_isolated_node_eval=True,
        experiment_tracking_tool="mlflow",
        experiment_tracking_uri="http://localhost:5000",
        query_params=query_params,
        sas_model_name_or_path="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        sas_batch_size=32,
        sas_use_gpu=True,
        reuse_index=False
    )
    
    temp_dir.cleanup()
    