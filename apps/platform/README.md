指令
pip install -e .\apps\platform\ --force-reinstall --no-deps

odp-init
odp-reset
odp-transform --dataset rsod --format pascal_voc
odp-validate --dataset rsod --task detect
odp-gen-config train/val/infer

python .\apps\platform\tests\train.py --data rsod.yaml --model .\tests\yolo11n.pt --epochs 1 --batch 2 --imgsz 640 --device cpu --workers 0 --project ..\..\runs\detect --name smoke --exist-ok