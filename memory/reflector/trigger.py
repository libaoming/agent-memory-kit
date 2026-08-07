"""trigger.py — Reflector 触发策略：warm-up 递增阈值 + idle 兜底 + 整理节流。

borrow 自 TencentDB-Agent-Memory 的 pipeline-manager（MemoryCore/src/utils/pipeline-manager.ts）。
解决的冷启动两难：批处理阈值定高了 → 新 Doer 跑了半天一条记忆都没沉淀；定低了 → 稳态下
每条 trace 都打一次 LLM，浪费。TDB 的解法：阈值从 1 起步、每成功跑一批翻倍，直到稳态值——
第 1 条 trace 就出第一批记忆，稳态后回到省钱的批处理节奏。

纯逻辑无 IO、无时钟：宿主（cron / Stop hook / daemon）自行喂 n_pending 与 idle 秒数。
"""
from __future__ import annotations


class WarmupTrigger:
    """Reflector（critic+librarian）该不该对攒下的 trace 跑一轮提炼。

    - warm-up：阈值 1→2→4→…→steady_batch（每成功一批翻倍，record_batch_done() 推进）
    - idle 兜底：不足一批但已闲置 idle_seconds，也触发——凑不满批的尾巴不会永远等下去
    - 整理节流（consolidation_due）：librarian 重整 store（合并/压缩）的「只提前不推迟」
      节奏——有新写入最快 floor_s 一次，没动静也最慢 ceil_s 兜底跑一次
    """

    def __init__(self, steady_batch=5, idle_seconds=60,
                 consolidate_floor_s=15 * 60, consolidate_ceil_s=60 * 60):
        if steady_batch < 1:
            raise ValueError("steady_batch 至少为 1")
        if idle_seconds <= 0:
            raise ValueError("idle_seconds 必须 >0（=0 时任何 pending 立即触发，warm-up 形同虚设）")
        if consolidate_floor_s > consolidate_ceil_s:
            raise ValueError("consolidate_floor_s 不得大于 ceil_s（否则「只提前不推迟」语义反转）")
        self.steady_batch = steady_batch
        self.idle_seconds = idle_seconds
        self.consolidate_floor_s = consolidate_floor_s
        self.consolidate_ceil_s = consolidate_ceil_s
        self.threshold = 1  # warm-up 从 1 起步：冷启动首条 trace 即触发

    def should_reflect(self, n_pending: int, idle_s: float = 0.0) -> bool:
        if n_pending <= 0:
            return False
        return n_pending >= self.threshold or idle_s >= self.idle_seconds

    def record_batch_done(self) -> None:
        """成功跑完一批后调用：阈值翻倍，封顶稳态值。失败不调（保持低阈值尽快重试）。"""
        self.threshold = min(self.threshold * 2, self.steady_batch)

    def consolidation_due(self, seconds_since_last: float, has_new_writes: bool) -> bool:
        if seconds_since_last >= self.consolidate_ceil_s:
            return True
        return has_new_writes and seconds_since_last >= self.consolidate_floor_s
