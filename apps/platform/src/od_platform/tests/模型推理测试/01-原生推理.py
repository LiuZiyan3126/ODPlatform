from ultralytics import YOLO

if __name__ == '__main__':
    model = YOLO('train3-20250704-165500-yolo11n-best.pt')
    model.predict(source=0, show=True)