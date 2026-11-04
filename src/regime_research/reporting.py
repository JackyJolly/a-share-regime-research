from pathlib import Path
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import subprocess
import numpy as np
import pandas as pd


def write_json(path, value):
    def convert(obj):
        if isinstance(obj, (np.integer, np.floating, np.bool_)):
            return obj.item()
        if isinstance(obj, (pd.Timestamp, Path)):
            return str(obj)
        raise TypeError(type(obj).__name__)
    Path(path).write_text(json.dumps(value, default=convert, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def run_manifest(config, data_manifest, profile, feature_names):
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unknown", None
    packages = {}
    for name in ["numpy", "pandas", "scipy", "scikit-learn", "rqdatac", "hmmlearn"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not_installed"
    return {"config": asdict(config), "dataset": data_manifest, "profile": profile,
            "features": list(feature_names), "code_commit": commit, "working_tree_dirty": dirty,
            "package_versions": packages,
            "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(Path(__file__).parent.glob("*.py"))},
            "claims": {"economic_hypotheses_confirmed": False,
                       "classification_probability_is_future_crisis_probability": False}}


def charts(directory, prices, features, result, backtest, synthetic=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    directory = Path(directory)
    p = result.predictions
    title = "SYNTHETIC DATA - software validation only" if synthetic else "Market regime research - unvalidated hypotheses"
    colors = list(plt.get_cmap("tab10").colors[:len(p.filter(regex="^p_state_").columns)])
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True, constrained_layout=True)
    fig.suptitle(title)
    axes[0].plot(prices.index, prices.close, color="black", linewidth=.8)
    axes[0].scatter(p.index, prices.loc[p.index, "close"], c=[colors[int(s)] for s in p.state], s=4)
    axes[0].set_ylabel("Market index / state")
    probs = p.filter(regex="^p_state_")
    axes[1].stackplot(p.index, probs.to_numpy().T, labels=probs.columns, colors=colors, alpha=.8)
    axes[1].legend(loc="upper left", ncol=4, fontsize=8)
    axes[1].set_ylabel("Current-state probability")
    axes[2].plot(p.index, p.entropy, label="Normalized entropy")
    axes[2].set_ylabel("Uncertainty")
    fig.savefig(directory/"states.png", dpi=150); plt.close(fig)
    corr = features.corr(method="spearman")
    fig, ax = plt.subplots(figsize=(10, 9), constrained_layout=True)
    fig.suptitle(title)
    image = ax.imshow(corr, vmin=-1, vmax=1, cmap="coolwarm")
    ax.set_xticks(range(len(corr)), corr.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(corr)), corr.columns, fontsize=7)
    ax.set_title("Descriptive full-sample correlation (not used for fitting)")
    fig.colorbar(image, ax=ax)
    fig.savefig(directory/"feature_correlation.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    fig.suptitle(title)
    backtest[["strategy_equity", "benchmark_equity"]].plot(ax=ax)
    ax.set_title("Illustrative index exposure / zero-return cash / costs")
    fig.savefig(directory/"equity.png", dpi=150); plt.close(fig)


def markdown_report(directory, result, manifest, metrics):
    p = result.predictions
    synthetic = manifest["dataset"].get("is_synthetic", False)
    lines = ["# A股市场状态研究运行报告", "",
             "**模拟数据验收，不能作为A股实证证据。**" if synthetic else "真实数据运行；结论仍需独立验证与稳健性检验。", "",
             f"- 配置：{manifest['profile']} / {manifest['config']['model']['model_type']}",
             f"- 样本外预测：{len(p)} 个交易日，{p.index[0].date()} 至 {p.index[-1].date()}",
             f"- 模型重估：{len(result.fits)} 次；每次训练截至预测日前一交易日。",
             f"- 未通过数值收敛检查的重估：{int((~result.fits.converged.astype(bool)).sum())} 次；如非零，相关状态结论须暂缓。",
             f"- 低于配置最低簇权重的重估：{int(result.fits.small_component_warning.sum())} 次。",
             f"- 平均样本外特征对数似然：{p.oos_log_likelihood.mean():.4f}（只可在相同特征/尺度下比较）。",
             "", "## 解释边界", "",
             "稳定、趋势、分化／脆弱、危机是论文候选经济解释。数字簇不强制一一对应；",
             "candidate_label 是训练窗画像启发式匹配，允许重复或 unresolved，分数不是校准概率。",
             "行业贡献使用等权行业指数收益代理，不能解释为历史个股真实市值贡献。",
             "所有数据截至收盘；信号次日收盘执行，再下一交易日首次产生持仓收益。",
             "策略为指数价格代理，未模拟ETF跟踪、分红、税费、涨跌停、停牌或冲击成本。", "",
             "## 输出", "",
             "- features.csv：因子；predictions.csv：样本外状态、概率、熵、似然。",
             "- fits.csv / centroids.csv：训练日期、标签匹配成本、簇画像及小簇提示。",
             "- state_statistics.csv：未来5/20/60日结果、概率加权均值、HAC区间及独立片段数。",
             "- incremental_hac_regressions.csv：控制趋势/波动/可用风格后的描述性回归；报告内BH校正。",
             "- transitions_*.csv：观察到的状态转移，非GMM下一期预测。",
             "- bic_initial.csv：仅首个训练窗K=2..6诊断，不自动据此调参。",
             "- rule_predictions.csv：五类趋势规则对照；historical_analogs.csv：最新日相似案例。",
             "- backtest.csv / metrics.json：示例仓位与成本；paper模式额外输出行业策略代理。",
             "- run_manifest.json：数据哈希、参数、代码提交、源码哈希、依赖版本。", "",
             "## 研究纪律", "",
             "HAC使用h−1阶滞后处理重叠区间；BH只覆盖本报告回归系数，不能修正跨模型搜索或状态估计误差。",
             "历史相似案例在查询时点统一模型中重算概率，要求案例结果已可见且案例区间不重叠。",
             "相似性检索未完成嵌套样本外预测增益检验，不能宣称优于基准。",
             "规则、GMM和HMM的似然不能跨不同特征集直接比较；候选状态有效性仍待检验。", "",
             "![状态与概率](states.png)", "", "![特征相关性](feature_correlation.png)", "",
             "![示例净值](equity.png)", ""]
    (Path(directory)/"report.md").write_text("\n".join(lines), encoding="utf-8")
