# 复现实验协议

1. 先核验RQData权益、专用TCP、交易日、市场指数、历史成分和固定行业版本；数据缺失不是经济状态。
2. 冻结数据目录、哈希、获取时间、复权、股票池；不提交授权行情或凭据。
3. 区分核心长样本和扩展短样本。252日因子预热消耗样本；论文配置1200日初训加预热后约2016年开始OOS，精确日期以真实日历为准。
4. 看OOS结果前固定K、特征、协方差、窗口、成本和策略集合。smoke配置只作验收。
5. 首个训练窗K=2..6 BIC只是诊断；不允许按已看过的OOS收益调参。预留最终独立检验期。
6. 每次新建输出目录。run_manifest.json记录参数、数据哈希、代码提交、源码哈希、依赖版本；未提交修改标记dirty。
7. 先检查训练时序、概率、收敛、小簇和独立事件，再看收益。允许标签无法解释，不凑四类机制。
8. HAC/BH不覆盖研究者的全部模型搜索，也不证明预测和因果。真实结果才可填入论文表格。
9. 并列运行核心/论文、GMM/HMM、固定/条件配置；不同特征密度不能直接比较。

```bash
uv sync --frozen --extra dev --extra ricequant --extra hmm --python 3.12
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 uv run --frozen pytest
uv run --frozen regime-research synthetic --output data/smoke --periods 1800
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 uv run --frozen regime-research run \
  --config configs/smoke.yaml --data data/smoke --output outputs/smoke-paper --profile paper
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 uv run --frozen regime-research run \
  --config configs/smoke.yaml --data data/smoke --output outputs/smoke-hmm --profile paper --model hmm
```

测试覆盖价格与交易日、数据篡改、历史分母、全负行业、GMM/HMM预测前缀不变性、案例截止与间隔、成交/成本日期、漂移、风险平价、HAC/BH和端到端流程。CI仅用模拟数据，不依赖米筐凭据。
