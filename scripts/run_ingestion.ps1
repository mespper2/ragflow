$ErrorActionPreference = "Stop"
$CONTAINER = "docker-ragflow-cpu-1"
$SCRIPT_HOST_PATH = "scripts/ingest_from_dataserver.py"
$SCRIPT_CONT_PATH = "/tmp/ingest_from_dataserver.py"
$API_KEY = "ragflow-8q5k58fMSHcP3xiBzb9G6Qi3AAylPWKILNx45B3dQ2Y"

Write-Output "Copying ingestion script to container $CONTAINER..."
docker cp $SCRIPT_HOST_PATH "${CONTAINER}:${SCRIPT_CONT_PATH}"

Write-Output "Ensuring dependencies inside container..."
docker exec $CONTAINER pip install requests --quiet

Write-Output "Running ingestion script inside container..."
# Note: Using 'data-server' as hostname because they share the scrapy_mundo_geral_net network
docker exec $CONTAINER python3 $SCRIPT_CONT_PATH --api-key $API_KEY --ragflow-url "http://localhost:9380" --data-url "http://data-server:80"

Write-Output "Ingestion Completed."
