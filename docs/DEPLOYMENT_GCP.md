# GCP Deployment with Workload Identity Federation

This guide explains how to deploy the FastAPI marketplace application to a GCP Compute Engine VM using Workload Identity Federation (WIF) for secure GitHub Actions authentication.

## Overview

**What is Workload Identity Federation?**
WIF allows GitHub Actions to authenticate to Google Cloud without storing long-lived service account keys. Instead, GitHub generates temporary OIDC tokens that are exchanged for GCP credentials.

**Architecture:**
```
GitHub Actions
    ↓ (uses OIDC token)
    ↓
Workload Identity Federation
    ↓ (exchanges token for credentials)
    ↓
GCP Service Account
    ↓ (pushes image)
    ↓
Artifact Registry → Compute Engine VM → Docker Container
```

---

## One-Time Setup (Manual)

### 1. Create GCP Project and Enable APIs

```bash
# Set your project ID
export PROJECT_ID="your-project-id"
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# Enable required APIs
gcloud services enable artifactregistry.googleapis.com \
  compute.googleapis.com \
  iam.googleapis.com \
  iap.googleapis.com \
  --project=$PROJECT_ID
```

### 2. Create Artifact Registry Repository

```bash
# Create Docker repository
gcloud artifacts repositories create marketplace \
  --repository-format=docker \
  --location=europe-west1 \
  --project=$PROJECT_ID

# Verify creation
gcloud artifacts repositories list --location=europe-west1 --project=$PROJECT_ID
```

### 3. Create Compute Engine VM

```bash
# Create the VM instance
gcloud compute instances create marketplace-vm \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --machine-type=e2-medium \
  --zone=europe-west1-a \
  --project=$PROJECT_ID \
  --scopes=https://www.googleapis.com/auth/cloud-platform \
  --metadata-from-file startup-script=infrastructure/deployment/cloud-init.yaml

# Get the external IP
gcloud compute instances describe marketplace-vm \
  --zone=europe-west1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)' \
  --project=$PROJECT_ID
```

### 4. Configure SSH Access

**Option A: OS Login (Recommended)**
```bash
# Enable OS Login for the project
gcloud compute project-info add-metadata \
  --metadata enable-oslogin=TRUE \
  --project=$PROJECT_ID

# SSH to VM (auto-manages credentials)
gcloud compute ssh marketplace-vm --zone=europe-west1-a
```

**Option B: SSH Key-based**
```bash
# Generate SSH key pair
ssh-keygen -t ed25519 -f ~/.ssh/gcp_vm_key -N ""

# Add public key to VM metadata
gcloud compute instances add-metadata marketplace-vm \
  --zone=europe-west1-a \
  --metadata-from-file ssh-keys=<(echo "user:$(cat ~/.ssh/gcp_vm_key.pub)") \
  --project=$PROJECT_ID
```

### 5. Setup Workload Identity Federation

#### 5.1 Create Workload Identity Pool and Provider

```bash
# Create the Workload Identity Pool
gcloud iam workload-identity-pools create github-actions \
  --project=$PROJECT_ID \
  --location=global \
  --display-name="GitHub Actions Pool"

# Get the pool resource name
POOL_ID="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions"

# Create OIDC provider for GitHub
gcloud iam workload-identity-pools providers create-oidc github \
  --project=$PROJECT_ID \
  --location=global \
  --workload-identity-pool=github-actions \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attr.aud=assertion.aud,attr.repository=assertion.repository" \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-condition="assertion.repository_owner == 'YOUR_GITHUB_ORG_OR_USERNAME'"

# Get the provider resource name
PROVIDER_ID="$POOL_ID/providers/github"
echo "WIF Provider: $PROVIDER_ID"
```

#### 5.2 Create Service Account

```bash
# Create service account for GitHub Actions
gcloud iam service-accounts create github-actions-deployer \
  --project=$PROJECT_ID \
  --display-name="GitHub Actions Deployer"

SA_EMAIL="github-actions-deployer@$PROJECT_ID.iam.gserviceaccount.com"
echo "Service Account: $SA_EMAIL"

# Grant Artifact Registry writer role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/artifactregistry.writer"

# Grant Compute Instance Admin role (for VM interaction)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/compute.instanceAdmin.v1"

# Grant service account user role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/iam.serviceAccountUser"
```

#### 5.3 Create Workload Identity Binding

```bash
# Allow GitHub to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --principal="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions/attribute.repository/YOUR_GITHUB_ORG_OR_USERNAME/YOUR_REPO_NAME"
```

### 6. Export Values for GitHub Secrets

```bash
# Export all values needed for GitHub
cat << EOF
GCP_PROJECT_ID=$PROJECT_ID
GCP_WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_ID
GCP_SERVICE_ACCOUNT_EMAIL=$SA_EMAIL
GCP_ARTIFACT_REGISTRY_LOCATION=europe-west1
GCP_ARTIFACT_REGISTRY_REPO=marketplace
VM_HOST=<EXTERNAL_IP_FROM_STEP_3>
VM_USERNAME=root
EOF
```

---

## GitHub Actions Setup

### 1. Add Repository Secrets

In your GitHub repository settings, add these secrets:

