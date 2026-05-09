import argparse
import csv
import json
import traceback
from pathlib import Path


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except Exception:
        return False


def _parse_metrics(save_dir: Path) -> dict:
    """Return the final-epoch validation metrics from results.csv, if present."""
    csv_path = save_dir / "results.csv"
    if not csv_path.exists():
        return {}
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return {}
        last = rows[-1]
        out = {}
        for k, v in last.items():
            key = k.strip()
            try:
                out[key] = float(v.strip())
            except Exception:
                out[key] = v.strip()
        return out
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-yaml', required=True)
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--model-source', required=True)
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--epochs', type=int, required=True)
    parser.add_argument('--imgsz', type=int, required=True)
    parser.add_argument('--batch', type=int, required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--patience', type=int, required=True)
    parser.add_argument('--aug-json', required=True)
    parser.add_argument('--result-json', required=True)
    # Optional export format after training (onnx, engine, coreml)
    parser.add_argument('--export-format', default='', required=False)
    args = parser.parse_args()

    try:
        from ultralytics import YOLO

        # Enable AMP only when a real CUDA device is available; CPU/MPS training
        # can silently produce NaN losses with amp=True on some Ultralytics builds.
        use_amp = _cuda_available() and args.device not in ("cpu", "mps")

        aug = json.loads(args.aug_json)
        model = YOLO(args.model_source)
        model.train(
            data=args.data_yaml,
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            device=args.device,
            project=args.run_root,
            name=args.run_name,
            exist_ok=True,
            verbose=False,
            patience=args.patience,
            amp=use_amp,
            hsv_h=aug['hsv_h'],
            hsv_s=aug['hsv_s'],
            hsv_v=aug['hsv_v'],
            degrees=aug['degrees'],
            translate=aug['translate'],
            scale=aug['scale'],
            shear=aug['shear'],
            perspective=aug['perspective'],
            fliplr=aug['fliplr'],
            mosaic=aug['mosaic'],
            mixup=aug['mixup'],
        )

        save_dir = None
        if hasattr(model, 'trainer') and getattr(model.trainer, 'save_dir', None):
            save_dir = Path(model.trainer.save_dir)
        if not save_dir:
            run_root = Path(args.run_root)
            run_dirs = sorted(run_root.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
            save_dir = run_dirs[0] if run_dirs else None
        if not save_dir:
            raise RuntimeError('Could not locate training run directory.')

        best = save_dir / 'weights' / 'best.pt'
        if not best.exists():
            raise RuntimeError('Training completed but best.pt not found.')

        metrics = _parse_metrics(save_dir)

        # Optional post-training export
        exported_path = None
        export_fmt = (args.export_format or "").strip().lower()
        if export_fmt and export_fmt not in ("pt", "pytorch"):
            try:
                exported = model.export(format=export_fmt)
                if exported:
                    exported_path = str(exported)
            except Exception as exp_err:
                # Export failure is non-fatal — training succeeded
                metrics["export_error"] = str(exp_err)

        payload = {
            'save_dir': str(save_dir),
            'best': str(best),
            'metrics': metrics,
            'amp_used': use_amp,
        }
        if exported_path:
            payload['exported'] = exported_path
            payload['export_format'] = export_fmt

        Path(args.result_json).write_text(json.dumps(payload), encoding='utf-8')

    except Exception as exc:
        payload = {
            'error': str(exc),
            'traceback': traceback.format_exc(limit=20),
        }
        try:
            Path(args.result_json).write_text(json.dumps(payload), encoding='utf-8')
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
