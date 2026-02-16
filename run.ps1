# =============================================================================
# MRR Dashboard — Full Pipeline Runner
# =============================================================================
# Run from the project root: .\run.ps1
# =============================================================================

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MRR Dashboard — Full Pipeline" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check .env exists
if (-Not (Test-Path ".env")) {
    Write-Host "ERROR: .env file not found. Copy .env.example and fill in your credentials:" -ForegroundColor Red
    Write-Host "  cp .env.example .env" -ForegroundColor Yellow
    exit 1
}

# Step 1: Generate Stripe test data
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  STEP 1: Generating Stripe test data..." -ForegroundColor Green
Write-Host "  (This takes ~10-15 min due to test clock advancement)" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Green
python scripts/generate_data.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Step 1 failed. Check your STRIPE_SECRET_KEY in .env" -ForegroundColor Red
    exit 1
}

# Step 2: ETL — Stripe to BigQuery
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  STEP 2: Running ETL (Stripe -> BigQuery)..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
python scripts/etl_stripe_to_bq.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Step 2 failed. Check your GCP credentials in .env" -ForegroundColor Red
    exit 1
}

# Step 3: Start API server (background)
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  STEP 3: Starting Flask API server (port 5001)..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
$apiJob = Start-Process python -ArgumentList "scripts/api_server.py" -PassThru -NoNewWindow
Start-Sleep -Seconds 3

# Quick health check
try {
    $health = Invoke-RestMethod -Uri "http://localhost:5001/api/health" -TimeoutSec 5
    Write-Host "  API server is running: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "  WARNING: API server may not be ready yet" -ForegroundColor Yellow
}

# Step 4: Install frontend deps and start React
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  STEP 4: Starting React frontend..." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Push-Location frontend
if (-Not (Test-Path "node_modules")) {
    Write-Host "  Installing npm dependencies..." -ForegroundColor DarkGray
    npm install
}
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Dashboard launching at http://localhost:3000" -ForegroundColor Cyan
Write-Host "  API running at http://localhost:5001/api/mrr" -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan
npm start
Pop-Location

# Cleanup: stop API server when React exits
if ($apiJob -and -Not $apiJob.HasExited) {
    Stop-Process -Id $apiJob.Id -Force
    Write-Host "API server stopped." -ForegroundColor DarkGray
}
