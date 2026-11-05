# 米筐云端接入诊断（2026-11-05）

`RQDATAC_LICENSE_KEY`：存在。未输出值、长度、片段或指纹，未发送到米筐。

| 层次 | 本次观察 | 可得结论 |
|---|---|---|
| 本地DNS：rqdatad-pro.ricequant.com | getaddrinfo返回gaierror，errno=-3（EAI_AGAIN） | 当前解析临时失败；不能判定域名不存在，不能代表代理侧DNS |
| 本地DNS：TCP代理 | proxy可解析 | 代理名称解析正常 |
| TCP代理监听 | 连接平台声明的proxy:8088返回ConnectionRefusedError，errno=111 | 无法建立代理连接，尚未到达目标TCP服务；不能据此判断米筐服务器宕机 |
| TCP网络策略 | domains=[]、ip_ranges=[] | 当前没有米筐TCP目的地授权；HTTPS允许列表不等于TCP权限 |
| 身份认证 | 未尝试 | licence有效性、账号权限和配额均未验证 |

仅进行一次分层诊断；未直连、切换代理绕过策略，也未反复重试。在代理不可用且授权缺失的当前配置下，云端无法完成该TCP数据访问；这不等于平台永远不支持TCP。

采用本机下载脚本导出真实CSV/Parquet，再把包含数据清单的完整目录放入云端进行研究。软件测试使用明确标注的离线夹具，不能作为成功下载、真实账号验收或A股实证结果。
