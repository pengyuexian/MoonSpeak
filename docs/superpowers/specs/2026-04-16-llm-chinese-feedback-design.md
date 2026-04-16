# LLM Chinese Feedback Design

## Goal
将评测产物中的最终反馈改为由 LLM 直接生成中文指导性文案，并收敛为单一 `*.feedback.md` 文件；server 页面只读取这个单文件，并在反馈区域底部显示一条 AI 免责声明。

## Current State
当前 pipeline 同时生成 `*.feedback.md` 和 `*.feedback.cn.md`。页面只读取中文文件。反馈正文实际没有调用 LLM，而是用本地 fallback 模板生成，文案稳定但机械。代码中已经存在英文反馈生成和中文翻译的 LLM 辅助函数，但主流程未启用。

## Requirements
1. 只保留一个反馈文件：`*.feedback.md`。
2. 反馈文件内容整体仍使用当前 markdown 结构：`匹配 Level / 匹配 Unit / 匹配 Track / 标准内容 / 评分 / 重点问题词 / 反馈`。
3. `反馈` 段落改为由 LLM 直接生成中文，不再走“英文反馈 -> 中文翻译”链路。
4. LLM 输出必须保留引号中的英文问题词原文，例如 `"it"` 不能被翻成 `"它"`。
5. 若 LLM 输出缺少关键问题词、过短、明显矛盾、或把英文词翻掉，则回退到现有中文 fallback 模板。
6. server 页面改为读取唯一的 `feedback.md`。
7. 页面 `反馈` 区底部追加一条小灰字免责声明，说明 AI 内容可能不完全准确。
8. `run_assessment` 返回的 report path 改为 `*.feedback.md`。

## Recommended Approach
### Option A: Single Chinese markdown report with LLM-first feedback (recommended)
保留现有 markdown report 结构，但只输出一个中文报告文件。LLM 只负责生成 `反馈` 段文本，其余结构化部分仍由代码确定。失败时回退到中文模板。

优点：
- 产物最简洁，完全符合目标
- 风险可控，LLM 只负责自然语言段落，不碰结构化事实
- 页面和脚本改动范围明确

缺点：
- 需要迁移 server/data_loader 和 run_assessment 对路径的依赖
- 需要增加 LLM 输出约束和校验逻辑

### Option B: Keep dual files internally, read only one in server
兼容成本更低，但违背“只保留一个 feedback 文件”的要求，不采用。

### Option C: Put feedback into JSON sidecar
结构更清晰，但会扩大产物类型和读取逻辑，不必要。

## Architecture
1. `pipeline.py` 继续负责匹配、standard text、Azure scoring、problem words 抽取。
2. 新的中文反馈函数直接接受结构化评分事实和问题词，向 LLM 请求中文反馈。
3. 输出校验在 pipeline 内完成：
   - 完整性：文本长度、句末标点
   - 问题词覆盖：被选中的英文问题词必须出现
   - 词保真：被引用的英文词不得被翻译或丢失
   - 语义一致性：不能把问题词描述成“很清楚/很好”
4. 若校验失败，则用现有中文 fallback 文案。
5. 最终中文 markdown 报告写入 `*.feedback.md`，不再生成 `*.feedback.cn.md`。
6. `server/data_loader.py` 只解析单个 markdown 报告文件。
7. `server/render.py` 在 `反馈` 区底部增加免责声明行。

## Data Flow
1. `assess_audio()` 生成 `standard.txt` 与 `azure.json`
2. `extract_problem_words(scores)` 提取重点问题词
3. `llm_generate_feedback_cn(...)` 生成中文反馈
4. `render_feedback_report_cn(...)` 写入唯一的 `feedback.md`
5. `load_speech_review_page_data()` 读取 `feedback.md`
6. `render_speech_review_page()` 展示反馈正文与免责声明

## LLM Prompt Requirements
- 角色：适合孩子和家长的英语朗读老师
- 语言：中文
- 目标：鼓励 + 具体指导
- 内容：
  - 先肯定孩子的坚持或节奏
  - 再指出 2-4 个最值得练习的问题词或问题类型
  - 给出具体练习建议，例如“慢一点”“把结尾音读清楚”“不要漏掉小词”
- 约束：
  - 如果问题词以英文列出，必须原样保留英文
  - 不得把这些英文词翻译成中文
  - 不得编造未在输入中出现的词
  - 不得说问题词读得“很好”或“很清楚”
  - 输出仅为反馈正文，不加标题或列表

## Disclaimer Copy
推荐文案：
`AI 生成的反馈可能不完全准确，请结合录音和实际朗读情况一起判断。`

理由：
- 简洁
- 不像法律条款
- 接近常见 AI 产品提示方式

## Files To Modify
- Modify: `src/moonspeak/pipeline.py`
- Modify: `server/data_loader.py`
- Modify: `server/render.py`
- Modify: `tests/test_speech_server.py`
- Modify: `tests/test_run_assessment.py`
- Modify: `tests/test_pipeline_helpers.py`
- Possibly update generated skill docs only if they mention `feedback.cn.md`

## Testing Strategy
1. Pipeline unit tests:
   - LLM 中文反馈 prompt/校验逻辑
   - 回退逻辑
   - 只输出 `feedback.md`
2. Run-assessment tests:
   - `report_path` 指向 `feedback.md`
3. Server loader/render tests:
   - 只读单文件 markdown
   - 页面展示反馈与免责声明
4. Regression:
   - 重点问题词中的英文词在中文反馈里保持原文

## Risks
1. LLM 返回空泛表扬，未覆盖问题词
缓解：严格覆盖校验，失败即 fallback。
2. LLM 将英文问题词翻译成中文
缓解：在 prompt 和 post-check 双重约束。
3. 旧产物仍存在 `feedback.cn.md`
缓解：新逻辑不再依赖它；页面路径统一切到 `feedback.md`。
4. 页面解析受 markdown section 名称变化影响
缓解：保留现有中文 section 名称，不改结构。