| Secret | Value | Notes |
|--------|-------|-------|
| `GCP_PROJECT_ID` | Your GCP project ID | From Step 1 |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource | From Step 5.1 |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Service account email | From Step 5.2 |
| `GCP_ARTIFACT_REGISTRY_LOCATION` | `europe-west1` | Must match Step 2 |
| `GCP_ARTIFACT_REGISTRY_REPO` | `marketplace` | Must match Step 2 |
| `VM_HOST` | Compute Engine external IP | From Step 3 |
| `VM_USERNAME` | `root` | Default for cloud-init |
| `VM_SSH_KEY_BASE64` | Base64-encoded SSH private key | See below |
| `APP_SECRET_KEY` | Your application secret key | Must be ≥32 chars |
| `DATABASE_URL` | PostgreSQL connection string | Set up on VM |

### 2. Generate SSH Key Secret

If using SSH key authentication (not OS Login):

```bash
# Generate SSH key
ssh-keygen -t ed25519 -f ~/.ssh/gcp_vm_key -N ""

# Encode as Base64 for GitHub Secret
cat ~/.ssh/gcp_vm_key | base64 -w0 > /tmp/ssh_key_b64.txt

# Copy to GitHub as VM_SSH_KEY_BASE64 secret
cat /tmp/ssh_key_b64.txt | pbcopy  # macOS
# or: cat /tmp/ssh_key_b64.txt | xclip -selection clipboard  # Linux
```

### 3. Verify Workflow

The workflow is automatically triggered on push to `main` branch:
1. Tests run
2. Docker image builds and pushes to Artifact Registry
3. SSH deploys image to Compute Engine VM

---

## Manual Deployment

To deploy manually without GitHub Actions:

```bash
# Set environment variables
export GCP_PROJECT_ID="your-project-id"
export GCP_ARTIFACT_REGISTRY_LOCATION="europe-west1"
export GCP_ARTIFACT_REGISTRY_REPO="marketplace"
export VM_HOST="<external-ip>"
export VM_USERNAME="root"
export VM_SSH_KEY="$HOME/.ssh/gcp_vm_key"
export SECRET_KEY="your-secret-key"
export DATABASE_URL="postgresql://user:password@localhost/marketplace"

# Run deployment script
chmod +x infrastructure/scripts/deploy-manual.sh
./infrastructure/scripts/deploy-manual.sh
```

---

## Monitoring & Debugging

### View Deployment Job Logs

```bash
# In GitHub Actions UI or via CLI:
gh run view <RUN_ID> --log
```

### SSH to VM and Check Container

```bash
# SSH to VM
gcloud compute ssh marketplace-vm --zone=europe-west1-a

# Check running containers
docker ps

# View application logs
docker logs -f marketplace

# Check image in local registry
docker images | grep marketplace
```

### Verify Artifact Registry Push

```bash
# List images in Artifact Registry
gcloud artifacts docker images list europe-west1-docker.pkg.dev/$PROJECT_ID/marketplace
```

### Test API Endpoint

```bash
# After deployment, test the app
curl http://<VM_EXTERNAL_IP>:8000/api/health

# Or open in browser
# http://<VM_EXTERNAL_IP>:8000/docs (Swagger UI)
```

---

## Troubleshooting

### WIF Authentication Fails

**Error:** `403: Unauthorized`

**Solution:**
- Verify WIF provider resource name matches exactly
- Check service account email is correct
- Ensure GitHub repository matches the attribute condition in Step 5.1
- Run: `gcloud iam workload-identity-pools describe github-actions --location=global`

### SSH Connection Fails

**Error:** `Permission denied (publickey)`

**Solution:**
- Verify VM_SSH_KEY_BASE64 is correct base64-encoded private key
- Check SSH key is added to VM metadata
- Verify firewall allows SSH (port 22)
- Try: `gcloud compute ssh marketplace-vm --zone=europe-west1-a`

### Container Fails to Start

**Error:** `docker: Error response from daemon`

**Solution:**
- SSH to VM and check: `docker logs marketplace`
- Verify environment variables are set (SECRET_KEY, DATABASE_URL)
- Check container image was pulled: `docker images`
- Ensure port 8000 is not in use: `netstat -tlnp | grep 8000`

### Image Push Fails

**Error:** `denied: Token exchange failed`

**Solution:**
- Verify service account has `artifactregistry.writer` role
- Check WIF binding is correct
- Re-run: `gcloud auth application-default login`

---

## Security Best Practices

1. **WIF over Keys:** ✅ Never store service account keys in GitHub
2. **SSH Keys:** Rotate SSH keys periodically
3. **Secrets:** Use GitHub's secret masking; never commit secrets
4. **VM Access:** Prefer OS Login over static SSH keys
5. **Firewall:** Restrict VM access to necessary ports only
6. **IAM:** Use principle of least privilege for service accounts

---

## Cleanup

To remove all resources:

```bash
# Delete Compute Engine VM
gcloud compute instances delete marketplace-vm --zone=europe-west1-a

# Delete Artifact Registry repository
gcloud artifacts repositories delete marketplace --location=europe-west1

# Delete service account
gcloud iam service-accounts delete github-actions-deployer@$PROJECT_ID.iam.gserviceaccount.com

# Delete Workload Identity Pool
gcloud iam workload-identity-pools delete github-actions --location=global
```

---

## References

- [Workload Identity Federation Documentation](https://cloud.google.com/iam/docs/workload-identity-federation)
- [GitHub Actions OpenID Connect Documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
- [Artifact Registry Docker Documentation](https://cloud.google.com/artifact-registry/docs/docker)
- [Compute Engine SSH Documentation](https://cloud.google.com/compute/docs/connect/standard-ssh)
