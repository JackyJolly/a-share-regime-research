# A股市场状态识别研究

基于米筐RQData的日频研究框架，依据用户提供的市场状态论文初稿实现：少量统计状态、多维连续画像、滚动样本外检验。

**这是可运行的研究代码，不是已验证有效的策略。模拟数据只作软件验收；尚未连接用户米筐账号，没有真实A股实证结论。**

## 已实现

- RQData接口、交易日核对、历史成分、CSV缓存与文件哈希。
- 指数核心版和加入宽度、行业结构、大小盘风格代理的论文版。
- 训练窗去极值、MAD稳健标准化、GMM概率、跨窗标签匹配、熵与样本外似然。
- 五类趋势规则；可选HMM前向过滤对照，不将平滑概率用于交易。
- 稳定／趋势／分化脆弱／危机的候选画像，允许重复或无法匹配，不强制四标签。
- 未来5/20/60日结果、概率加权统计、HAC区间、状态片段及转移统计。
- 查询时点统一模型下的历史相似案例，排除未完成结果或相互重叠的案例。
- 行业动量、反转、风险平价和大小盘轮动代理；固定、趋势条件与状态概率条件配置对照。
- 次日收盘执行、持仓漂移、成本、研究图表、运行清单与离线CI测试。

行业贡献目前为**等权行业指数收益代理**，不冒充历史个股的真实市值收益贡献。详见[研究设计与局限](docs/research-design.md)。

## 安装

Python 3.11+，建议3.12。在仓库根目录使用uv：

```bash
uv sync --frozen --extra dev --extra ricequant --extra hmm --python 3.12
```

也可在虚拟环境 `pip install -e '.[dev,ricequant,hmm]'`；可复现版本以uv.lock为准。无需安装已导入的全部科研Skills的运行依赖。

若云环境的用户缓存目录只读，先设置 `export UV_CACHE_DIR="$PWD/.cache/uv"`；缓存已被Git忽略。

## 离线演示

```bash
uv run --frozen regime-research synthetic --output data/demo --periods 1800
uv run --frozen regime-research run --config configs/smoke.yaml \
  --data data/demo --output outputs/demo-paper --profile paper
uv run --frozen regime-research run --config configs/smoke.yaml \
  --data data/demo --output outputs/demo-hmm --profile paper --model hmm
uv run --frozen pytest
```

查看输出目录的report.md、状态／概率图、因子相关图、净值图与CSV。**模拟结果不构成A股证据。** 每次使用新的输出目录，防止覆盖实验。

## 米筐真实数据

licence认证优先在安全的环境设置中填写RQDATAC_LICENSE_KEY；代码使用官方的 `rqdatac.init("license", key)`。也支持RQDATAC_USERNAME／RQDATAC_PASSWORD或SDK原生RQDATAC_CONF／RQDATAC2_CONF。不要将值放进对话、YAML、Git或命令历史；不要运行会打印licence的SDK `info()`。

```bash
# 先验证账号、行情字段与交易日。
uv run --frozen regime-research fetch --config configs/baseline.yaml --output data/rq-core
uv run --frozen regime-research run --config configs/baseline.yaml \
  --data data/rq-core --output outputs/rq-core --profile core
```

论文版先在configs/paper.yaml填写账号有权访问的固定版本行业指数代码与industry_classification。未填写时明确拒绝下载，不编造代码。

```bash
# 历史每日成分和个股面板请求量较大，先确认配额。
uv run --frozen regime-research fetch --config configs/paper.yaml \
  --output data/rq-paper --with-panels
uv run --frozen regime-research run --config configs/paper.yaml \
  --data data/rq-paper --output outputs/rq-paper --profile paper
```

RQData SDK 3.8.1默认连接rqdatad-pro.ricequant.com:16011，使用专用TCP协议。**允许HTTPS域名不等于允许这条TCP连接。** 云端需要平台支持相应目的地或认可的SDK代理；本项目不绕过网络策略。真实账号、行业权限及TCP可达性尚未验证。

在当前托管环境，程序先检查TCP授权，再使用平台声明的CONNECT代理；没有授权时在发送凭据前停止。2026-11-04检查发现TCP允许列表为空，声明的CONNECT代理连接被拒绝；因此尚未验证licence有效性，也未下载真实数据。环境草稿已登记RQDATAC_LICENSE_KEY需求，但未填入或保存密钥值。

## 目录

```text
configs/                 核心、论文、模拟验收配置
src/regime_research/
  data.py datasets.py    RQData、CSV、历史成分、来源清单
  features.py panels.py  指数、股票宽度、行业、风格特征
  model.py hmm.py        GMM、实时HMM、训练窗处理与标签对齐
  interpretation.py      候选经济画像
  evaluation.py inference.py  未来结果、HAC、描述性回归
  similarity.py          历史案例查询
  strategies.py          延迟执行、持仓漂移、行业与风格代理
  pipeline.py reporting.py cli.py  流水线、图表和命令行
tests/                   反前视、数据接口与端到端测试
data/ outputs/           本地数据和结果，Git忽略
.agents/skills/          项目级Skills
```

详细说明：[研究设计](docs/research-design.md)、[数据契约](docs/data-contract.md)、[实验协议](docs/experiment-protocol.md)、[当前验证记录](docs/validation.md)。
