"""预测追踪系统——记录每次预测，与实际结果比对，持续校准模型。

工作原理:
1. 每次运行记录: 时间、预测区间、实际价格
2. 积累足够数据后计算: 准确率、偏差方向、校准系数
3. 将校准结果反馈到评分模型

线程安全:
- 所有读写操作通过文件锁 (lock file + retry) 保护
- 写入采用 temp file + atomic rename，避免半写损坏
- 每次写入前自动备份 (.bak)，损坏时自动恢复
- 旧记录自动归档 (>60天 → .archive.json)
"""

import csv
import json
import os
import statistics
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

TRACKER_DIR = Path(".prediction_history")
ARCHIVE_DAYS = 60  # 超过60天的记录自动归档
LOCK_TIMEOUT = 10  # 锁等待超时（秒）
LOCK_RETRY_INTERVAL = 0.1  # 锁重试间隔（秒）


def _ensure_tracker_dir() -> None:
    """延迟创建追踪目录，避免模块导入时副作用。"""
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)


# ====== 文件锁（跨平台，基于 lock file） ======

class FileLock:
    """跨平台文件锁。使用 .lock 文件 + 轮询实现。

    比 fcntl/msvcrt 更可移植，适合低并发 Cron 场景。
    """

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT):
        self._lock_path = Path(str(path) + ".lock")
        self._timeout = timeout
        self._acquired = False

    def acquire(self) -> bool:
        """获取锁，返回是否成功。"""
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            try:
                # O_CREAT | O_EXCL — 仅当文件不存在时创建成功（原子操作）
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, f"{os.getpid()}\n{time.time()}".encode())
                os.close(fd)
                self._acquired = True
                return True
            except FileExistsError:
                # 检查锁是否过期（持有者可能崩溃）
                try:
                    lock_age = time.time() - self._lock_path.stat().st_mtime
                    if lock_age > LOCK_TIMEOUT * 2:
                        # 锁过期，强制删除
                        self._lock_path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(LOCK_RETRY_INTERVAL)
            except OSError:
                time.sleep(LOCK_RETRY_INTERVAL)
        return False

    def release(self) -> None:
        """释放锁。"""
        if self._acquired:
            try:
                self._lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._acquired = False

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"无法获取文件锁: {self._lock_path} (超时 {self._timeout}s)")
        return self

    def __exit__(self, *args):
        self.release()


# ====== 原子读写 ======

def _atomic_write(path: Path, records: list[dict]) -> None:
    """原子写入：先写临时文件，再 os.replace 原子替换。

    os.replace 在 POSIX 和 Windows 上都是原子操作。
    """
    tmp_path = Path(str(path) + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp_path), str(path))


def _load_records_safe(stock_code: str) -> list[dict]:
    """安全加载记录——自动从备份恢复损坏文件，兼容 GBK 和 UTF-8 编码。"""
    path = _records_path(stock_code)
    bak_path = Path(str(path) + ".bak")

    if not path.exists():
        # 尝试从备份恢复
        if bak_path.exists():
            try:
                records = _try_decode(bak_path)
                _atomic_write(path, records)
                return records
            except (json.JSONDecodeError, OSError):
                pass
        return []

    try:
        return _try_decode(path)
    except (json.JSONDecodeError, OSError):
        # 主文件损坏，尝试从备份恢复
        if bak_path.exists():
            try:
                records = _try_decode(bak_path)
                _atomic_write(path, records)
                return records
            except (json.JSONDecodeError, OSError):
                pass
        return []


def _try_decode(filepath: Path) -> list[dict]:
    """尝试用 UTF-8 和 GBK 编码读取 JSON 文件。"""
    raw = filepath.read_bytes()
    # 先试 UTF-8（新文件统一编码）
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    # 回退 GBK（兼容旧文件）
    return json.loads(raw.decode("gbk"))


def _save_records_safe(stock_code: str, records: list[dict]) -> None:
    """安全保存记录——带锁 + 原子写入 + 自动备份 + 归档。

    注意：此函数不持有跨读写的锁，仅保护写入操作本身。
    如需原子的「读取→修改→写入」，使用 record_prediction/backfill_actual。
    """
    _ensure_tracker_dir()
    path = _records_path(stock_code)

    with FileLock(path):
        _atomic_write_with_backup(path, records)

    # 自动归档旧记录（不持锁时进行）
    _auto_archive(stock_code)


