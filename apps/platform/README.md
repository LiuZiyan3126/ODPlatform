# 云平台
unzip ODPlatform.zip -d .
cd ODPlatform

pip install -e ./apps/platform/
odp-init
odp-transform --dataset fire --format pascal_voc --task detect --split-mode preserve --classes fire human-fire
odp-validate --dataset fire --task detect
odp-gen-config train
odp-train --epochs 300 --batch 16 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_v1_yolo11n


# 本地测试指令
pip install -e .\apps\platform\ --force-reinstall --no-deps

odp-init

odp-reset

odp-transform --dataset fire --format pascal_voc --task detect --split-mode preserve --classes fire human-fire

odp-validate --dataset fire --task detect

odp-gen-config train/val/infer

odp-train --epochs 1 --batch 16 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_smoke_test --author zpx

odp-train --epochs 300 --batch 16 --device 0 --model yolo11n.pt --data fire.yaml --yaml train.yaml --experiment-name fire_v1_yolo11n --author "你的名字"

## 推理加速后--model文件后缀改为.engine
odp-infer --source fire.mp4 --batch 1 --warmup 30 --show --model train-4-20260707-233005-yolo11n-best.pt --pipeline-yaml infer_pipeline.yaml --yaml infer.yaml --no-save 

yolo export model=models\trained\train-4-20260707-233005-yolo11n-best.pt format=engine half=True dynamic=True batch=1 workspace=2 device=0