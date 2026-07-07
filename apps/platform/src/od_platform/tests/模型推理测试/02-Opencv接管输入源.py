import cv2
from ultralytics import YOLO

if __name__ == '__main__':
    model = YOLO('train3-20250704-165500-yolo11n-best.pt')

    cap = cv2.VideoCapture(0) # 自己打开摄像头

    while True:
        ret, frame = cap.read() # 读取摄像头的帧画面
        if not ret:
            break

        results = model.predict(frame, verbose=False, show=False) # 控制点，只让模型进行推理，不显示结果

        annotated_frame = results[0].plot() # 获取推理结果

        cv2.imshow('YOLO Inference', annotated_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            break

        cap.release()
        cv2.destroyAllWindows()