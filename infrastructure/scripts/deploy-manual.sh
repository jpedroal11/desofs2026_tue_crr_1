#!/bin/bash
set -e

# Manual deployment script for GCP Compute Engine
# Usage: ./deploy-manual.sh

GCP_PROJECT_ID="${GCP_PROJECT_ID:?Error: GCP_PROJECT_ID not set}"
GCP_ARTIFACT_REGISTRY_LOCATION="${GCP_ARTIFACT_REGISTRY_LOCATION:?Error: GCP_ARTIFACT_REGISTRY_LOCATION not set}"
GCP_ARTIFACT_REGISTRY_REPO="${GCP_ARTIFACT_REGISTRY_REPO:?Error: GCP_ARTIFACT_REGISTRY_REPO not set}"
VM_HOST="${VM_HOST:?Error: VM_HOST not set}"
VM_USERNAME="${VM_USERNAME:?Error: VM_USERNAME not set}"
VM_SSH_KEY="${VM_SSH_KEY:?Error: VM_SSH_KEY not set}"

# Optional: Set environment variables for the application
SECRET_KEY="${SECRET_KEY:?Error: SECRET_KEY not set}"
DATABASE_URL="${DATABASE_URL:?Error: DATABASE_URL not set}"

IMAGE_URL="$GCP_ARTIFACT_REGISTRY_LOCATION-docker.pkg.dev/$GCP_PROJECT_ID/$GCP_ARTIFACT_REGISTRY_REPO/marketplace:latest"

echo "🔨 Building Docker image: $IMAGE_URL"
docker build -t "$IMAGE_URL" Deliverables/Phase_2/Project/marketplace

echo "📤 Pushing image to Artifact Registry..."
docker push "$IMAGE_URL"

echo "🚀 Deploying to VM at $VM_HOST..."
mkdir -p ~/.ssh

# Add VM to known_hosts
ssh-keyscan -H "$VM_HOST" >> ~/.ssh/known_hosts 2>/dev/null || true

# Deploy via SSH
ssh -i "$VM_SSH_KEY" "$VM_USERNAME@$VM_HOST" << DEPLOY_EOF
  set -e
  echo "🔑 Authenticating to Artifact Registry..."
  gcloud auth configure-docker "$GCP_ARTIFACT_REGISTRY_LOCATION-docker.pkg.dev"

  echo "📥 Pulling latest image..."
  docker pull "$IMAGE_URL"

  echo "🛑 Stopping old container..."
  docker stop marketplace || true
  docker rm marketplace || true

  echo "▶️  Starting new container..."
  docker run -d \
    --name marketplace \
    --restart always \
    -p 8000:8000 \
    -e SECRET_KEY="$SECRET_KEY" \
    -e DATABASE_URL="$DATABASE_URL" \
    -e APP_ENV="production" \
    "$IMAGE_URL"

  echo "✅ Deployment complete!"
  echo "📋 Container logs:"
  docker logs marketplace | tail -20
DEPLOY_EOF

echo ""
echo "✅ Deployment successful!"
echo "🌐 Access your app at: http://$VM_HOST:8000"
echo "📊 Check logs with: ssh -i $VM_SSH_KEY $VM_USERNAME@$VM_HOST docker logs -f marketplace"
