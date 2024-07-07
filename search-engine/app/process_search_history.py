from concrete.ml.sklearn import NeuralNetRegressor
from concrete.ml.deployment import FHEModelDev, FHEModelClient, FHEModelServer
import numpy as np
import torch.nn as nn
from collections import Counter
import re
from sklearn.preprocessing import normalize
from sklearn.model_selection import train_test_split
from nltk.stem.porter import PorterStemmer
import os
import requests
import json
import base64
import logging 
from .predict import get_new_prediction, display_predictions, clean_normalize_predictions
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KEYWORDS_FILENAME = "./tmp/keywords.txt"
STEMMED_KEYWORDS_FILENAME = "./tmp/stemmed_keywords.json"
SERVER_ADDRESS = "http://server:5001/"
FHE_FILE_PATH = "./fhe"

REGEX = re.compile('[^a-zA-Z ]')
STEMMER = PorterStemmer()
client = FHEModelClient(path_dir=FHE_FILE_PATH)
generate_key = lambda: client.get_serialized_evaluation_keys()
serialized_evaluation_keys = generate_key()


def init_keywords():
    get_keywords_if_not_got()
    process_keywords()
    
def is_keywords_got():
    return os.path.exists(KEYWORDS_FILENAME)
    
def get_keywords_if_not_got():
    if is_keywords_got():
        logger.info("Keywords have already been got. Skipping.")
        return

    endpoint = f"{SERVER_ADDRESS}/get_keywords"
    try:
        response = requests.get(endpoint)
        if response.status_code == 200:
            keywords = response.json().get("keywords")
            logger.info("Received keywords from server: %s", keywords)

            os.makedirs(os.path.dirname(KEYWORDS_FILENAME), exist_ok=True)
            with open(KEYWORDS_FILENAME, 'w') as file:
                json.dump(keywords, file)
            logger.info(f"Keywords file '{KEYWORDS_FILENAME}' has been created and written to.")
        else:
            logger.warning(f"Server returned status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to connect to server: {e}")
        
def process_keywords():
    with open(KEYWORDS_FILENAME, 'r') as file:
        keywords = json.load(file)
    stemmed_keywords = list(map(STEMMER.stem, keywords))
    logger.info("stemmed_keywords: %s", stemmed_keywords)
    with open(STEMMED_KEYWORDS_FILENAME, 'w') as file:
        json.dump(stemmed_keywords, file)
    logger.info(f"Stemmed Keywords file '{STEMMED_KEYWORDS_FILENAME}' has been created and written to.")    

# Converts search history to encrypted normalized vector
def process_search_history(search_history): 
    try:
        text = " ".join(search_history)
        with open(STEMMED_KEYWORDS_FILENAME, 'r') as file:
            stemmed_keywords = json.load(file)
        
        logger.info("Stemmed Keywords in processing: %s", stemmed_keywords)
        text = text.replace("-", " ")
        text = REGEX.sub('', text)
        text = text.lower()
        text = text.split()
        text = list(map(STEMMER.stem, text))
        freq = Counter(text)

        vector = [freq[category] for category in stemmed_keywords]
        normalized_vector = normalize(np.array(vector).reshape((1, -1)), norm="l1", axis=1)
        
        logger.info("normalized vector: %s", normalized_vector)
        encrypted_vector = client.quantize_encrypt_serialize(normalized_vector)
        return encrypted_vector
    except Exception as e:
        logger.error(e)
        raise

def send_search_history_to_server(search_history):
    try:
        endpoint = f"{SERVER_ADDRESS}/recieve_search_history"
        headers = {'Content-Type': 'application/json'}

        search_history_str = base64.b64encode(search_history).decode('utf-8')
        payload = {"search_history": search_history_str}

        response = requests.post(endpoint, json=payload, headers=headers)
        if response.status_code == 200:
            raw_bytes = base64.b64decode(response.json()["prediction"])
            categories = response.json()["categories"]

            # Decrypt vector
            try: 
                vector = client.deserialize_decrypt_dequantize(raw_bytes)
                vector = vector[0].tolist()
            except Exception as e:
                logger.error(str(e))
                raise

            predictions = dict(zip(categories, vector))
            predictions = clean_normalize_predictions(predictions)
            # Log predictions
            logger.info("Predictions received:")
            display_predictions(predictions)

            new_predictions = get_new_prediction(predictions)
            logger.info("New predictions received:")
            display_predictions(new_predictions)

            return predictions
        else: 
            logger.warning(f"Server returned status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to connect to server: {e}")