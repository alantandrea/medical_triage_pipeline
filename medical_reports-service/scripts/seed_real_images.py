#!/usr/bin/env python3
"""
Seed Real Medical Images to S3 — All Modalities

Downloads real medical images from public datasets and uploads them
to the S3 medical-images bucket, replacing placeholder images.

Datasets:
  X-ray: BahaaEldin0/NIH-Chest-Xray-14 (NIH ChestX-ray14, CC0 Public Domain)
  CT:    MedMNIST v2 OrganAMNIST (CC BY 4.0) — real CT axial slices, 224x224
  MRI:   AIOmarRehan/Brain_Tumor_MRI_Dataset (CC0 Public Domain)

S3 modality mapping (matches getMedicalImage() in report generator):
  xray → xray/    ct → ct/    mri → mri/    mra → mri/    pet → ct/

Usage:
    pip install datasets boto3 Pillow medmnist
    python scripts/seed_real_images.py

Requires AWS credentials configured (aws configure).
"""

import io
import json
import sys
import time
from datetime import datetime, timezone

import boto3
import numpy as np
from datasets import load_dataset
from PIL import Image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BUCKET_PREFIX = "medgemma-challenge-medical-images"
IMAGES_PER_SEVERITY = 20

# ---------------------------------------------------------------------------
# X-ray: NIH ChestX-ray14 — severity mapping
# ---------------------------------------------------------------------------

XRAY_FINDING_TO_SEVERITY = {
    "No Finding":          "normal",
    "Atelectasis":         "minor",
    "Cardiomegaly":        "critical",
    "Effusion":            "minor",
    "Infiltration":        "minor",
    "Mass":                "major",
    "Nodule":              "major",
    "Pneumonia":           "major",
    "Pneumothorax":        "critical",
    "Consolidation":       "major",
    "Edema":               "critical",
    "Emphysema":           "minor",
    "Fibrosis":            "minor",
    "Pleural_Thickening":  "minor",
    "Hernia":              "minor",
}

# ---------------------------------------------------------------------------
# MRI: Brain Tumor — severity mapping
# ---------------------------------------------------------------------------

# Label indices from the HF dataset
MRI_LABEL_TO_INFO = {
    0: ("glioma", "critical"),        # Aggressive brain tumor
    1: ("meningioma", "major"),       # Usually benign but concerning
    2: ("no_tumor", "normal"),        # Normal brain MRI
    3: ("pituitary", "minor"),        # Usually benign pituitary adenoma
}

# ---------------------------------------------------------------------------
# CT: MedMNIST OrganAMNIST — organ classification
#
# These are REAL CT axial slices showing different organs. We map organs
# to severity levels for S3 folder structure. MedGemma 4B will analyze
# whatever it sees — the important thing is these are real CT images.
# ---------------------------------------------------------------------------

CT_LABEL_TO_INFO = {
    0:  ("bladder", "normal"),
    1:  ("femur_left", "normal"),
    2:  ("femur_right", "normal"),
    3:  ("heart", "minor"),
    4:  ("kidney_left", "minor"),
    5:  ("kidney_right", "minor"),
    6:  ("liver", "major"),
    7:  ("lung_left", "major"),
    8:  ("lung_right", "major"),
    9:  ("spleen", "critical"),
    10: ("stomach", "critical"),
}

SEVERITY_PRIORITY = {"normal": 0, "minor": 1, "major": 2, "critical": 3}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_bucket_name():
    """Discover the medical-images bucket name from AWS account."""
    sts = boto3.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    bucket_name = f"{BUCKET_PREFIX}-{account_id}"
    print(f"Target bucket: {bucket_name}")
    return bucket_name


def clear_existing_images(s3, bucket_name):
    """Delete all existing images from the bucket."""
    print("\nClearing existing images...")
    paginator = s3.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=bucket_name):
        contents = page.get("Contents", [])
        if not contents:
            continue
        objects = [{"Key": obj["Key"]} for obj in contents]
        s3.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})
        deleted += len(objects)
    print(f"  Deleted {deleted} existing objects")


def pil_to_png_bytes(pil_image):
    """Convert a PIL image to PNG bytes."""
    buf = io.BytesIO()
    if pil_image.mode not in ("RGB", "L"):
        pil_image = pil_image.convert("RGB")
    pil_image.save(buf, format="PNG")
    return buf.getvalue()


def upload_image(s3, bucket_name, key, png_bytes, finding_name, severity, modality, source):
    """Upload a single image to S3 with metadata."""
    s3.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=png_bytes,
        ContentType="image/png",
        Metadata={
            "description": f"{source} - {finding_name}",
            "finding": finding_name,
            "severity": severity,
            "modality": modality,
            "source": source,
            "license": "CC0 Public Domain" if modality != "ct" else "CC BY 4.0",
        }
    )


