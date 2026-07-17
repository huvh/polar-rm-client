from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any


ARMOR_THICKNESS_M = 0.035
SMALL_ARMOR_WIDTH_M = 0.135
BIG_ARMOR_WIDTH_M = 0.230
ARMOR_HEIGHT_M = 0.056


@dataclass(frozen=True)
class ArmorPlate3D:
    points: tuple[tuple[float, float], ...]
    back_points: tuple[tuple[float, float], ...]
    predicted: bool
    plate_id: int
    distance_m: float
    depth_m: float
    yaw_rad: float


class MultiArmorPrediction:
    """桌面相机坐标系下的 PnP 装甲厚度与整车多板预测。"""

    def __init__(self) -> None:
        self._last_yaw = 0.0
        self._last_time = 0.0
        self._yaw_rate = 0.0
        self._stable_frames = 0
        self._filtered_rvec: Any | None = None
        self._filtered_tvec: Any | None = None
        self._velocity: Any | None = None
        self._pose_time = 0.0
        self._target_key: Any | None = None

    def reset(self) -> None:
        """在目标切换或检测中断时清空姿态历史，避免旧目标拖入新目标。"""
        self._last_yaw = 0.0
        self._last_time = 0.0
        self._yaw_rate = 0.0
        self._stable_frames = 0
        self._filtered_rvec = None
        self._filtered_tvec = None
        self._velocity = None
        self._pose_time = 0.0
        self._target_key = None

    @staticmethod
    def _camera_matrix(width: int, height: int) -> Any:
        import numpy as np  # type: ignore

        focal = width / (2.0 * math.tan(math.radians(70.0) / 2.0))
        return np.array([[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]], dtype=np.float64)

    @staticmethod
    def _object_points(width_m: float, thickness_m: float = 0.0) -> Any:
        import numpy as np  # type: ignore

        return np.array(
            [
                [-width_m / 2.0, -ARMOR_HEIGHT_M / 2.0, thickness_m],
                [width_m / 2.0, -ARMOR_HEIGHT_M / 2.0, thickness_m],
                [width_m / 2.0, ARMOR_HEIGHT_M / 2.0, thickness_m],
                [-width_m / 2.0, ARMOR_HEIGHT_M / 2.0, thickness_m],
            ],
            dtype=np.float64,
        )

    @staticmethod
    def _project(points: Any, rvec: Any, tvec: Any, matrix: Any) -> tuple[tuple[float, float], ...]:
        import cv2  # type: ignore

        projected, _ = cv2.projectPoints(points, rvec, tvec, matrix, None)
        return tuple((float(point[0][0]), float(point[0][1])) for point in projected)

    def _solve(
        self,
        points: tuple[tuple[float, float], ...],
        width_m: float,
        matrix: Any,
        previous_rvec: Any | None = None,
        previous_tvec: Any | None = None,
    ) -> tuple[Any, Any, float] | None:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        image = np.asarray(points, dtype=np.float64)
        obj = self._object_points(width_m)
        candidates: list[tuple[Any, Any, float]] = []
        for order in ((0, 1, 2, 3), (1, 2, 3, 0), (3, 0, 1, 2), (0, 3, 2, 1)):
            image_ordered = image[list(order)]
            for flag in (cv2.SOLVEPNP_IPPE, cv2.SOLVEPNP_ITERATIVE):
                try:
                    ok, rvec, tvec = cv2.solvePnP(obj, image_ordered, matrix, None, flags=flag)
                except cv2.error:
                    continue
                depth = float(tvec.reshape(3)[2])
                if not ok or depth < 0.2 or depth > 15.0:
                    continue
                projected = self._project(obj, rvec, tvec, matrix)
                error = sum(math.dist(projected[index], tuple(image_ordered[index])) for index in range(4)) / 4.0
                candidates.append((rvec, tvec, error))
        if not candidates:
            return None
        if previous_rvec is None or previous_tvec is None:
            return min(candidates, key=lambda item: item[2])

        # 重投影误差相近时优先沿用上一帧的姿态，避免 PnP 在两个合法解之间翻转。
        def pose_score(item: tuple[Any, Any, float]) -> float:
            rvec, tvec, reprojection_error = item
            translation_delta = float(np.linalg.norm(tvec.reshape(3) - previous_tvec.reshape(3)))
            rotation_delta = float(np.linalg.norm(rvec.reshape(3) - previous_rvec.reshape(3)))
            return reprojection_error + min(7.0, translation_delta * 16.0) + min(6.0, rotation_delta * 1.8)

        return min(candidates, key=pose_score)

    def build(
        self,
        points: tuple[tuple[float, float], ...],
        frame_width: int,
        frame_height: int,
        *,
        is_big: bool = False,
        armor_count: int = 4,
        radius_m: float = 0.23,
        horizon_s: float = 0.06,
        target_key: Any | None = None,
    ) -> list[ArmorPlate3D]:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        if target_key != self._target_key:
            self.reset()
            self._target_key = target_key

        width_m = BIG_ARMOR_WIDTH_M if is_big else SMALL_ARMOR_WIDTH_M
        matrix = self._camera_matrix(frame_width, frame_height)
        solved = self._solve(points, width_m, matrix, self._filtered_rvec, self._filtered_tvec)
        if solved is None:
            self.reset()
            self._target_key = target_key
            return []
        rvec, tvec, error = solved
        if error > 8.0:
            self.reset()
            self._target_key = target_key
            return []

        raw_rvec = np.asarray(rvec, dtype=np.float64).reshape(3, 1)
        raw_tvec = np.asarray(tvec, dtype=np.float64).reshape(3, 1)
        now = time.perf_counter()
        if self._filtered_rvec is None or self._filtered_tvec is None or self._pose_time <= 0.0:
            filtered_rvec = raw_rvec.copy()
            filtered_tvec = raw_tvec.copy()
            velocity = np.zeros((3, 1), dtype=np.float64)
        else:
            delta_time = max(0.001, min(0.12, now - self._pose_time))
            # 80ms 低通：保留跟手感，同时过滤角点抖动放大的深度与姿态变化。
            alpha = 1.0 - math.exp(-delta_time / 0.080)
            filtered_rvec = self._filtered_rvec + (raw_rvec - self._filtered_rvec) * alpha
            filtered_tvec = self._filtered_tvec + (raw_tvec - self._filtered_tvec) * alpha
            measured_velocity = (filtered_tvec - self._filtered_tvec) / delta_time
            previous_velocity = self._velocity if self._velocity is not None else np.zeros((3, 1), dtype=np.float64)
            velocity = previous_velocity * 0.78 + measured_velocity * 0.22

        self._filtered_rvec = filtered_rvec
        self._filtered_tvec = filtered_tvec
        self._velocity = velocity
        self._pose_time = now

        rotation, _ = cv2.Rodrigues(filtered_rvec)
        normal = rotation[:, 2]
        if normal[2] > 0:
            normal = -normal
        yaw = math.atan2(float(normal[0]), float(-normal[2]))
        if self._last_time:
            delta = (yaw - self._last_yaw + math.pi) % (2.0 * math.pi) - math.pi
            instant_rate = delta / max(0.001, now - self._last_time)
            self._yaw_rate = self._yaw_rate * 0.72 + instant_rate * 0.28
        self._last_yaw, self._last_time = yaw, now
        self._stable_frames = min(12, self._stable_frames + 1)

        filtered_tvec = filtered_tvec.reshape(3, 1)
        predicted_tvec = filtered_tvec + velocity * min(0.12, max(0.0, horizon_s)) * 0.65
        front_projected = self._project(self._object_points(width_m), filtered_rvec, filtered_tvec, matrix)
        back_projected = self._project(self._object_points(width_m, -ARMOR_THICKNESS_M), filtered_rvec, filtered_tvec, matrix)
        # 检测前脸比 PnP 回投影稳定，将后脸做同中心平移与它对齐。
        detected_center = np.mean(np.asarray(points), axis=0)
        projected_center = np.mean(np.asarray(front_projected), axis=0)
        shift = detected_center - projected_center
        # 保留检测中心的跟手性，但限制角点噪声直接传入 3D 姿态框。
        shift *= 0.35
        back_visible = tuple((point[0] + float(shift[0]), point[1] + float(shift[1])) for point in back_projected)
        distance = float(np.linalg.norm(filtered_tvec))
        front_visible = tuple((point[0] + float(shift[0]), point[1] + float(shift[1])) for point in front_projected)
        plates = [ArmorPlate3D(front_visible, back_visible, False, 0, distance, float(filtered_tvec.reshape(3)[2]), yaw)]
        if self._stable_frames < 3 or armor_count < 2:
            return plates

        center = predicted_tvec.reshape(3) - radius_m * normal.reshape(3)
        for index in range(1, armor_count):
            angle = index * 2.0 * math.pi / armor_count + self._yaw_rate * horizon_s
            rotate_y, _ = cv2.Rodrigues(np.array([0.0, angle, 0.0], dtype=np.float64))
            plate_rotation = rotate_y @ rotation
            plate_position = center + rotate_y @ (predicted_tvec.reshape(3) - center)
            plate_rvec, _ = cv2.Rodrigues(plate_rotation)
            plate_tvec = plate_position.reshape(3, 1)
            front = self._project(self._object_points(width_m), plate_rvec, plate_tvec, matrix)
            back = self._project(self._object_points(width_m, -ARMOR_THICKNESS_M), plate_rvec, plate_tvec, matrix)
            if not all(-frame_width * 0.35 < point[0] < frame_width * 1.35 and -frame_height * 0.35 < point[1] < frame_height * 1.35 for point in front):
                continue
            plate_normal = plate_rotation[:, 2]
            plate_yaw = math.atan2(float(plate_normal[0]), float(-plate_normal[2]))
            plates.append(ArmorPlate3D(front, back, True, index, float(np.linalg.norm(plate_tvec)), float(plate_tvec.reshape(3)[2]), plate_yaw))
        return plates
