指令
pip install -e .\apps\platform\ --force-reinstall --no-deps

odp-init
odp-reset
odp-transform --dataset rsod --format pascal_voc
odp-validate --dataset rsod --task detect
odp-gen-config train/val/infer

python -m apps.platform.tests.train --data rsod.yaml --model yolo11n.pt --epochs 1 --batch 2