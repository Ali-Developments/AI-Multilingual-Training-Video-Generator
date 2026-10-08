# ==============================================================================
# SadTalker Local Avatar Provider Bootstrap Script (Windows PowerShell)
# ==============================================================================
# This script sets up an isolated virtual environment (.sadtalker-venv) and clones
# the official OpenTalker/SadTalker repository into tools/sadtalker with CUDA PyTorch.
#
# Requirements:
# - Python 3.10 installed on system (or via Conda / pyenv)
# - NVIDIA GPU with CUDA drivers
# - FFmpeg installed and available on PATH
# ==============================================================================

param(
    [string]$Python310Path = "python",
    [string]$TargetDir = "tools/sadtalker",
    [string]$VenvDir = ".sadtalker-venv"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " SadTalker Local Environment Setup " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify Target Directory
if (-not (Test-Path -Path $TargetDir)) {
    Write-Host "[1/5] Cloning OpenTalker/SadTalker into '$TargetDir'..." -ForegroundColor Yellow
    git clone https://github.com/OpenTalker/SadTalker.git $TargetDir
} else {
    Write-Host "[1/5] Upstream SadTalker repository already present at '$TargetDir'." -ForegroundColor Green
}

# 2. Setup Dedicated Virtual Environment
if (-not (Test-Path -Path $VenvDir)) {
    Write-Host "[2/5] Creating isolated virtual environment in '$VenvDir'..." -ForegroundColor Yellow
    & $Python310Path -m venv $VenvDir
} else {
    Write-Host "[2/5] Isolated virtual environment already present at '$VenvDir'." -ForegroundColor Green
}

$VenvPython = Join-Path $VenvDir "Scripts/python.exe"
$VenvPip = Join-Path $VenvDir "Scripts/pip.exe"

# 3. Install PyTorch with CUDA support
Write-Host "[3/5] Installing PyTorch (CUDA 11.8 / 12.1 compatible)..." -ForegroundColor Yellow
& $VenvPip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 4. Install SadTalker requirements
Write-Host "[4/5] Installing SadTalker dependencies..." -ForegroundColor Yellow
& $VenvPip install -r (Join-Path $TargetDir "requirements.txt")
& $VenvPip install imageio-ffmpeg facexlib librosa yacs pydantic

# 5. Checkpoints guidance
$CheckpointDir = Join-Path $TargetDir "checkpoints"
if (-not (Test-Path -Path $CheckpointDir)) {
    New-Item -ItemType Directory -Path $CheckpointDir -Force | Out-Null
}

Write-Host "[5/5] Checking model checkpoints..." -ForegroundColor Yellow
Write-Host @"
Expected Checkpoint Files in '$CheckpointDir':
  - SadTalker_V0.0.2_256.safetensors
  - mapping_00109-model.pth.tar
  - mapping_00229-model.pth.tar
  - BFM_Fitting_Fitting_Fitting (BFM directory structure)
  - hub/checkpoints/s3fd-619a31684a.pth
  - hub/checkpoints/2DFAN4-cd93763095.pth

Download official weights via:
  powershell -Command "Invoke-WebRequest -Uri 'https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2/SadTalker_V0.0.2_256.safetensors' -OutFile '$CheckpointDir/SadTalker_V0.0.2_256.safetensors'"

Default source presenter portrait:
  assets/avatars/local_presenter.png

Environment configuration (.env):
  DEFAULT_AVATAR_PROVIDER=sadtalker
  SADTALKER_PYTHON_PATH=$VenvPython
  SADTALKER_ROOT=$TargetDir
  SADTALKER_CHECKPOINT_PATH=$CheckpointDir
  SADTALKER_DEFAULT_SOURCE_IMAGE=assets/avatars/local_presenter.png
"@ -ForegroundColor Cyan

Write-Host "==========================================================" -ForegroundColor Green
Write-Host " SadTalker Setup Completed Successfully! " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
