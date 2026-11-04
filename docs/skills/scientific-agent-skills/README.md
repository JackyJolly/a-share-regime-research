# Scientific Agent Skills 安装审查

已按用户的 `npx skills add K-Dense-AI/scientific-agent-skills` 请求，以项目级方式安装全部 177 个 Skills。来源版本 2.72.0，提交 `a25cf9ec00e2745d03f8704acf6f6919694ccd9a`。安装到 `.agents/skills/`，原有 Agent-Reach 保留；不代表其他项目已安装。

## 安装方式与验证

下载并核对 npm `skills@1.7.6` 的 SHA-512，静态检查其 Codex 目录、复制逻辑和遥测开关。用 `npx --yes --ignore-scripts --package /tmp/skills-1.7.6.tgz skills add /tmp/scientific-agent-skills-review --agent codex --skill '*' --copy --yes` 安装已审查的本地源码；设置 DISABLE_TELEMETRY=1 和 DO_NOT_TRACK=1，禁止 npm 生命周期脚本。

177 个 SKILL.md frontmatter 均通过解析，name 与目录名一致；安装的全部文件与该提交逐字节比较通过，SHA-256 记录在 PROVENANCE.json。没有执行任何科研脚本。安装器生成的本地来源 skills-lock.json 指向临时目录，已删除，以本目录包含提交和逐文件哈希的 PROVENANCE.json 为持久来源记录。重新安装时应先克隆来源、检出上述精确提交再用 skills CLI 安装本地路径，不直接更新到 main。

Codex 目录格式兼容，Node 24.22.1 满足安装器 >=22.20.0。新任务的自动发现和全部科研工作流均未验证。本会话不假定热加载新 Skills。

## 功能、依赖与风险

覆盖生物、化学、医学、物理、工程、统计、机器学习、金融数据库、时间序列和科研写作。inventory.json 记录全部名称、功能说明、兼容性声明、脚本数量与静态风险类别。

总计 536 个 Python/shell/JS/R 等脚本文件。全部文档及常见文本代码做模式扫描：177 个 Skills 含网络地址或联网模式、63 个含凭据模式、43 个含子进程模式、31 个含文件删除模式、121 个含依赖安装模式。命中只是审查线索，不等同于漏洞。Python 文件全部可 AST 解析，所查 eval/exec/os.system/pickle.load(s)/shell=True 模式无命中；这不能排除其他危险调用或逻辑问题。

重点查看了上游 SECURITY.md、security-triage.md、安装器代码、依赖声明以及代表性的时间序列、科研写作、研究检索、autoskill 文档/代码。上游安全报告含误报、未完成分析及历史修复，不能作为完整安全认证。本次不是对 177 个 Skills 全部代码及传递依赖的逐行安全审计。

- API、数据库检索或云服务可能读取 API keys、上传输入内容、产生费用；按具体任务确认目的地与凭据。
- autoskill 可分析 screenpipe 屏幕历史；此次未安装 screenpipe、未启用录屏、未读取历史。需单独明确授权。
- 模型下载、反序列化、GPU/HPC/云计算、实验室接口、子进程和文件覆盖/删除均需用前审查。
- 文档中的安装命令只是指导，不自动授权执行；根 AGENTS.md 保存了使用约束。
- 上游开发/测试项目要求 Python >=3.13；当前 Python 3.12.14 不满足。不同 Skills 的依赖版本和平台也可能冲突，不做全局一揽子安装。upstream-skill-requirements.toml 是供参考的原始依赖清单，不是已验证的锁文件。

根 MIT 许可证在 LICENSE.md；技能内部自带许可证原样保留。

## 格式检查

`git diff --cached --check` 报告已导入上游文件的空白格式问题（如尾随空格或 EOF 空行），因此该项未通过。为维持逐字节来源校验，未修改第三方原文；这不影响安装文件完整性验证。
