# 数据契约

每个数据目录必须有manifest.json，记录非空来源 `source`、显式布尔值 `is_synthetic`、行业分类和数据文件的SHA-256。缺少模拟标记的未知数据不默认为真实数据。运行时校验；拒绝篡改数据及非空输出目录。

表可保存为 `.csv` 或 `.parquet`，字段契约相同。Parquet需要 `parquet` 可选依赖（PyArrow）。日期可为date列；prices/styles也可使用命名为date的索引。表的读取不触发米筐认证或联网下载。

本机下载成功时同时生成 `quality_report.json` 和 `quality_report.md`，记录行数、日期、OHLC边界、缺失值、量额与日历检查、可用核心特征行数。数据表和质量报告均纳入清单哈希；JSON统一UTF-8。`regime-research validate-data --data <目录>` 使用与研究流水线相同的加载器重新验证文件与OHLC，不联网、不拟合模型；该离线命令不能独立核对供应商交易日历。

| 文件 | 字段 | 要求 |
|---|---|---|
| prices.csv / prices.parquet | date,open,high,low,close,volume,total_turnover | 唯一升序市场交易日，OHLC正数，量额非负，无缺失 |
| industry_panel.csv / .parquet | date,industry_id,close,total_turnover | 至少4个行业，固定分类，完整面板 |
| stock_panel.csv / .parquet | date,order_book_id,close | 一致复权，上市前退市后可缺失，不前填 |
| membership.csv / .parquet | date,order_book_id,eligible | 对面板每一日期证券明确0/1，历史名单而非今天名单 |
| styles.csv / .parquet | date,small_close,large_close | 同一日历的大小盘指数 |

核心版只需prices表；论文版全部需要且须列入清单。宽度采用历史基准成分，不直接等于全部A股。下载器逐日index_components取并集，分批下载价格；排除当日无成交量或少于60日历史的股票，未额外排除ST。

新清单使用 `logical_tables`，如 `{"prices": "prices.parquet", "styles": "styles.csv"}`，映射到的数据文件必须列在 `sha256` 中。旧清单没有映射时，按已哈希的同名CSV/Parquet查找；同一表同时出现两种格式时拒绝歧义，必须明确映射。拒绝路径逃逸与指向数据目录外部的符号链接。哈希证明文件一致性，不能认证来源真实性。

历史名单是供应商当前返回的历史快照，并不证明获得了原始公布时点或历史版本。股票pre复权只用于比例／宽度，同一股票共同尺度抵消；固定快照和哈希不能自动排除所有公司行动口径问题或供应商修订。市场和行业用指数价格。

已核对rqdatac 3.8.1的init/get_price/get_trading_dates/index_components签名，真实服务器尚未请求。代码复用SDK原生认证配置，禁用自动SDK插件加载，不输出凭据。

安全设置RQDATAC_LICENSE_KEY（licence模式）、RQDATAC_USERNAME/RQDATAC_PASSWORD或RQDATAC_CONF/RQDATAC2_CONF。本机脚本可用 `--prompt-license` 隐藏输入。原生URI含凭据，不能提交Git或贴到对话。平台HTTPS代理注入的占位密钥不一定适用于专用TCP协议，需要核验实际认证。

SDK默认rqdatad-pro.ricequant.com:16011；平台须支持对应TCP目的地或认可的SDK代理。仅加入HTTPS白名单不够；不关闭验证、不改路由绕过策略。账号、行业权限和TCP连接尚未验证。

## 导入外部CSV/Parquet

在有RQData权限的本机按契约导出，可用项目函数登记：

```python
from regime_research.datasets import dataset_manifest
dataset_manifest('data/imported', {
    'source': 'ricequant_offline_export',
    'is_synthetic': False,
    'industry_classification': '真实使用的行业分类版本',
    'industry_contributions': 'equal_weight_index_return_proxy',
    'export_note': '说明历史股票池、复权和数据版本',
})
```

函数只记录声明和哈希，不替代来源真实性与时点性审计。不要把模拟文件重新登记为非模拟；离线夹具不得用作真实数据结果。数据和原始论文附件不自动提交Git。
