import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


CANVAS_SIZE = 800
PLOT_MARGIN = 80


def load_measurements(path: Path) -> list[dict]:
    """Load Lab measurements produced by the color estimator."""
    if not path.exists():
        raise FileNotFoundError(
            f"Measurements not found: {path}. Run measure_lab.py first."
        )

    measurements = json.loads(path.read_text(encoding="utf-8"))
    if not measurements:
        raise ValueError("The measurements file is empty")
    return measurements


def scale_value(
    value: float,
    source_min: float,
    source_max: float,
    target_min: int,
    target_max: int,
) -> int:
    """Map one value from a data range to a pixel range."""
    if source_min == source_max:
        return round((target_min + target_max) / 2)
    ratio = (value - source_min) / (source_max - source_min)
    return round(target_min + ratio * (target_max - target_min))


def draw_l_histogram(measurements: list[dict]) -> np.ndarray:
    """Draw a histogram over the observed median-L range."""
    l_values = np.array([item["median_l"] for item in measurements])
    data_min = int(np.floor(l_values.min()))
    data_max = int(np.ceil(l_values.max()))
    axis_min = max(0, data_min - 2)
    axis_max = min(255, data_max + 2)
    bins = np.arange(axis_min, axis_max + 2)
    counts, edges = np.histogram(l_values, bins=bins)

    canvas = np.full((CANVAS_SIZE, CANVAS_SIZE, 3), 255, dtype=np.uint8)
    left = PLOT_MARGIN
    right = CANVAS_SIZE - 30
    top = 70
    bottom = CANVAS_SIZE - PLOT_MARGIN
    cv2.line(canvas, (left, top), (left, bottom), (0, 0, 0), 2)
    cv2.line(canvas, (left, bottom), (right, bottom), (0, 0, 0), 2)

    max_count = max(int(counts.max()), 1)
    bar_width = max(1, (right - left) // len(counts))
    for index, count in enumerate(counts):
        x1 = left + index * bar_width
        x2 = left + (index + 1) * bar_width - 1
        bar_height = round((bottom - top) * int(count) / max_count)
        cv2.rectangle(
            canvas,
            (x1, bottom - bar_height),
            (x2, bottom),
            (180, 100, 30),
            -1,
        )
        if count > 0:
            cv2.putText(
                canvas,
                str(int(count)),
                (x1, bottom - bar_height - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

    tick_step = max(1, round((axis_max - axis_min) / 8))
    for value in range(axis_min, axis_max + 1, tick_step):
        x = scale_value(value, axis_min, axis_max + 1, left, right)
        cv2.line(canvas, (x, bottom), (x, bottom + 6), (0, 0, 0), 1)
        cv2.putText(
            canvas,
            str(value),
            (x - 10, bottom + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    cv2.putText(
        canvas,
        "Distribution of median L",
        (left, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "Median L (observed range)",
        (CANVAS_SIZE // 2 - 120, CANVAS_SIZE - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return canvas


def draw_ab_scatter(measurements: list[dict]) -> np.ndarray:
    """Draw unique median-(a, b) pairs and their occurrence counts."""
    pairs = Counter(
        (item["median_a"], item["median_b"]) for item in measurements
    )
    a_values = [pair[0] for pair in pairs]
    b_values = [pair[1] for pair in pairs]
    a_min, a_max = min(a_values) - 2, max(a_values) + 2
    b_min, b_max = min(b_values) - 2, max(b_values) + 2

    canvas = np.full((CANVAS_SIZE, CANVAS_SIZE, 3), 255, dtype=np.uint8)
    left = PLOT_MARGIN
    right = CANVAS_SIZE - 30
    top = 70
    bottom = CANVAS_SIZE - PLOT_MARGIN
    cv2.line(canvas, (left, top), (left, bottom), (0, 0, 0), 2)
    cv2.line(canvas, (left, bottom), (right, bottom), (0, 0, 0), 2)

    for (a_value, b_value), count in pairs.items():
        x = scale_value(a_value, a_min, a_max, left, right)
        y = scale_value(b_value, b_min, b_max, bottom, top)
        radius = 5 + round(2 * np.sqrt(count))
        cv2.circle(canvas, (x, y), radius, (40, 120, 220), -1)
        cv2.putText(
            canvas,
            str(count),
            (x + radius + 3, y - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    for value in range(int(a_min), int(a_max) + 1):
        x = scale_value(value, a_min, a_max, left, right)
        cv2.putText(
            canvas,
            str(value),
            (x - 10, bottom + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    for value in range(int(b_min), int(b_max) + 1, 2):
        y = scale_value(value, b_min, b_max, bottom, top)
        cv2.putText(
            canvas,
            str(value),
            (15, y + 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    cv2.putText(
        canvas,
        "Median a-b distribution",
        (left, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "median a",
        (CANVAS_SIZE // 2 - 40, CANVAS_SIZE - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "median b",
        (8, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "Circle labels show repeated measurements",
        (right - 310, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return canvas


def print_summary(measurements: list[dict]) -> None:
    """Print feature ranges and bricks ordered by median L."""
    print("Observed Lab ranges")
    for key in ("median_l", "median_a", "median_b", "l_spread"):
        values = [item[key] for item in measurements]
        print(f"  {key:<9}: {min(values):.2f} to {max(values):.2f}")

    print("\nBricks ordered by median L")
    print("ID         median L   median a   median b   L spread")
    for item in sorted(measurements, key=lambda value: value["median_l"]):
        print(
            f'{item["id"]:<10} '
            f'{item["median_l"]:>8.2f} '
            f'{item["median_a"]:>10.2f} '
            f'{item["median_b"]:>10.2f} '
            f'{item["l_spread"]:>10.2f}'
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visualize Lab measurements produced by measure_lab.py."
    )
    parser.add_argument("measurements", type=Path, help="Lab measurements JSON")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (defaults to the measurements directory)",
    )
    args = parser.parse_args()

    output_directory = args.output_dir or args.measurements.parent
    l_histogram_path = output_directory / "l_histogram.png"
    ab_scatter_path = output_directory / "ab_scatter.png"
    measurements = load_measurements(args.measurements)
    l_histogram = draw_l_histogram(measurements)
    ab_scatter = draw_ab_scatter(measurements)

    output_directory.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(l_histogram_path), l_histogram):
        raise OSError(f"Could not write histogram: {l_histogram_path}")
    if not cv2.imwrite(str(ab_scatter_path), ab_scatter):
        raise OSError(f"Could not write scatter plot: {ab_scatter_path}")

    print_summary(measurements)
    print(f"\nL histogram: {l_histogram_path}")
    print(f"a-b scatter: {ab_scatter_path}")


if __name__ == "__main__":
    main()