def _auto_archive(stock_code: str) -> None:
    """将超过 ARCHIVE_DAYS 天的记录移至归档文件。"""
    path = _records_path(stock_code)
    archive_path = Path(str(path) + ".archive.json")
    if not path.exists():
        return

    cutoff = datetime.now() - timedelta(days=ARCHIVE_DAYS)
    with FileLock(path):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        active = []
        archived = []
        for r in records:
            try:
                ts = datetime.fromisoformat(r["timestamp"])
            except (KeyError, ValueError):
                active.append(r)
                continue
            if ts < cutoff:
                archived.append(r)
            else:
                active.append(r)

        if not archived:
            return

        # 加载已有归档
        existing_archive = []
        if archive_path.exists():
            try:
                existing_archive = json.loads(archive_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        # 写入活跃记录
        _atomic_write(path, active)

        # 追加到归档
        existing_archive.extend(archived)
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(existing_archive, f, ensure_ascii=False, indent=2)

# ====== 记录预测 ======

def record_prediction(
    stock_code: str,
    predicted_low: float,
    predicted_high: float,
    predicted_close: float,
    current_price: float,
    confidence: str = "中",
) -> int:
    """记录一次预测。返回记录 ID。

    线程安全：整个「读取→追加→写入」在文件锁保护下完成。
    """
    _ensure_tracker_dir()
    path = _records_path(stock_code)

    with FileLock(path):
        records = _load_records_safe(stock_code)
        record_id = len(records) + 1

        records.append({
            "id": record_id,
            "timestamp": datetime.now().isoformat(),
            "date": date.today().isoformat(),
            "predicted_low": round(predicted_low, 2),
            "predicted_high": round(predicted_high, 2),
            "predicted_close": round(predicted_close, 2),
            "current_price": round(current_price, 2),
            "confidence": confidence,
            "actual_close": "",       # 后续回填
            "error": "",              # 后续回填
            "backfill_type": "",      # "auto"=30分钟自动, "manual"=手动回填
        })

        _atomic_write_with_backup(path, records)

    return record_id


def backfill_actual(stock_code: str, actual_price: float, fill_type: str = "manual",
                    min_age_minutes: int = 0) -> int:
    """回填实际收盘价，更新未回填记录。

    Args:
        stock_code: 股票代码
        actual_price: 实际价格
        fill_type: 'auto'=30分钟自动, 'manual'=手动回填
        min_age_minutes: 最少等待分钟数（auto 模式默认 30 分钟，避免盘中价格污染）

    线程安全：整个「读取→修改→写入」在文件锁保护下完成。
    """
    _ensure_tracker_dir()
    path = _records_path(stock_code)
    count = 0

    # auto 模式默认等待 30 分钟
    if fill_type == "auto" and min_age_minutes == 0:
        min_age_minutes = 30

    with FileLock(path):
        records = _load_records_safe(stock_code)
        now = datetime.now()
        for r in records:
            if r.get("actual_close"):
                continue
            # 检查时间戳，确保不会过早回填
            if min_age_minutes > 0:
                try:
                    ts = datetime.fromisoformat(r["timestamp"])
                except (ValueError, KeyError):
                    continue
                if now - ts < timedelta(minutes=min_age_minutes):
                    continue
            r["actual_close"] = round(actual_price, 2)
            r["error"] = round(actual_price - float(r.get("predicted_close", 0)), 2)
            r["backfill_type"] = fill_type
            count += 1
        if count:
            _atomic_write_with_backup(path, records)

    return count


def _atomic_write_with_backup(path: Path, records: list[dict]) -> None:
    """原子写入 + 自动备份（调用者必须持有锁）。"""
    bak_path = Path(str(path) + ".bak")
    # 备份现有文件（用二进制复制避免编码问题）
    if path.exists():
        try:
            bak_path.write_bytes(path.read_bytes())
        except OSError:
            pass
    _atomic_write(path, records)


# ====== 校准分析 ======

def compute_accuracy(stock_code: str) -> dict:
    """计算预测准确率和偏差统计。自动过滤极端异常值。"""
    records = _load_records(stock_code)
    completed = [r for r in records if r.get("actual_close")]

    if len(completed) < 3:
        return {"status": "insufficient_data", "count": len(completed)}

    # 过滤极端异常值（偏差 > max(5元, 5%当前价)）
    ref_price = float(completed[-1].get("current_price", 100))
    threshold = max(5.0, ref_price * 0.05)
    valid = [r for r in completed if abs(float(r["error"])) < threshold]
    filtered_count = len(completed) - len(valid)

    errors = [float(r.get("error", 0) or 0) for r in valid]
    abs_errors = [abs(e) for e in errors if e != 0]

    # 方向准确率——只统计明确标记为 manual 的记录
    dir_records = [r for r in valid if r.get("backfill_type") == "manual"
                   and r.get("predicted_close") and r.get("current_price")]
    direction_correct = 0
    direction_total = 0
    for r in dir_records:
        try:
            pred_change = float(r["predicted_close"]) - float(r["current_price"])
            actual_change = float(r["actual_close"]) - float(r["current_price"])
            if abs(pred_change) > 0.15 or abs(actual_change) > 0.15:
                direction_total += 1
                if (pred_change > 0 and actual_change > 0) or (pred_change < 0 and actual_change < 0):
                    direction_correct += 1
        except (KeyError, ValueError, TypeError):
            continue

    # 手动回填的方向准确率
    manual = [r for r in valid if r.get("backfill_type") == "manual"
              and r.get("predicted_close") and r.get("current_price")]
    manual_dir_correct = 0
    manual_dir_total = 0
    for r in manual:
        try:
            pred_change = float(r["predicted_close"]) - float(r["current_price"])
            actual_change = float(r["actual_close"]) - float(r["current_price"])
            if abs(pred_change) > 0.15 or abs(actual_change) > 0.15:
                manual_dir_total += 1
                if (pred_change > 0 and actual_change > 0) or (pred_change < 0 and actual_change < 0):
                    manual_dir_correct += 1
        except (KeyError, ValueError, TypeError):
            continue

    # 区间命中
    in_range = 0
    for r in valid:
        try:
            lo = float(r.get("predicted_low", 0))
            hi = float(r.get("predicted_high", 0))
            ac = float(r.get("actual_close", 0))
            if lo <= ac <= hi:
                in_range += 1
        except (KeyError, ValueError, TypeError):
            continue

    return {
        "status": "ok",
        "count": len(valid),
        "total_predictions": len(records),
        "filtered_outliers": filtered_count,
        "mae": round(statistics.mean(abs_errors), 2),
        "rmse": round(statistics.mean([e**2 for e in errors])**0.5, 2),
        "mean_bias": round(statistics.mean(errors), 2),
        "direction_accuracy": round(direction_correct / max(direction_total, 1) * 100, 1),
        "direction_total": direction_total,
        "manual_direction_accuracy": round(manual_dir_correct / max(manual_dir_total, 1) * 100, 1) if manual_dir_total >= 3 else None,
        "manual_direction_total": manual_dir_total,
        "in_range_pct": round(in_range / len(valid) * 100, 1),
    }


def get_calibration(stock_code: str) -> dict:
    """获取校准参数——用于修正后续预测。"""
    stats = compute_accuracy(stock_code)
    if stats["status"] != "ok":
        return {"bias_correction": 0.0, "range_multiplier": 1.0, "ready": False}

    # 中位数偏差 + 指数加权（排除异常值）
    records = _load_records(stock_code)
    filled = [r for r in records if r.get("actual_close") and abs(float(r.get("error", 0))) < 5.0]
    if len(filled) >= 3:
        import statistics as _st
        # 中位数偏差——比均值更稳健（不受极端值影响）
        median_bias = _st.median([float(r["error"]) for r in filled])
        # 指数加权偏差（最近10条）
        recent = filled[-10:]
        weighted = [float(r["error"]) * (1.5 ** i) for i, r in enumerate(recent)]
        ewma_bias = sum(weighted) / sum(1.5 ** i for i in range(len(weighted)))
        # 中位数和EWMA取平均
        bias = (median_bias + ewma_bias) / 2
    else:
        bias = stats["mean_bias"]

    # 样本量越大，修正力度越强
    n = len(filled)
    if n >= 30:
        correction_strength = 0.90  # 30+样本：90%修正
    elif n >= 15:
        correction_strength = 0.75
    elif n >= 5:
        correction_strength = 0.60
    else:
        correction_strength = 0.50

    # 连续命中：连续N次误差<阈值
    threshold = 0.3 if n < 10 else 0.2  # 样本多了收紧阈值
    consecutive = 0
    for r in reversed(filled):
        if abs(float(r["error"])) < threshold:
            consecutive += 1
        else:
            break

    # 区间宽度自适应（目标：95%命中率）
    in_range = stats["in_range_pct"]
    range_mult = 1.0
    if in_range < 70:
        range_mult = 1.6
    elif in_range < 80:
        range_mult = 1.40
    elif in_range < 85:
        range_mult = 1.25
    elif in_range < 90:
        range_mult = 1.15
    elif in_range < 93:
        range_mult = 1.08
    elif in_range < 95:
        range_mult = 1.03  # 接近目标，微扩
    elif in_range >= 99:
        range_mult = 0.88
    elif in_range >= 98:
        range_mult = 0.92
    elif in_range >= 96:
        range_mult = 0.96
    else:  # 95-96%
        range_mult = 1.0  # 达标，保持

    # 连续命中奖励（仅当命中率已达标时适度收窄）
    if in_range >= 95 and consecutive >= 10:
        range_mult *= 0.90
    elif in_range >= 95 and consecutive >= 5:
        range_mult *= 0.95
    elif in_range >= 90 and consecutive >= 15:
        range_mult *= 0.85  # 长期连续命中才收窄

    return {
        "bias_correction": round(bias * correction_strength, 2),
        "range_multiplier": round(range_mult, 2),
        "ready": True,
        "based_on": n,
        "direction_accuracy": stats["direction_accuracy"],
        "in_range_pct": in_range,
        "consecutive_hits": consecutive,
    }


# ====== 内部 ======

def _records_path(stock_code: str) -> Path:
    return TRACKER_DIR / f"predictions_{stock_code}.json"


def _load_records(stock_code: str) -> list[dict]:
    """加载记录（兼容旧接口，内部调用安全版本）。"""
    return _load_records_safe(stock_code)


def _save_records(stock_code: str, records: list[dict]) -> None:
    """保存记录（兼容旧接口，内部调用安全版本）。"""
    _save_records_safe(stock_code, records)
