指令
$env:PYTHONPATH = "apps/platform/src"
pip install -e .\apps\platform\ --force-reinstall --no-deps

odp-init
odp-reset
odp-transform --dataset rsod --format pascal_voc
odp-validate --dataset rsod --task detect
odp-gen-config train/val/infer
odp-train --epochs 3 --batch 8 --device 0 --model yolo11n.pt --data rsod.yaml --yaml train.yaml