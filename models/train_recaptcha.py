#!/usr/bin/env python3
"""
Train MobileNetV3-Small untuk reCAPTCHA v2 tile classifier.
Labels: [bicycle, bus, car, crosswalk, hydrant] — multi-label binary
Input: 100x100 tile images → 5-dim sigmoid output

Contabo: 4 core, 7.8GB RAM, no GPU → CPU training ~10-20 menit
"""
import os, time, json, io
import pyarrow.parquet as pq
import numpy as np
from PIL import Image

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from sklearn.metrics import f1_score, accuracy_score

LABELS = ["bicycle", "bus", "car", "crosswalk", "hydrant"]
PARQUET_TRAIN = "/tmp/rcv2_data/train.parquet"
PARQUET_VAL   = "/tmp/rcv2_data/val.parquet"
MODEL_OUT     = "/tmp/recaptcha_classifier.pt"
LOG_OUT       = "/tmp/train_log.json"

BATCH   = 64
EPOCHS  = 8
LR      = 1e-3
WORKERS = 0   # num_workers=0 untuk stabilitas (pyarrow fork-safe issue)


class ReCaptchaDataset(Dataset):
    def __init__(self, parquet_path, transform=None):
        self.tbl = pq.read_table(parquet_path)
        self.transform = transform

    def __len__(self):
        return self.tbl.num_rows

    def __getitem__(self, idx):
        img_data = self.tbl["image"][idx].as_py()
        labels   = self.tbl["labels"][idx].as_py()
        if isinstance(img_data, dict) and "bytes" in img_data:
            img = Image.open(io.BytesIO(img_data["bytes"])).convert("RGB")
        else:
            img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        if self.transform:
            img = self.transform(img)
        return img, torch.tensor(labels, dtype=torch.float32)


def build_model(num_classes=5):
    model = models.mobilenet_v3_small(weights=None)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, num_classes)
    return model


def train():
    print("=== reCAPTCHA v2 Tile Classifier Training ===")
    print(f"Labels: {LABELS}")
    print(f"Batch: {BATCH}, Epochs: {EPOCHS}, LR: {LR}")
    print()

    tf_train = transforms.Compose([
        transforms.Resize((112, 112)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    tf_val = transforms.Compose([
        transforms.Resize((112, 112)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    print("Loading datasets...")
    ds_train = ReCaptchaDataset(PARQUET_TRAIN, tf_train)
    ds_val   = ReCaptchaDataset(PARQUET_VAL,   tf_val)
    print(f"  train: {len(ds_train)}, val: {len(ds_val)}")

    dl_train = DataLoader(ds_train, batch_size=BATCH, shuffle=True,  num_workers=WORKERS, pin_memory=False)
    dl_val   = DataLoader(ds_val,   batch_size=BATCH, shuffle=False, num_workers=WORKERS, pin_memory=False)

    device = torch.device("cpu")
    model  = build_model(num_classes=5).to(device)
    param_count = sum(p.numel() for p in model.parameters())
    print(f"  model: MobileNetV3-Small ({param_count:,} params)")

    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

    log = {"epochs": [], "labels": LABELS, "model": "MobileNetV3-Small"}
    best_f1 = 0.0

    for epoch in range(1, EPOCHS + 1):
        t0 = time.time()
        # --- TRAIN ---
        model.train()
        train_loss = 0.0
        for batch_idx, (imgs, lbls) in enumerate(dl_train):
            imgs, lbls = imgs.to(device), lbls.to(device)
            optimizer.zero_grad()
            out  = model(imgs)
            loss = criterion(out, lbls)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * imgs.size(0)
            if batch_idx % 50 == 0:
                print(f"  epoch {epoch} batch {batch_idx}/{len(dl_train)} loss={loss.item():.4f}", flush=True)
        train_loss /= len(ds_train)

        # --- VAL ---
        model.eval()
        val_loss = 0.0
        all_pred, all_true = [], []
        with torch.no_grad():
            for imgs, lbls in dl_val:
                imgs, lbls = imgs.to(device), lbls.to(device)
                out  = model(imgs)
                loss = criterion(out, lbls)
                val_loss += loss.item() * imgs.size(0)
                probs = torch.sigmoid(out).cpu().numpy()
                preds = (probs > 0.5).astype(int)
                all_pred.append(preds)
                all_true.append(lbls.cpu().numpy())
        val_loss /= len(ds_val)

        all_pred = np.vstack(all_pred)
        all_true = np.vstack(all_true)
        f1   = f1_score(all_true, all_pred, average="macro", zero_division=0)
        f1pc = f1_score(all_true, all_pred, average=None, zero_division=0)

        scheduler.step()
        elapsed = time.time() - t0

        entry = {
            "epoch": epoch, "train_loss": round(train_loss, 4),
            "val_loss": round(val_loss, 4), "f1_macro": round(f1, 4),
            "f1_per_class": {LABELS[i]: round(float(f1pc[i]), 4) for i in range(5)},
            "elapsed_s": round(elapsed, 1)
        }
        log["epochs"].append(entry)

        print(f"Epoch {epoch}/{EPOCHS}  "
              f"train={train_loss:.4f}  val={val_loss:.4f}  "
              f"F1={f1:.4f}  [{elapsed:.0f}s]")
        for i, lbl in enumerate(LABELS):
            print(f"  {lbl:12s}: F1={f1pc[i]:.3f}")

        if f1 > best_f1:
            best_f1 = f1
            torch.save({
                "model_state": model.state_dict(),
                "labels": LABELS,
                "threshold": 0.5,
                "f1_macro": f1,
                "epoch": epoch,
            }, MODEL_OUT)
            print(f"  ✅ Saved best model (F1={f1:.4f})")
        print()

    json.dump(log, open(LOG_OUT, "w"), indent=2)
    print(f"=== DONE === Best F1: {best_f1:.4f}")
    print(f"Model: {MODEL_OUT}")
    print(f"Log:   {LOG_OUT}")


if __name__ == "__main__":
    train()
