import argparse
import requests
import re
import os
from urllib.parse import urljoin
from requests.auth import HTTPBasicAuth

# Configuration Defaults
DEFAULT_RAGFLOW_URL = "http://localhost:8000" # RagFlow Backend (Host) usually 9380 or 8000 depending on docker port mapping. API is usually on 9380 internal or exposed port. 
# Looking at docker-compose, SVR_HTTP_PORT:9380 is mapped. Backend usually exposes /api/v1.
# Confirmed from docker-compose: 
# ragflow-cpu: ports: "... - 9380:9380"
# So default should be http://localhost:9380

DEFAULT_DATA_SERVER_URL = "http://localhost:8081" # Nginx exposed on host
DEFAULT_DATA_USER = "ragflow"
DEFAULT_DATA_PASS = "ragflow"

def get_dataset_id(base_url, api_key, dataset_name):
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(f"{base_url}/api/v1/datasets", headers=headers, params={"name": dataset_name, "page": 1, "page_size": 100})
    if response.status_code != 200:
        print(f"Error getting datasets: {response.text}")
        return None
    data = response.json()
    if data['code'] == 0 and data['data']:
        for ds in data['data']:
            if ds['name'] == dataset_name:
                return ds['id']
    return None

def create_dataset(base_url, api_key, dataset_name):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "name": dataset_name,
        "permission": "me",
        "chunk_method": "naive",
        "parser_config": {"chunk_token_num": 512, "delimiter": "\\n"}
    }
    response = requests.post(f"{base_url}/api/v1/datasets", headers=headers, json=payload)
    if response.status_code == 200:
        data = response.json()
        if data['code'] == 0:
             return data['data']['id']
    print(f"Error creating dataset: {response.text}")
    return None

def fetch_file_list(data_url, auth):
    try:
        response = requests.get(data_url, auth=auth)
        if response.status_code != 200:
            print(f"Failed to fetch data server index: {response.status_code}")
            return []
        
        # Simple regex to find links to .md files
        # Nginx autoindex usually looks like <a href="filename.md">filename.md</a>
        files = re.findall(r'href="([^"]+\.md)"', response.text)
        return list(set(files)) # Unique
    except Exception as e:
        print(f"Error fetching file list: {e}")
        return []

def upload_file(base_url, api_key, dataset_id, file_url, file_name, auth):
    # Download content first
    print(f"Downloading {file_name}...")
    try:
        file_resp = requests.get(file_url, auth=auth)
        if file_resp.status_code != 200:
            print(f"Failed to download {file_name}")
            return
        
        # Save temp file
        temp_path = f"temp_{file_name}"
        with open(temp_path, "wb") as f:
            f.write(file_resp.content)
        
        # Upload to RagFlow
        print(f"Uploading {file_name} to Dataset {dataset_id}...")
        url = f"{base_url}/api/v1/datasets/{dataset_id}/documents"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        with open(temp_path, "rb") as f:
            files = {'file': (file_name, f)}
            response = requests.post(url, headers=headers, files=files)
        
        if response.status_code == 200 and response.json().get('code') == 0:
            print(f"Successfully uploaded {file_name}")
        else:
            print(f"Failed to upload {file_name}: {response.text}")
        
        # Cleanup
        os.remove(temp_path)
            
    except Exception as e:
        print(f"Error processing {file_name}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Ingest Markdown files from Data Server to RagFlow")
    parser.add_argument("--api-key", required=True, help="RagFlow API Key")
    parser.add_argument("--dataset-name", default="SCRAPY_MUNDO", help="Target Dataset Name")
    parser.add_argument("--ragflow-url", default="http://localhost:9380", help="RagFlow API Base URL")
    parser.add_argument("--data-url", default=DEFAULT_DATA_SERVER_URL, help="Data Server URL")
    
    args = parser.parse_args()
    
    auth = HTTPBasicAuth(DEFAULT_DATA_USER, DEFAULT_DATA_PASS)
    
    print(f"Connecting to RagFlow at {args.ragflow_url}...")
    dataset_id = get_dataset_id(args.ragflow_url, args.api_key, args.dataset_name)
    
    if not dataset_id:
        print(f"Dataset '{args.dataset_name}' not found. Creating it...")
        dataset_id = create_dataset(args.ragflow_url, args.api_key, args.dataset_name)
        if not dataset_id:
            print("Failed to create dataset. Exiting.")
            return

    print(f"Target Dataset ID: {dataset_id}")
    
    file_list = fetch_file_list(args.data_url, auth=auth)
    print(f"Found {len(file_list)} files on Data Server.")
    
    for file_name in file_list:
        file_url = urljoin(args.data_url, file_name)
        upload_file(args.ragflow_url, args.api_key, dataset_id, file_url, file_name, auth)

    # Trigger Parsing for any unparsed files
    trigger_parsing_for_dataset(args.ragflow_url, args.api_key, dataset_id)

def trigger_parsing_for_dataset(base_url, api_key, dataset_id):
    print(f"Checking for unparsed documents in Dataset {dataset_id}...")
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # List documents (page size 100 max usually, loop if needed, but keeping simple for now)
    # We filter by run=0 (UNSTART) or run=UNSTART if API supports it, or just fetch all and filter.
    # API ref: run: ["0", "1", ...] or ["UNSTART", ...]
    params = {"page": 1, "page_size": 100, "run": "UNSTART"} 
    
    try:
        response = requests.get(f"{base_url}/api/v1/datasets/{dataset_id}/documents", headers=headers, params=params)
        if response.status_code != 200:
            print(f"Error listing documents: {response.text}")
            return

        data = response.json()
        if data['code'] != 0:
            print(f"Error listing documents API: {data}")
            return

        docs = data['data']['docs']
        if not docs:
            print("No unparsed documents found.")
            return
            
        doc_ids = [d['id'] for d in docs]
        print(f"Found {len(doc_ids)} unparsed documents. Triggering parsing...")
        
        # Parse endpoint
        parse_url = f"{base_url}/api/v1/datasets/{dataset_id}/chunks"
        payload = {"document_ids": doc_ids}
        
        parse_resp = requests.post(parse_url, headers=headers, json=payload)
        if parse_resp.status_code == 200 and parse_resp.json().get('code') == 0:
            print("Parsing triggered successfully.")
        else:
            print(f"Failed to trigger parsing: {parse_resp.text}")

    except Exception as e:
        print(f"Error during parsing trigger: {e}")

if __name__ == "__main__":
    main()
