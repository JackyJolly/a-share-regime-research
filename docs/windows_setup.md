# Windows 11 本机部署与真实米筐数据

适用：Windows 11 x64、Windows PowerShell 5.1 或 PowerShell 7、Python 3.12 x64。
工作分支为 `research/ricequant-regime-framework`；不需要修改或合并 `main`。
本页所有命令在仓库根目录执行，均使用 PowerShell 语法。

云端当前未能连接米筐专用 TCP 服务，因此本次没有下载真实行情、没有验证你的 licence 权限，也没有生成实证结果。
下面的真实下载必须在能访问 `rqdatad-pro.ricequant.com:16011` 的本机完成。

## 1. 安装工具并取得代码

若尚未安装 Python 3.12 x64 和 Git，在 PowerShell 运行：

```powershell
winget install --exact --id Python.Python.3.12 --source winget
winget install --exact --id Git.Git --source winget
```

安装完成后重新打开 PowerShell。首次克隆使用：

```powershell
py -3.12 --version
git --version
git clone --branch research/ricequant-regime-framework --single-branch https://github.com/JackyJolly/a-share-regime-research.git
Set-Location .\a-share-regime-research
```

如果本机已有仓库，进入它后检查 `git status --short --branch`；仅在当前就是研究分支且工作区干净时执行 `git pull --ff-only origin research/ricequant-regime-framework`。有未提交修改时先保留工作，不要 reset、覆盖或删分支；也可以克隆到另一个新目录。

## 2. 建立隔离环境、安装固定版本

```powershell
$env:PYTHONUTF8 = "1"
py -3.12 -m venv .venv
$ResearchPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $ResearchPython -m pip install --only-binary=:all: -r .\requirements.txt
& $ResearchPython -m pip install --no-deps -e .
& $ResearchPython -m pip check
& $ResearchPython .\scripts\download_sample.py --help
```

每一步出现错误时先停止处理该错误，不继续下载。无需激活虚拟环境，也无需修改 PowerShell ExecutionPolicy。
已存在的其他项目虚拟环境不要复用；上述 `.venv` 应属于本项目。

`requirements.txt` 从 `uv.lock` 导出，固定直接和传递依赖并保留平台标记，包括 rqdatac 3.8.1、pandas 2.3.3、PyArrow 24.0.0、hmmlearn 0.3.3、pytest 9.2.0；Python 3.12 对应 NumPy 2.5.4。
Windows 需要的 colorama、win-inet-pton 和 tzdata 也列入依赖。锁文件中的35项 Windows/Python 3.12 依赖均有兼容 wheel 记录；本次是在 Linux 核查，不能代替 Windows 实机安装。
项目自身以 editable 模式安装，构建后端由 `pyproject.toml` 声明。无需安装仓库中所有第三方 Skills 的依赖。

开发者更新依赖后，可用 `uv export --frozen --all-extras --no-emit-project --no-hashes --no-annotate --output-file requirements.txt` 重新导出，不手工升级单个包破坏版本一致性。

## 3. 先运行离线测试

```powershell
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MPLBACKEND = "Agg"
& $ResearchPython -m pytest
```

这些测试无需 licence、不请求米筐。假 SDK/生成数据只位于测试临时目录，用来验证软件契约，不能当作真实市场观测。
Windows 没有符号链接权限时，单个符号链接安全测试会注明原因后跳过；其余测试仍应通过。hmmlearn/NumPy 的既有弃用警告不等于测试失败。

## 4. 安全设置本机 licence 环境变量

若本 PowerShell 进程已有 `RQDATAC_LICENSE_KEY`，直接保留。只有尚未配置时，运行下面的隐藏输入流程；粘贴到提示中，而不是命令文本中：

```powershell
if (-not $env:RQDATAC_LICENSE_KEY) {
    $RicequantSecret = Read-Host "Ricequant License (hidden)" -AsSecureString
    $RicequantPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($RicequantSecret)
    try {
        $env:RQDATAC_LICENSE_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($RicequantPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($RicequantPointer)
        $RicequantSecret.Dispose()
        Remove-Variable RicequantSecret, RicequantPointer
    }
}
if ($env:RQDATAC_LICENSE_KEY) { "RQDATAC_LICENSE_KEY exists" } else { throw "RQDATAC_LICENSE_KEY missing" }
```

只输出是否存在。密钥仅供当前进程及其 Python 子进程读取，不写入源码、YAML、requirements、报告或 Git。
不要运行会输出 licence 的 `rqdatac.info()`，也不要打印环境变量值。新 PowerShell 窗口需要重新设置。

## 5. 下载沪深300最近60个完整交易日

```powershell
& $ResearchPython .\scripts\download_sample.py --output .\data\hs300-60
if ($LASTEXITCODE -ne 0) { throw "Download failed; do not treat partial files as a dataset." }
```

下载器固定使用沪深300 `000300.XSHG`，先通过 `get_trading_dates(..., market="cn")` 选择最后60个交易日，再调用：

```python
client.get_price("000300.XSHG", start_date=start, end_date=end,
                 frequency="1d", adjust_type="none", expect_df=True,
                 fields=["open", "high", "low", "close", "volume", "total_turnover"])
```

