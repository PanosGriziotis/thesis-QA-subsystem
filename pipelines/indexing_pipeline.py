import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

import logging

from haystack.nodes import EmbeddingRetriever, PreProcessor
from transformers import AutoTokenizer
from utils.file_type_classifier import init_file_to_doc_pipeline
from document_store.initialize_document_store import document_store as DOCUMENT_STORE


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
if DOCUMENT_STORE is None:
    raise ValueError("the imported document_store is None. Please make sure that the Elasticsearch service is properly launched")

embedding_model = "panosgriz/covid_el_paraphrase-multilingual-MiniLM-L12-v2"
retriever = EmbeddingRetriever(embedding_model=embedding_model, document_store=DOCUMENT_STORE, max_seq_len=128)
tokenizer = AutoTokenizer.from_pretrained(embedding_model)

preprocessor = PreProcessor(
    clean_empty_lines=True,
    split_by = "token",
    split_length=128,
    split_respect_sentence_boundary=True,
    tokenizer=tokenizer
    )


#DOCUMENT_STORE.recreate_index = True
indexing_pipeline = init_file_to_doc_pipeline(custom_preprocessor=preprocessor)

# Update the document embeddings in the the document store using the encoding model specified in the retriever
indexing_pipeline.add_node(component=retriever, name = "DenseRetriever", inputs=["Preprocessor"])
indexing_pipeline.add_node(component=DOCUMENT_STORE, name= "DocumentStore", inputs=["DenseRetriever"])