def resolve_xray_severity(labels):
    """Resolve multi-label X-ray findings to most severe."""
    if not labels:
        return None, None
    best_severity = "normal"
    best_finding = "No Finding"
    for label_name in labels:
        label_name = label_name.strip()
        severity = XRAY_FINDING_TO_SEVERITY.get(label_name, "normal")
        if SEVERITY_PRIORITY.get(severity, 0) > SEVERITY_PRIORITY.get(best_severity, 0):
            best_severity = severity
            best_finding = label_name
    return best_finding, best_severity


# ---------------------------------------------------------------------------
# Modality seeders
# ---------------------------------------------------------------------------

def seed_xray(s3, bucket_name, target):
    """Seed X-ray images from NIH ChestX-ray14."""
    print("\n" + "=" * 60)
    print("X-RAY: NIH ChestX-ray14 (BahaaEldin0/NIH-Chest-Xray-14)")
    print("=" * 60)

    collected = {s: [] for s in ["normal", "minor", "major", "critical"]}

    ds = load_dataset("BahaaEldin0/NIH-Chest-Xray-14", split="train", streaming=True)

    examined = 0
    for sample in ds:
        examined += 1
        if all(len(v) >= target for v in collected.values()):
            break

        labels = sample.get("label", [])
        if isinstance(labels, str):
            labels = [labels]

        finding_name, severity = resolve_xray_severity(labels)
        if severity is None or len(collected[severity]) >= target:
            continue

        pil_image = sample["image"]
        count = len(collected[severity]) + 1
        safe_finding = finding_name.lower().replace(" ", "_")
        s3_key = f"xray/{severity}/{safe_finding}_{count:03d}.png"

        png_bytes = pil_to_png_bytes(pil_image)
        upload_image(s3, bucket_name, s3_key, png_bytes, finding_name, severity,
                     "xray", "NIH ChestX-ray14 (Wang et al., CVPR 2017)")

        collected[severity].append({
            "key": s3_key, "finding": finding_name,
            "severity": severity, "size_kb": round(len(png_bytes) / 1024, 1),
        })
        print(f"  [xray/{severity:8s}] {count}/{target} -- {s3_key} ({len(png_bytes)/1024:.0f} KB)")

    total = sum(len(v) for v in collected.values())
    print(f"\n  X-ray: {total} images uploaded (examined {examined})")
    return collected


def seed_ct(s3, bucket_name, target):
    """Seed CT images from MedMNIST OrganAMNIST."""
    print("\n" + "=" * 60)
    print("CT: MedMNIST OrganAMNIST (224x224 axial CT slices)")
    print("=" * 60)

    # Import and load MedMNIST
    from medmnist import OrganAMNIST

    collected = {s: [] for s in ["normal", "minor", "major", "critical"]}

    # Download the 224x224 version
    ds = OrganAMNIST(split="train", download=True, size=224)

    examined = 0
    for i in range(len(ds)):
        if all(len(v) >= target for v in collected.values()):
            break

        examined += 1
        pil_image, label_array = ds[i]
        label_idx = int(label_array[0])

        info = CT_LABEL_TO_INFO.get(label_idx)
        if info is None:
            continue

        organ_name, severity = info
        if len(collected[severity]) >= target:
            continue

        count = len(collected[severity]) + 1
        s3_key = f"ct/{severity}/{organ_name}_{count:03d}.png"

        png_bytes = pil_to_png_bytes(pil_image)
        upload_image(s3, bucket_name, s3_key, png_bytes, organ_name, severity,
                     "ct", "MedMNIST v2 OrganAMNIST (Yang et al., 2023)")

        collected[severity].append({
            "key": s3_key, "finding": organ_name,
            "severity": severity, "size_kb": round(len(png_bytes) / 1024, 1),
        })
        print(f"  [ct/{severity:8s}] {count}/{target} -- {s3_key} ({len(png_bytes)/1024:.0f} KB)")

    total = sum(len(v) for v in collected.values())
    print(f"\n  CT: {total} images uploaded (examined {examined})")
    return collected