额外保存成交额 `total_turnover`，供研究特征使用。SDK 返回的单证券 MultiIndex 会规范为唯一升序 `date`；接口包含起止日，下载后再次核对完整交易日历及恰好60行。
初始化通过 `rqdatac.init("license", os.environ["RQDATAC_LICENSE_KEY"], ...)` 的等价封装完成，关闭自动插件加载，屏蔽 SDK 敏感诊断与异常文本。

“最近”默认截至**运行时上海日期的前一自然日**，从米筐日历中取最近60个交易日，自动处理周末及法定休市，不使用60个自然日或60个普通工作日代替。
即使今天已收盘也默认排除今天，以免日线尚未入库。可加 `--end-date YYYY-MM-DD` 冻结更早截止日，但必须早于当前上海日期。

成功目录包含：

| 文件 | 内容 |
|---|---|
| `prices.parquet` | 60行真实SDK返回的OHLCV与成交额，date列 |
| `manifest.json` | 来源声明、代码、日期、行数、文件映射和SHA-256 |
| `quality_report.json` | 可机读的数据质量与研究就绪情况 |
| `quality_report.md` | 可读质量报告 |

质量检查涵盖日期唯一升序、交易日覆盖、空值/无穷值、正价格、OHLC边界、量额非负；零量/零额单独计数。发现问题即失败，不前填、不生成替代数据。
目录只有在表、质量报告、清单均写入并验证后才整体发布。失败时可能留下 `.hs300-60.download-*` 和 `INCOMPLETE.json`，研究入口拒绝加载这些半成品。
重复下载请使用新输出目录（例如 `data/hs300-60-v2`），既有非空目录不会覆盖。

## 6. 不联网验证本地数据可供研究模块读取

```powershell
& $ResearchPython -m regime_research.cli validate-data --data .\data\hs300-60
if ($LASTEXITCODE -ne 0) { throw "Local dataset validation failed." }
Get-Content -Encoding UTF8 .\data\hs300-60\quality_report.md
```

`validate-data` 与 `run_research` 共用 `verify_manifest`、`resolve_table`、`read_prices`，兼容CSV/Parquet并复核哈希。成功应看到 `ok: true`、`status: passed`、`rows: 60`、`market_index: 000300.XSHG`、`is_synthetic: false`、`hash_verified: true`。
离线复核不能独立认证数据来源或重新查询交易所日历，输出的 `exact_requested_calendar: null` 表示这一点；下载时质量报告中的该检查应为 `true`。

**60日样本只用于安装、认证、下载和读取验收。** 核心特征含252日滚动窗口，基准模型还需504个有效训练样本及后续样本外观测，因此样本的 `usable_core_feature_rows` 应为0，不运行GMM/HMM来凑结论。
模型不降低研究门槛来适配这个小样本。

## 7. 后续下载长期真实样本并运行研究

首次60日验收成功后，检查 `configs/hs300_local.yaml` 的研究日期范围（默认2010-01-01至2026-11-04），确认账号历史权限及配额，然后执行：

```powershell
& $ResearchPython .\scripts\download_ricequant.py --config .\configs\hs300_local.yaml --output .\data\hs300-long --format parquet
if ($LASTEXITCODE -ne 0) { throw "Long sample download failed." }
& $ResearchPython -m regime_research.cli validate-data --data .\data\hs300-long
if ($LASTEXITCODE -ne 0) { throw "Long sample validation failed." }
& $ResearchPython -m regime_research.cli run --config .\configs\hs300_local.yaml --data .\data\hs300-long --output .\outputs\hs300-long --profile core
```

需要CSV时把下载命令的 `--format parquet` 改为 `--format csv`，研究命令保持不变。
指数核心版不等同于论文全量研究。论文版还需在 `configs/paper.yaml` 配置获得许可的行业代码与固定分类，下载历史成分、个股和风格面板；不能用沪深300单表代替这些输入。

云端无需再连接米筐：将整个完成的数据目录（含manifest与质量报告）传到云端，按相同 `validate-data` 和 `run` 命令加载即可。真实数据位于被Git忽略的 `data/`，不随代码提交。

本机结束后可清除当前进程密钥：

```powershell
Remove-Item Env:RQDATAC_LICENSE_KEY -ErrorAction SilentlyContinue
```

## 故障判断与验收边界

本机遇到网络错误时，可各检查一次：

```powershell
Resolve-DnsName rqdatad-pro.ricequant.com
Test-NetConnection rqdatad-pro.ricequant.com -Port 16011
```

DNS失败与TCP失败分开判断；成功连接端口仍不证明 licence 有效或具备对应行情权限。若通过单位认可的TCP代理访问，直接端口测试也不能代表代理链路；按米筐SDK及本单位规定设置代理，不关闭安全校验或绕过网络策略。HTTP/HTTPS代理通常不能直接替代SDK专用TCP连接。一次失败后先解决网络/授权原因，不循环重试下载。

本次已完成：SDK 3.8.1源码/API签名核对、Linux离线测试、Windows依赖wheel静态匹配；新增Windows离线CI作后续持续验证。
必须在本机完成：Windows安装、真实DNS/TCP与代理可达性、licence认证与配额、沪深30060日真实下载、生成并查看实际质量报告、真实文件离线读取；长期研究还需全量数据验收。
哈希和质量检查不证明经济结论，也不排除供应商历史修订。此文档未声称Windows实机或真实数据验收已经通过。
