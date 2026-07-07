from od_platform.frame_source import create_frame_source
from od_platform.frame_source import CameraConfig
base = CameraConfig(width=1280, height=720, fps=90,)
import cv2

if __name__ == '__main__':
    with create_frame_source(source = "0") as src:
        for frame in src:
            img = frame.image
            cv2.putText(
                img,
                f"FPS: {frame.info.fps:.2f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            cv2.imshow("Frame", img)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
    cv2.destroyAllWindows()