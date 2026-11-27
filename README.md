# DFO Homebush Offer Verification Agent

> **About this repository.** This is a public snapshot of a private audit repository, exported from its commit `11bdbb8` with a fresh Git history. Commit SHAs mentioned below (such as `e215b10`, `40a9fe9` and the tag `v0.4-judge`), as well as PR numbers and links, refer to that private repository. The authoritative replay of each cassette, at the commit it was recorded on, was done there. This snapshot provides the source code, frozen data, run records (the three cassettes in `results/c_arm/` are kept byte for byte) and results for inspection.
>
> What you can reproduce here: the tests, the offline A/B evaluation and the frozen-file checksums. Replaying a cassette here runs it against the current v0.4 code, not the code it was recorded with, so it is not an authoritative check: the BF26 cassette still replays 15/15, while the candidate cassettes recorded at `e215b10` show mismatches wherever the v0.4 judge decides differently. The `replay` command will also suggest a `git worktree` command for the recording commit, which exists only in the private repository.
>
> **关于本仓库。** 本仓库是私有审计仓库的公开快照，从其提交 `11bdbb8` 导出，使用全新的 Git 历史。下文提到的提交 SHA（如 `e215b10`、`40a9fe9` 和标签 `v0.4-judge`）以及 PR 编号和链接都属于私有仓库；三份 cassette 在各自录制提交上的权威回放也在那里完成。本快照提供源码、冻结资料、运行记录（`results/c_arm/` 下的三份 cassette 保持原始字节）和结果，供检查。
>
> 在这里可以自行复现：测试、A/B 离线评测和冻结文件校验和。在这里回放 cassette 用的是当前 v0.4 代码，而不是录制时的代码，不算权威核验：BF26 的录制仍然 15/15 一致；在 `e215b10` 录制的候选案例，凡是 v0.4 判定器判法不同的地方都会显示不一致。`replay` 给出的录制提交 `git worktree` 命令，所指提交只存在于私有仓库。

**Does a given Black Friday offer actually apply at the DFO Homebush outlet store in Sydney?** Brand pages, mall flyers and store directories often disagree, or leave out conditions such as "members only" or "excludes Factory Outlets". This project answers that question with a cited verdict of *applies* / *does not apply* / *insufficient evidence*. It reads official sources one at a time under a fixed budget, and records every step so each verdict can be audited and reproduced.

It is also a small, controlled testbed for **evidence-gathering agents**. Three strategies share the same reader, budget and judge, and differ only in how they pick the next document to read:

| Arm | Strategy |
| --- | --- |
| A | Fixed order by source type |
| B | Rule-based: picks the next source from what evidence is still missing |
| C | LLM agent via LiteLLM tool calling (`read_evidence` / `finish`) |

**Highlights**

- **Bounded, auditable agent**: the LLM only chooses which document to read next. At most 3 documents and 3 model calls are allowed per case. The backend reads documents, checks that every citation was actually read, and issues the verdict.
- **Reproducible evaluation**: frozen inputs are SHA-256 checksummed, gold labels are opened only at scoring time, and per-step traces are saved as JSONL. Rerunning the offline evaluation reproduces the outputs byte for byte.
- **Full stack**: Next.js UI, FastAPI, PostgreSQL with versioned re-checks (each re-check carries the expected version; stale writes get HTTP 409), Docker Compose, Playwright end-to-end tests and GitHub Actions.

## Architecture

```mermaid
flowchart LR
    U["Browser"] --> W["Next.js web<br/>:3000"]
    W -- "/api/* (rewrite)" --> API["FastAPI<br/>:8000"]
    API --> S{"Selection strategy"}
    S -- "A: fixed order" --> R
    S -- "B: rule-based" --> R
    S -- "C: LLM via LiteLLM<br/>read_evidence / finish" --> R["Evidence reader<br/>budget: 3 documents"]
    SRC[("Frozen official sources<br/>+ maintainer library")] --> R
    R --> J["Shared judge<br/>verdict + citation check"]
    J --> API
    API --> DB[("PostgreSQL<br/>checks + revisions")]
```

## Quick start

Requires Git and Docker with Compose v2.

```bash
git clone https://github.com/Nlwuu17/dfo-homebush-offer-verifier.git
cd dfo-homebush-offer-verifier
docker compose up -d --build
```

- Open http://127.0.0.1:3000 to check an offer and save it. History is kept in PostgreSQL, and each re-check is saved as a new version.
- Open http://127.0.0.1:3000/compare to run arms A, B and C side by side on the three frozen cases.

Arms A and B run fully offline and need no API key. To enable arm C, copy `.env.example` to `.env`, set `DFO_MODEL` (e.g. `deepseek/deepseek-chat`) and the matching API key, then run `docker compose up -d --build api`.

