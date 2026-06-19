import platform
import subprocess
from typing import Dict


def safe_import_torch():
    try:
        import torch

        return torch
    except Exception:
        return None


def has_nvidia_smi() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=5,
        )

        return result.returncode == 0

    except Exception:
        return False


def get_torch_cuda_info() -> Dict:
    torch = safe_import_torch()

    if torch is None:
        return {
            "torch_installed": False,
            "cuda_available": False,
            "device_count": 0,
            "device_name": None,
            "torch_version": None,
        }

    cuda_available = False
    device_count = 0
    device_name = None

    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False

    if cuda_available:
        try:
            device_count = int(torch.cuda.device_count())
        except Exception:
            device_count = 0

        try:
            device_name = torch.cuda.get_device_name(0)
        except Exception:
            device_name = None

    return {
        "torch_installed": True,
        "cuda_available": cuda_available,
        "device_count": device_count,
        "device_name": device_name,
        "torch_version": getattr(torch, "__version__", None),
    }


def get_hardware_status() -> Dict:
    torch_info = get_torch_cuda_info()
    nvidia_driver_detected = has_nvidia_smi()

    can_use_gpu_ocr = (
        torch_info["torch_installed"]
        and torch_info["cuda_available"]
        and torch_info["device_count"] > 0
    )

    if can_use_gpu_ocr:
        reason = "CUDA GPU is available for OCR."
    elif not torch_info["torch_installed"]:
        reason = "Torch is not installed. OCR must use CPU."
    elif nvidia_driver_detected and not torch_info["cuda_available"]:
        reason = "NVIDIA driver exists, but current Torch build cannot use CUDA."
    elif not nvidia_driver_detected:
        reason = "No NVIDIA CUDA driver detected. OCR must use CPU."
    else:
        reason = "CUDA is not available. OCR must use CPU."

    return {
        "platform": platform.platform(),
        "nvidia_driver_detected": nvidia_driver_detected,
        "torch": torch_info,
        "can_use_gpu_ocr": can_use_gpu_ocr,
        "recommended_ocr_gpu": can_use_gpu_ocr,
        "reason": reason,
    }


def should_use_gpu_ocr(user_requested_gpu=None) -> bool:
    """
    Auto-safe GPU decision.

    user_requested_gpu:
    - None: auto detect
    - True: use GPU only if machine really supports it
    - False: force CPU

    This prevents crashes on machines without CUDA.
    """

    status = get_hardware_status()

    if user_requested_gpu is False:
        return False

    if user_requested_gpu is True:
        return bool(status["can_use_gpu_ocr"])

    return bool(status["recommended_ocr_gpu"])


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            get_hardware_status(),
            ensure_ascii=False,
            indent=2,
        )
    )