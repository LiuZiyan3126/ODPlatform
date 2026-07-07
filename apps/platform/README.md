指令

pip install -e .\apps\platform\ --force-reinstall --no-deps

odp-init
odp-reset
odp-transform --dataset fire --format pascal_voc --task detect --split-mode preserve --classes fire human-fire
odp-validate --dataset fire --task detect
odp-gen-config train/val/infer
odp-train --epochs 3 --batch 2 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_smoke_test
odp-train --epochs 300 --batch 16 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_v1_yolo11n