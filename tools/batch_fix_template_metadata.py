"""
批量修复模板元数据中的 window_client_size 和 threshold
"""
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates" / "icons"


def fix_template_metadata(
    json_path: Path,
    target_width: int,
    target_height: int,
    adjust_threshold: bool = False,
    threshold_adjustment: float = -0.10,
) -> dict[str, Any]:
    """
    修复单个模板的元数据

    Args:
        json_path: 模板 JSON 文件路径
        target_width: 目标窗口宽度
        target_height: 目标窗口高度
        adjust_threshold: 是否自动调整阈值
        threshold_adjustment: 阈值调整量（负数表示降低）

    Returns:
        修改结果字典
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "error", "reason": f"读取失败: {e}"}

    original_size = data.get("window_client_size", {})
    original_width = original_size.get("width")
    original_height = original_size.get("height")
    original_threshold = data.get("threshold")

    changes = []

    # 修复 window_client_size
    if original_width != target_width or original_height != target_height:
        data["window_client_size"] = {
            "width": target_width,
            "height": target_height
        }
        changes.append(
            f"尺寸 {original_width}×{original_height} → {target_width}×{target_height}"
        )

    # 调整阈值（如果启用且当前使用默认值）
    if adjust_threshold and original_threshold is None:
        new_threshold = max(0.01, min(1.0, 0.85 + threshold_adjustment))
        data["threshold"] = round(new_threshold, 2)
        changes.append(f"阈值 默认0.85 → {new_threshold:.2f}")

    if not changes:
        return {"status": "skip", "reason": "无需修改"}

    # 写回文件
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return {"status": "error", "reason": f"写入失败: {e}"}

    return {"status": "updated", "changes": changes}


def batch_fix_templates(
    templates_dir: Path,
    target_width: int,
    target_height: int,
    adjust_threshold: bool = False,
    threshold_adjustment: float = -0.10,
    dry_run: bool = False,
) -> None:
    """
    批量修复所有模板元数据
    """
    json_files = list(templates_dir.rglob("*.json"))

    if not json_files:
        print(f"未找到模板文件: {templates_dir}")
        return

    print(f"找到 {len(json_files)} 个模板文件")
    print(f"目标窗口尺寸: {target_width}×{target_height}")
    print(f"调整阈值: {'是' if adjust_threshold else '否'}")
    if adjust_threshold:
        print(f"阈值调整量: {threshold_adjustment:+.2f}")
    print(f"模式: {'预览（不写入）' if dry_run else '实际修改'}")
    print("-" * 80)

    stats = {"updated": 0, "skip": 0, "error": 0}

    for json_path in sorted(json_files):
        relative_path = json_path.relative_to(templates_dir)

        if dry_run:
            # 干运行模式：只读取不写入
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                original_size = data.get("window_client_size", {})
                original_width = original_size.get("width")
                original_height = original_size.get("height")

                if original_width != target_width or original_height != target_height:
                    print(f"[预览] {relative_path}")
                    print(f"  尺寸: {original_width}×{original_height} → {target_width}×{target_height}")
                    stats["updated"] += 1
                else:
                    stats["skip"] += 1
            except Exception as e:
                print(f"[错误] {relative_path}: {e}")
                stats["error"] += 1
        else:
            # 实际修改模式
            result = fix_template_metadata(
                json_path,
                target_width,
                target_height,
                adjust_threshold,
                threshold_adjustment,
            )

            status = result["status"]
            stats[status] += 1

            if status == "updated":
                print(f"[已更新] {relative_path}")
                for change in result["changes"]:
                    print(f"  {change}")
            elif status == "error":
                print(f"[错误] {relative_path}: {result['reason']}")

    print("-" * 80)
    print(f"完成: 更新 {stats['updated']} 个，跳过 {stats['skip']} 个，错误 {stats['error']} 个")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="批量修复模板元数据")
    parser.add_argument("--width", type=int, default=1018, help="目标窗口宽度（默认 1018）")
    parser.add_argument("--height", type=int, default=632, help="目标窗口高度（默认 632）")
    parser.add_argument(
        "--adjust-threshold",
        action="store_true",
        help="自动降低没有自定义阈值的模板的匹配阈值"
    )
    parser.add_argument(
        "--threshold-adjustment",
        type=float,
        default=-0.10,
        help="阈值调整量（默认 -0.10，即从 0.85 降到 0.75）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式，不实际修改文件"
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=TEMPLATES_DIR,
        help="模板目录路径"
    )

    args = parser.parse_args()

    batch_fix_templates(
        templates_dir=args.templates_dir,
        target_width=args.width,
        target_height=args.height,
        adjust_threshold=args.adjust_threshold,
        threshold_adjustment=args.threshold_adjustment,
        dry_run=args.dry_run,
    )