Offline evaluation, with the Python standard library only:

```bash
python3 bf26.py eval --out "$(mktemp -d)"
```

## Current status

| Item | Result |
| --- | --- |
| Offline baseline (A, B) | 3/3 correct for both arms on 3 frozen real cases. Average documents read: A 2.67, B 2.67, under the shared stop policy (one check read after the first verdict). Under the earlier first-verdict policy B read 2.33. These cases were visible during development. |
| LLM arm (C) | 15 recorded runs (3 cases × 5) with `deepseek/deepseek-chat`: 15/15 correct, the same reading path in all 5 runs of each case, 2.33 documents read on average (same as B), 2827 ms average, about US$0.0061 in total as reported by LiteLLM. All runs replay offline from `results/c_arm/cassette.jsonl`. These are the same 3 cases that were visible during development, recorded under the earlier first-verdict stop policy and compared with A and B under that policy. |
| Held-out comparison (5 frozen cases, run once at `e215b10`) | A 3/5, B 3/5, C 3/5, with identical per-case verdicts and no technical failures; C read 12 sources, A and B 11 each. Selection differed only in paths and cost: C swapped the reading order on Sharetea and read one more source (the store page) on Portmans; neither changed a verdict. Both misses come from the shared judge, which only parses percentage discounts (buy-one-get-one is not parsed). See [results/heldout_comparison_2026_11_27.md](results/heldout_comparison_2026_11_27.md). |
| v0.4 judge, regression on known cases (23 revealed cases, tag `v0.4-judge` at `40a9fe9`) | Same 23 cases (3 BF26 + 20 candidates), all already revealed: baseline `e215b10` 15/23, v0.4 22/23 for A, B and C. 7 wrong→right, 0 right→wrong. C was re-judged on its recorded reading paths, with 0 new model calls. This is a regression check on known cases, **not** a blind test, and is not comparable with the held-out row above. See [results/regression_v0.4/](results/regression_v0.4/regression.md). |
| Mac offline full-stack acceptance | Python tests 27/27 and Playwright 3/3 passed at `2ce2f06`, including a record that survived a container rebuild. |
| Post-merge check on Mac | At `a046076`: 48/48 Python tests passed, including the PostgreSQL test against a real PostgreSQL 16 database; the production build and Playwright 3/3 passed; the checksums of the four frozen candidate files matched. Remote CI has not run. |
| v0.4 acceptance on Mac | At `40a9fe9` (the tagged commit), in a clean worktree: 101/101 Python tests passed, with the PostgreSQL test executed against PostgreSQL 16 (not skipped); the production build and Playwright 3/3 passed; BF26 outputs byte-identical to the baseline. Later commits on PR #14 change only the regression report and docs. Remote CI has not run. |

Real arm-C runs can be recorded to a cassette and replayed offline without an API key; see 「C 组录制与回放」 below. The 20 candidate cases were labelled and frozen. See the [15-case development report](results/c_arm/candidates_dev_summary.md) (dev debugging results) and the [one-time comparison on 5 held-out cases](results/heldout_comparison_2026_11_27.md).

**Two kinds of result, kept apart.** The held-out comparison (3/5 per arm) is the only blind test: 5 frozen cases, each run once. The v0.4 figures (15/23 → 22/23) come from re-scoring cases that were already revealed, after fixing the judge on them. They show that the fixes work on those cases without breaking any others, not how the judge does on unseen offers.

## Design choices and limitations

- **The model selects, code decides.** The LLM only chooses the next document to read, using two tools under a budget of 3 documents and 3 calls. A deterministic judge issues the verdict, and every citation is checked against the documents actually read. Verdicts are therefore auditable and testable, and the model cannot argue its way to a conclusion. The cost is that the judge is written for the wording of the frozen summaries and needs extending for new phrasing. The candidate case set measures how well it generalises.
- **Frozen sources instead of live scraping.** Sources are snapshots registered by a maintainer, with checksums. Every result can be reproduced, and a page edit cannot silently flip a verdict. The cost is that coverage is limited to registered offers, and snapshots go stale after the event.
- **"Insufficient evidence" is a first-class answer.** When the sources do not tie an offer to this store, the system says so instead of guessing.
- **Record and replay for the LLM arm.** Real runs are recorded once and replayed offline, so LLM results can be checked as easily as the offline baselines.
- **No agent framework.** With two tools and a fixed budget, a plain loop is shorter and easier to audit than LangChain or LangGraph.

Current limitations:

- NC20 still gets *insufficient evidence*: its frozen summary keeps the date range as printed (`5/11 – 1/12`), which the judge cannot parse. The summary is frozen, so it stays wrong.
- The v0.4 judge has no blind-test result on new cases yet. The only blind test (5 held-out cases, 3/5 per arm) was run with the earlier judge at `e215b10`.
- Only one model has been tested (DeepSeek via LiteLLM, temperature 0).
- The judge reads paraphrased Chinese summaries, not the original pages.
- The system covers one centre and one event, runs locally only, and has no authentication.

