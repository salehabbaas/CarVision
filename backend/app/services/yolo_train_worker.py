import argparse
import json
import traceback
from pathlib import Path


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
    args = parser.parse_args()

    try:
        from ultralytics import YOLO

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
            amp=False,
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
        Path(args.result_json).write_text(json.dumps({'save_dir': str(save_dir), 'best': str(best)}), encoding='utf-8')
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