def seed_mri(s3, bucket_name, target):
    """Seed MRI images from Brain Tumor MRI Dataset."""
    print("\n" + "=" * 60)
    print("MRI: Brain Tumor MRI Dataset (AIOmarRehan, CC0)")
    print("=" * 60)

    collected = {s: [] for s in ["normal", "minor", "major", "critical"]}

    # This dataset has a 'test' split with all images
    ds = load_dataset("AIOmarRehan/Brain_Tumor_MRI_Dataset", split="test", streaming=True)

    examined = 0
    for sample in ds:
        examined += 1
        if all(len(v) >= target for v in collected.values()):
            break

        label_idx = sample.get("label")
        if label_idx is None:
            continue

        info = MRI_LABEL_TO_INFO.get(label_idx)
        if info is None:
            continue

        finding_name, severity = info
        if len(collected[severity]) >= target:
            continue

        pil_image = sample["image"]
        count = len(collected[severity]) + 1
        s3_key = f"mri/{severity}/{finding_name}_{count:03d}.png"

        png_bytes = pil_to_png_bytes(pil_image)
        upload_image(s3, bucket_name, s3_key, png_bytes, finding_name, severity,
                     "mri", "Brain Tumor MRI Dataset (CC0 Public Domain)")

        collected[severity].append({
            "key": s3_key, "finding": finding_name,
            "severity": severity, "size_kb": round(len(png_bytes) / 1024, 1),
        })
        print(f"  [mri/{severity:8s}] {count}/{target} -- {s3_key} ({len(png_bytes)/1024:.0f} KB)")

    total = sum(len(v) for v in collected.values())
    print(f"\n  MRI: {total} images uploaded (examined {examined})")
    return collected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Multi-Modality Real Medical Image Seeder")
    print("=" * 60)
    print()
    print("Modalities: X-ray (NIH ChestX-ray14), CT (MedMNIST), MRI (Brain Tumor)")
    print(f"Target: {IMAGES_PER_SEVERITY} images per severity x 4 severities x 3 modalities = {IMAGES_PER_SEVERITY * 4 * 3} total")
    print()
    print("S3 modality mapping in report generator:")
    print("  xray reports -> xray/     ct reports -> ct/")
    print("  mri reports  -> mri/      mra reports -> mri/  (reuses MRI)")
    print("  pet reports  -> ct/  (reuses CT)")

    bucket_name = get_bucket_name()
    s3 = boto3.client("s3")

    try:
        s3.head_bucket(Bucket=bucket_name)
    except Exception as e:
        print(f"\nERROR: Bucket '{bucket_name}' not found or not accessible.")
        print(f"  {e}")
        sys.exit(1)

    clear_existing_images(s3, bucket_name)

    start_time = time.time()
    target = IMAGES_PER_SEVERITY

    # Seed all three modalities
    xray_collected = seed_xray(s3, bucket_name, target)
    ct_collected = seed_ct(s3, bucket_name, target)
    mri_collected = seed_mri(s3, bucket_name, target)

    elapsed = time.time() - start_time

    # Build manifest
    all_images = []
    for modality_name, collected in [("xray", xray_collected), ("ct", ct_collected), ("mri", mri_collected)]:
        for severity in ["normal", "minor", "major", "critical"]:
            for item in collected[severity]:
                all_images.append(item)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_images": len(all_images),
        "modalities": ["xray", "ct", "mri"],
        "severities": ["normal", "minor", "major", "critical"],
        "sources": {
            "xray": {
                "dataset": "NIH ChestX-ray14",
                "citation": "Wang et al., ChestX-ray8, CVPR 2017",
                "license": "CC0 Public Domain",
                "hf_repo": "BahaaEldin0/NIH-Chest-Xray-14",
            },
            "ct": {
                "dataset": "MedMNIST v2 OrganAMNIST",
                "citation": "Yang et al., MedMNIST v2, Scientific Data 2023",
                "license": "CC BY 4.0",
                "hf_repo": "medmnist (pip package)",
            },
            "mri": {
                "dataset": "Brain Tumor MRI Dataset",
                "citation": "AIOmarRehan/Brain_Tumor_MRI_Dataset",
                "license": "CC0 Public Domain",
                "hf_repo": "AIOmarRehan/Brain_Tumor_MRI_Dataset",
            },
        },
        "images": all_images,
    }

    s3.put_object(
        Bucket=bucket_name,
        Key="index.json",
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )

    # Summary
    print("\n" + "=" * 60)
    print(f"COMPLETE! {len(all_images)} real medical images uploaded in {elapsed:.1f}s")
    print("=" * 60)
    print()

    for modality_name, collected in [("xray", xray_collected), ("ct", ct_collected), ("mri", mri_collected)]:
        mod_total = sum(len(v) for v in collected.values())
        print(f"  {modality_name:5s}: {mod_total} images")
        for severity in ["normal", "minor", "major", "critical"]:
            items = collected[severity]
            if items:
                findings = set(item["finding"] for item in items)
                print(f"    {severity:8s}: {len(items)}/{target} -- {', '.join(sorted(findings))}")

    print(f"\n  index.json manifest uploaded ({len(all_images)} entries)")
    print()
    print("Report type -> S3 modality mapping:")
    print("  xray -> xray/  |  ct -> ct/  |  mri -> mri/")
    print("  mra  -> mri/   |  pet -> ct/ |  lab/path -> no image")
    print()
    print("All modalities now have REAL medical images!")


if __name__ == "__main__":
    main()