The detailed documentation below is in Chinese.

---

# DFO Homebush 优惠核对与追踪（中文说明）

## v0.3 本地启动

需要 Git 和带 Compose v2 的 Docker。首次构建需要下载基础镜像、Python 和 npm 依赖。在干净目录执行：

```bash
git clone https://github.com/Nlwuu17/dfo-homebush-offer-verifier.git
cd dfo-homebush-offer-verifier
docker compose up -d --build
docker compose ps
```

打开 http://127.0.0.1:3000 提交，历史记录保存在 PostgreSQL 命名卷。前端和 API 仅向本机开放端口；同机使用者共享记录。旧网页在 /compare，首版 CLI 与 results/bf26 沿用各自的入口和文件。

### 一次真实优惠的演示

1. 在首页填 Tommy Hilfiger，核对日填 2026-11-26（表单默认悉尼当日），保持离线规则。输入「全店按原价减 50%」，或粘贴[商场品牌优惠页](https://www.homebush.dfo.com.au/offers/tommy-hilfiger-black-friday-november-2026-tommy-hilfiger)。
2. 点击「核对并保存」，记下浏览器中属于本机的完整结果 URL（路径为 `/records/<UUID>`）。第 1 版引用 TH-BF，条款是全店按原价减 50%，有效期 11/18–12/01。点击官方出处，或刷新并重开同一 URL。
3. 点选商场传单，点击「保存新的核对版本」。传单第 3 页的价格基准是 RRP，档期是 11/18–11/30。11 月 26 日两次结论均为「适用」，新版新增 TH-FLYER 作为参照，判定仍引用品牌优惠页。版本切换可查看各次读取的原文摘要和轨迹。[商场活动入口](https://www.homebush.dfo.com.au/the-big-shopping-week)
4. 在启动服务的同一目录、同一 Compose 项目下运行 `docker compose up -d --force-recreate --wait`。这会重建容器并重新挂载已有的 PostgreSQL 命名卷。打开第 2 步记下的原 URL，在「历史版本」依次选第 1 版和第 2 版。两版均显示「适用」，最终引用均为 `TH-BF`。第 1 版轨迹为 `TH-BF`，第 2 版为 `TH-BF → TH-FLYER`。可展开对照每步的查询理由和官方出处。
5. 返回首页，输入同品牌「只有红色外套减 88%」。预期为「证据不足」，记录注明缺少匹配该具体优惠的官方资料。

### 匹配及资料维护

核对范围固定为悉尼 DFO Homebush。链接不触发联网抓取。后端同时检查品牌，以及指定官方优惠链接或经维护者确认的完整中英文文案别名。只规范化大小写、空白、全半角和链接追踪参数。填写两项时均须匹配。多条活动无法区分时保留证据不足。已支持 v0.2 的三条优惠和本轮 Tommy Hilfiger 优惠。未知活动在维护者登记后可用原记录重新核对。

维护者以 v03/library/tommy.json 为格式添加活动。key 标识具体活动，sources 记录官方原页、摘录、定位、日期、范围和判断所需的价格限定；homebush_included 或 homebush_excluded 必须有原文或商场直接发布的依据。可在 v03/supplements 新增同活动 key、同品牌的资料（旧案例使用 BF26-xx）。补证链接必须匹配该活动的已登记资料。Compose 将这两个目录只读挂载至 API，每次运行重新载入。用户文案仅用于识别活动。该模型依赖维护者核对来源和结构化字段，无法覆盖尚未登记的活动或任意改写。

每次写入同时保存提交或新版结果、实际读取的证据快照和轨迹。重新核对追加版本；并发更新使用版本号与数据库行锁，过期提交返回 409。已有结果页从数据库加载当时的快照，文案、时间、引用及轨迹均可追溯。超过资料预算可能留下证据缺口。

离线模式无需模型。启用 LLM 时先复制 .env.example 至 .env，填写一个可用的 DFO_MODEL 与对应后端密钥，然后执行 `docker compose up -d --build api`。复用 LiteLLM 的 read_evidence / finish、3 份文档、3 次模型调用和超时限制。后端检查所有引用与本次已读 ID，执行门店判定。缺少凭据时页面标明不可用。真实模型的结果见下文的单案例验收和 C 组批量录制。

### Mac 离线全栈验收（2026-11-26）

在提交 `2ce2f06a97a40061b2b635aa06561b94208a53b6` 的干净 checkout 上取得以下结果。

| 验收项 | Mac 实测 |
| --- | --- |
| 生产构建及 Compose 联调 | Next.js 生产构建成功。前端、API 和 PostgreSQL 均通过健康检查。 |
| Python 测试 | 27/27 通过，零跳过，含连接真实 PostgreSQL 的跨 API 生命周期历史记录测试。 |
| Playwright | 3/3 通过。另在 Chromium 中完成上述 Tommy Hilfiger 两版保存与恢复流程。 |
| 容器重建 | 数据库容器 ID 已改变，挂载卷名称保持一致。从原 URL 打开两版后核对了结论、引用、查询理由及官方链接。重建前后的记录快照逐字节相同。 |

原验收脚本完成浏览器检查和快照比对后，在最后打印 `PASS` 时因 Bash 变量名紧邻全角分号触发 `unbound variable`，最终以非零状态退出。修正本机辅助脚本后，单独验证了打印语句，并再次比对了两份快照。本轮远程 CI 未重跑；这一轮离线验收的真实 LiteLLM 调用为 0 次。[Draft PR #2 的 Mac 验收记录与实际命令](https://github.com/Nlwuu17/dfo-offer-verification-agent/pull/2#issuecomment-7183202333)

### 合并后 Mac 验收（`a046076`，2026-11-26）

PR #5–#8 全部合并后，在 Mac 上对 `main` 的 `a046076` 做了一次完整验收。远程 CI 因 Actions 额度问题未运行，以这次验收作为合并后的测试记录。

| 验收项 | 实测 |
| --- | --- |
| 冻结文件 | `data/candidates_2026_11_26/SHA256SUMS` 中的资料、案例、划分和标签 4 份文件，SHA-256 均校验通过。 |
| Python 测试 | `python -m unittest discover -s tests -v`：48/48 通过，无跳过。`test_v03` 的 6 个用例全部执行；其中 `test_saved_history_across_api_lifespans` 连接真实的 PostgreSQL 16（测试容器使用 5433 端口，因为本机已有 PostgreSQL 占用 5432），跨两次 API 启动保存并读回历史记录。 |
| 前端 | Node 22.23.5；`npm run build` 通过；`npm run test:browser`：Playwright 3/3 通过。 |

本轮未调用模型，也未运行候选集评测。

### LiteLLM 单案例验收（2026-11-26）

这次运行在旧停止规则（首次判出结论即停）下进行。对 BF26-02（ASICS）提交 1 次 C 组运行请求。配置的模型标识为 `deepseek/deepseek-chat`，供应商响应记录的模型为 `deepseek-flash`；两者不一致，此处如实记录，未进一步核实对应关系。验收所用提交未记录。

| 验收项 | 实测 |
| --- | --- |
| 查询轨迹 | 模型发起 2 次 `read_evidence`，后端依次成功读取 E03 → E04，随后因「证据充分」停止。 |
| 判定与引用 | 「不适用」，引用 E03、E04，与人工标签一致。 |
| 资源消耗 | 文档查询 2/3，模型调用 2 次，累计模型耗时 2190 ms。页面记录费用约 US$0.000160，未与供应商账单核对。 |

ASICS 一题的三组对照：

| 组 | 查询路径 | 读取份数 | 判定 | 引用 |
| --- | --- | ---: | --- | --- |
| A 固定组 | E03 → E07 → E04 | 3 | 不适用 | E03、E04 |
| B 规则组 | E03 → E04 | 2 | 不适用 | E03、E04 |
| C LLM 组 | E03 → E04 | 2 | 不适用 | E03、E04 |

在这一案例中，固定组读取 3 份资料，规则组和 LLM 组各读取 2 份，三组结论一致。这个结论仅限于这一次单案例实测：没有重复运行，也未覆盖 BF26-01 和 BF26-03，不能据此评估 C 组的准确率、稳定性或成本。

### C 组批量录制（2026-11-26）

以下录制和对比都在旧停止规则（首次判出结论即停）下完成，A、B 组路径也是旧规则下的结果。在提交 `5063b11` 的干净工作区上，用 `deepseek/deepseek-chat` 对 3 个 BF26 案例各录制 5 次，共 15 次运行。供应商返回的模型均为 `deepseek-flash`。录制文件为 [results/c_arm/cassette.jsonl](results/c_arm/cassette.jsonl)，汇总表为 [results/c_arm/summary.md](results/c_arm/summary.md)。汇总表由 `python -m v02.cassette report` 生成；15 次运行均可离线回放，且回放一致。

| 案例 | 人工标签 | C 组判定 | C 组路径（5 次） | A 组路径 | B 组路径 |
| --- | --- | --- | --- | --- | --- |
| BF26-01 Oroton | 适用 | 5/5 适用 | E02 → E07 | E02 → E07 | E02 → E07 |
| BF26-02 ASICS | 不适用 | 5/5 不适用 | E03 → E04 | E03 → E07 → E04 | E03 → E04 |
| BF26-03 Ralph Lauren | 证据不足 | 5/5 证据不足 | E05 → E06 → E07 | E05 → E07 → E06 | E05 → E07 → E06 |

- 准确率 15/15。每个案例 5 次运行走的路径完全相同。
- 平均读取 2.33 份，与 B 组相同，比 A 组的 2.67 份少。BF26-03 中 C 组读取的 3 份资料与 A、B 组相同，只是顺序不同，三组都因预算用尽停止。
- 平均耗时 2827 ms；15 次运行的费用合计约 US$0.0061。该费用是 LiteLLM 报告值，未与账单核对。上文单案例验收中，页面记录的 2 次调用费用约 US$0.000160；本轮同为 2 次调用的 ASICS 运行，每次约 US$0.00031。两者的差异未核实。

局限：只测了一个模型，温度为 0，样本是开发期间可见的 3 个案例，C 组的提示词也是在这些案例已知的情况下写的。这个结果说明在这 3 题上，C 组与规则组一样准确、一样省资料，并且跑多次结果稳定；它不能说明 C 组在新案例上的表现。

### C 组候选开发集录制（2026-11-26，开发集调试结果）

在固定配置 `e215b10`（规则 A、规则 F 的边界、三组共用的补查停止规则）的干净 worktree 上，用 `deepseek/deepseek-chat` 对 15 道开发题各录制 5 次，共 75 次运行。供应商返回的模型均为 `deepseek-flash`；75 次运行的 `dirty` 都是 false，录制中没有留出案例。录制文件为 [results/c_arm/candidates_dev.jsonl](results/c_arm/candidates_dev.jsonl)，汇总表为 [results/c_arm/candidates_dev_summary.md](results/c_arm/candidates_dev_summary.md)。75 次运行离线回放全部一致，用 `report` 重新生成的汇总表与提交的版本逐字节相同。

| 指标 | 结果 |
| --- | --- |
| 判定正确 | 9/15 题；按单次运行计为 45/75 |
| 重复稳定性 | 15/15 题的 5 次运行，读取路径和最终标签都相同 |
| 读取与模型调用 | 各 155 次，平均每次运行 2.07 次 |
| 平均耗时 | 2181 ms |
| 费用 | 合计约 US$0.0150（LiteLLM 报告值，未与账单核对） |

6 道错题是 NC04、NC06、NC07、NC13、NC19、NC20，人工标签都是「适用」，C 组都判「证据不足」。这 6 题每次都读完了目录里的全部资料。在同一配置下，A、B 两组在开发集上错的也正是这 6 题，三组都是 9/15。可见错误来自三组共用的判定器，与选资料无关。

这些都是**开发集调试结果**：开发集在改判定器时用过，A、B 组在这 15 题上的判定也曾在测试失败时暴露过一次，所以这些数字不代表泛化表现。泛化表现以 5 道留出题的一次性评测为准。
### 5 道冻结留出案例的一次性三组对照（2026-11-27）

三组都固定在 `e215b10`，每组每题只运行一次。三组都答对 3/5，逐题判定完全相同，没有技术失败。C 组读了 12 份资料，A、B 组各 11 份。两道错题（NC03 Sharetea、NC05 Bath & Body Works）上，三组都读完了全部资料，最终都判「证据不足」。原因是共用判定器只能解析百分比折扣，无法识别「买一送一」。在这 5 题上，三组的逐题判定相同，都答对 3/5。选资料的差异只体现在路径和成本上：C 组在 Sharetea 调换了读取顺序，在 Portmans 多读了一份门店页；两处都没有改变最终判定。完整报告见 [results/heldout_comparison_2026_11_27.md](results/heldout_comparison_2026_11_27.md)。

留出集已经揭晓，之后对判定器的改进不能再用这 5 题来证明有效。

### C 组录制与回放

真实模型的运行无法原样重跑，所以 C 组改为录制后回放。录制时，每次运行在 JSONL 文件里追加一行，内容包括：
- 每次模型请求的 SHA-256 指纹
- 模型返回的工具调用、token 数、费用
- 配置的模型名和供应商返回的模型名
- 代码提交 SHA 及工作区是否有未提交改动
- agent 返回的完整结果

超时和上游错误也会录下来，但只记录错误类型，不保存供应商的错误原文。录制文件不含 API key。

回放不调用模型：它把录下的响应依次送回未改动的 agent 循环，逐次校验请求指纹，再比对重建出的结果与录制结果。墙钟耗时无法复现，所以耗时字段沿用录制值，其余内容必须逐字节一致。资料、提示词或 agent 逻辑一旦改变，回放会报告不一致，并以非零状态退出。

**权威回放以录制提交为准。** 每条记录都存了录制时的 `source.commit`。换了代码，判定、停止时机和后续请求都可能改变，所以在其他提交上回放，结果不能用来核验录制本身。当前提交与录制提交不同时，`replay` 会先列出两者，并给出在录制提交上回放的命令，例如：

```bash
git worktree add --detach /tmp/replay-e215b10 <录制提交> && (cd /tmp/replay-e215b10 && python -m v02.cassette replay <录制文件的绝对路径>)
```

三份已有录制在各自的录制提交上回放全部一致：`results/c_arm/cassette.jsonl`（`5063b11`）15/15，`candidates_dev.jsonl`（`e215b10`）75/75，`candidates_heldout.jsonl`（`e215b10`）5/5。

`python -m v02.cassette` 还提供固定已读路径重判（`v02.cassette.rejudge`）：保留录制里的资料和读取顺序，只换用当前判定器重判，不调用模型。它只能说明「给同样的证据，判定有没有改善」；当前判定器真正运行时，C 组可能提前停止，也可能继续查询。

```bash
# 录制：需要 LiteLLM、DFO_MODEL 和对应密钥
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r v02/model-requirements.txt
set -a; source .env; set +a
python -m v02.cassette record --out results/c_arm/cassette.jsonl --repeats 5

# 回放：只需 pydantic，不需要密钥
python -m v02.cassette replay results/c_arm/cassette.jsonl

# 按人工标签生成汇总表
python -m v02.cassette report results/c_arm/cassette.jsonl --out results/c_arm/summary.md

# 候选案例：默认只录开发集；留出集需显式指定 --split heldout
python -m v02.cassette record --data data/candidates_2026_11_26 \
  --out results/c_arm/candidates_dev.jsonl --repeats 5
python -m v02.cassette report results/c_arm/candidates_dev.jsonl --labels labels_todo.json
```

每次运行都会在录制文件里记下所属的数据集和划分，回放时会自动找到对应的输入。一份录制文件可以包含多个数据集，但汇总时一次只能汇总一个。未标注的案例只显示读取路径，不计入正确数。

`--case BF26-02` 可以只录指定案例，可重复传入。同一文件可多次追加，`run_index` 会继续编号。

### v0.4 判定器（已冻结，标签 `v0.4-judge`，`40a9fe9`）

v0.4 把每条优惠连同它的条件一起识别，不再只认百分比。

- **形式**：百分比、买一送一、单件价格（`单价$12`）、整组价格（`3杯共$20`）。金额门槛（如 `$3,000 以下`）当作条件，不当作价格。
- **范围**：全店、指定或精选、商品类别；「任一饮品」表示不限品类。价格前出现词表外的限定词（如「床品」）时，按保守规则保留这项限制：用户描述须原文写出这个词，否则判「证据不足」。日期、「标题为」「另外」、品牌名等说明文字不算限制。
- **条件**：会员资格（按整句识别）、金额门槛和件数要求（按所在分句识别，连同具体数值比对）。「额外」与「最高」一样，属于优惠本身，须一致。
- **Outlet**：「Outlet 门店 / Outlet 全店」是门店类型，需要资料限定 Outlet；「Outlet 商品」是商品范围，按类别比对。

用户描述与资料要在形式、数值和「最高」与否上相同，才算同一条优惠。内容比对沿用规则 B：资料明确覆盖的更窄描述成立；用户描述漏掉资料里的范围限制或条件时，判「证据不足」。即使另一份资料没提这项限制，结论也不变。同一条优惠的有效期仍按规则 A、E、F 另行判断。

摘要按 [data/SUMMARY_TEMPLATE.md](data/SUMMARY_TEMPLATE.md)（已定稿）撰写。模板和判定器放在同一提交中，通过回归审阅、数据库和浏览器验收后，打上 `v0.4-judge` 标签冻结。

回归报告见 [results/regression_v0.4/](results/regression_v0.4/)：在已揭晓的 23 题（BF26 3 题、候选集 20 题）上，A、B 两组和 C 组固定路径重判都从 15/23 提高到 22/23，7 题错→对，没有对→错，NC20 仍然判错。这 23 题都已揭晓，只用于回归，不代表对未见优惠的表现。

两类结果请分开看，`3/5` 和 `22/23` 不是同一场测试：

| 评测 | 结论 |
| --- | --- |
| `e215b10` 的一次性盲测 | 在 5 道冻结留出题上，三组各答对 **3/5**，逐题判定一致。A、B 各读取 11 份资料，C 读取 12 份。 |
| v0.4 的已知案例回归 | 在 23 道已揭晓案例上，同一批题的基线为 **15/23**，当前为 **22/23**。7 题由错变对，0 题由对变错。C 组使用原录制路径重判，新增模型调用为 0。 |

**v0.4 验收（`40a9fe9`，Mac，干净 worktree）**：Python 测试 101/101 通过，其中 PostgreSQL 用例连接 PostgreSQL 16 实际执行，没有跳过；生产构建成功，Playwright 3/3 通过；BF26 输出与基线逐字节一致。PR #14 在此之后的提交只改回归报告和文档。远程 CI 因 Actions 额度问题未运行。

### 设计取舍与局限

| 选择 | 为什么这样做 | 代价 |
| --- | --- | --- |
| 模型只选资料，判定交给代码 | 结论可审计、可测试；每条引用都必须是本次实际读过的资料，模型无法靠措辞得出结论 | 判定器按冻结摘要的表述编写，遇到新说法需要扩展；候选案例集用来检验它的泛化能力 |
| 冻结资料，不实时抓取 | 每个结果都能复现，网页改版不会悄悄改变结论 | 只覆盖维护者登记过的优惠；档期结束后快照会过期 |
| 「证据不足」是正式答案 | 资料不能把优惠落实到本店时，明确说不知道，而不是猜 | 用户有时得不到明确的是或否 |
| 资料预算 3 份、模型调用 3 次 | 成本和延迟可控，策略之间的比较有共同前提 | 需要更多资料才能判定的案例只能给出「证据不足」 |
| LLM 组录制后回放 | 真实模型的结果和离线基线一样可以复查 | 回放只能验证已录的运行；换模型或改提示词需要重新录制 |
| 不用 Agent 框架 | 只有两个工具和固定预算，手写循环更短，也更容易审计 | 以后如果要增加复杂的多步工作流，需要自己扩展 |

当前局限：
- NC20 的冻结摘要保留了未统一的日期格式（`5/11 – 1/12`），判定器无法解析，当前仍判「证据不足」。摘要已冻结，不为这一题改写。
- v0.4 尚无新题盲测结果。唯一的盲测是 `e215b10` 上 5 道留出题的一次性对照（三组各 3/5），用的是旧判定器。
- 只测试了一个模型：经 LiteLLM 调用的 DeepSeek，温度为 0。
- 判定器读取的是改写过的中文摘要，不是原始页面。
- 只覆盖一个商场的一次活动；只在本地运行，没有用户登录。

### 运行测试

CI 使用 PostgreSQL 16、离线模式及 Chromium。单独验证数据库跨 API 生命周期持久化与并发版本检查时，DATABASE_URL 必须指向可写的测试数据库。以下命令从仓库根目录运行（Python 3.12、Node 22）：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r v03/requirements.txt
export DATABASE_URL=postgresql://dfo:test@127.0.0.1:5432/dfo
python -m unittest discover -s tests -v
shasum -a 256 -c data/real_cases_2026_11_26/SHA256SUMS
out=$(mktemp -d)
python bf26.py eval --out "$out"
diff -ru results/bf26 "$out"
cd web && npm install && npm run build
npx playwright install chromium
npm run test:browser
```

Playwright 自行启动 API 和生产前端，运行前释放 8000/3000 端口。真实优惠补证测试使用两份公开资料。额外的冲突测试仅在临时测试目录放入显式标记的合成排除条款，验证「适用 → 证据不足」，不向真实资料库写入测试结论。


## v0.1 冻结基线


在悉尼当地 2026-11-26，一条指定的黑五优惠能否用于 DFO Homebush 实体店？本轮 CLI 为 `bf26.py`，使用 3 个冻结的真实案例、7 份本地官方资料和「适用／不适用／证据不足」三个标签。B 组采用**规则策略**（C 组才是由模型选资料的 Agent）。两组均离线执行，实际模型调用为零。

[逐案例对照表](results/bf26/comparison.md) · [查询轨迹 JSONL](results/bf26/traces.jsonl) · [冻结输入](data/real_cases_2026_11_26/)

## 在 macOS 复现

在项目根目录使用 Python 3.10 或更新版本，仅需标准库。

```bash
python3 bf26.py check BF26-02 --arm B
shasum -a 256 -c data/real_cases_2026_11_26/SHA256SUMS
python3 -m unittest discover -s tests -v
repeat_dir=$(mktemp -d)
python3 bf26.py eval --out "$repeat_dir"
diff -ru results/bf26 "$repeat_dir"
```

`check` 输出单题的理由、引用、实际查询次数和逐步判断。`eval` 先跑完 6 次独立查询，再打开 gold_labels.json 评分。Markdown 表记录人工标签、预测和引用。JSONL 每行保存一题一组的完整轨迹，末步记录停止原因。复跑时两个输出均可逐字节比较。

## 实验设计

两组唯一的实验变量是下一份资料的选择策略。输入来自同一份 cases.json，目录仅暴露 ID、标题和来源类型。公共读取工具按本题目录检查 ID，只能逐份读取，每份最多一次，每组每题上限 **3 份**。同一份传单包含多个品牌，读一次算一次。判定器仅处理已读的资料，并按品牌定位传单段落。

| 组 | 选择下一份资料的规则 |
|---|---|
| A 固定组 | 商场品牌优惠页 → 品牌活动条款 → 商场活动传单 → 品牌门店目录 → 商场门店页 → 商场活动页。首批 3 个案例不含商场门店页。同类保持原目录顺序。优先查看能直接说明门店优惠或约束门店范围的资料。 |
| B 规则策略 | 起步及无优先候选时沿用 A 的顺序。读到排除某类门店的条款后优先查门店目录；缺少本店参与依据或具体优惠条件时优先查商场传单。 |

三组共用同一套停止规则（A、B 在 `bf26.run`，C 在 `v02.agent.llm`）。每题最多读 3 份资料，每读一份都由共用判定器按全部已读资料重新判断：

- 首次判出「适用」或「不适用」后，如果预算还有余量，目录里也还有可能载有同一优惠的资料，就再读一份（补查），最多一次。可能载有同一优惠，只依据目录元数据判断：商场品牌优惠页或品牌活动条款，标题须含品牌名；商场活动传单都算。门店页、门店目录和活动页都不算。补查时 A、B 仍按各自的选文规则选资料，C 只能从这些候选中选。
- 补查后由判定器重新判断。两份档期都覆盖核对日，就继续核对门店与优惠内容；一份覆盖、另一份排除，就按规则 F 判「证据不足」，之后按原有流程继续查询，直到读完或预算用尽。
- 轨迹记录实际停止原因：「补查完成」「没有相关候选」「预算用尽」（C 组为「文档预算用尽」），未得出结论的为「目录已读完」或「预算用尽」。补查只能说明已读资料之间是否冲突。

2026-11-26 之前的运行（包括 C 组的 BF26 录制）用的是旧规则：首次判出结论即停，停止原因记为「证据充分」。录制文件中没有 `stop_policy` 字段的条目，回放时按旧规则执行。

共用判定器针对冻结的中文摘要识别品牌、有效期、折扣数值及对应条件，包括会员身份、价格基准、额外或最高折扣。商场品牌优惠页可以与同档期、同折扣的本店传单互补；品牌条款排除特定店型时，需要门店目录确认该分店属于该类别。只有参与门店泛称、同品牌其他优惠或门店身份时，保留「证据不足」。无明确结束日的限时活动仅按核对日快照解释。

## 评分及实测结果

按每题最终标签与 gold_labels.json 精确匹配计分。平均查询次数为该组读取总数除以 3。评分前验证案例 ID 唯一、标注与案例一一对应、目录元数据与 sources.json 一致、参考证据属于该题目录。每一步也校验引用来自该次已经读取的资料。不同证据组合允许得到同一结论；未计算引用正确率。

- **Oroton**。两组均读 E02、E07 后判「适用」。E02 说明原价和折后价的计算基准，E07 补充额外 10% 的会员资格。首跑发现共用解析器遗漏逗号后的除外条件，导致两组均漏判。修复并增加回归测试后复跑，选文策略及冻结数据沿用首跑版本。
- **ASICS**。两组先读 E03，确认会员减 30% 的条款排除 Factory Outlets。差异发生在第 2 步。A 读 E07，传单写的是本店另一条减 50% 的优惠，第 3 步才读 E04 核实店型，此时预算用尽。B 根据缺失信息直接读 E04，判出「不适用」后补查 E07，未发现冲突。两组都引用 E03、E04 判「不适用」。
- **Ralph Lauren**。两组都读 E05、E07、E06。E05 仅称参加活动的门店可享指定商品减 30%；本店传单写最高减 70%，目录只确认分店身份。第 3 次查询后预算用尽，两组均判「证据不足」。

最终两组均正确 **3/3**。按共用停止规则，A、B 两组各读 8 份，平均 2.67 份。旧规则下 B 组在 ASICS 一题判出结论后即停，共读 7 份，平均 2.33 份；现在多出的 1 份就是补查。判定规则针对现有资料的表述，样本是开发期间可见的三个固定案例，尚无独立留出集。v0.1 基线本身不含模型调用；C 组的真实模型数据见上文的单案例验收和 C 组批量录制。

## 测试范围

完整套件含 6 项本轮真实案例检查和 8 项早期离线协议检查。早期 CLI、测试夹具和冻结配置随测试保留。首版结果表仅统计上面的三个 BF26 案例。策略函数只收到未读目录、组别和已读证据归纳出的缺项；参考标签由评分入口读取。这项隔离由代码调用边界和测试验证，运行环境没有操作系统级文件隔离。
