"""兼容旧基准工具入口；实现统一位于 tools.video.benchmark_decode。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.video.benchmark_decode import main, measure, run

if __name__ == "__main__":
    raise SystemExit(main())
