# 天眼 · 亚马逊选品雷达 Skill

<div align="center">

# Tianyan · Amazon Product Radar

**一款判断亚马逊产品/品类"到底能不能做"的 AI Agent Skill**

**适配 Claude Code / Codex / OpenCode 等主流 AI Coding Agent**

**想了解更多最新 AI 行业动态,AI × 跨境电商实战方法,人与 AI 如何协作共生的思考,请关注公众号:【新西楼.AI】**

![新西楼.AI](https://github.com/user-attachments/assets/d8f068d9-c4f8-46c7-914c-fbcab5d52f2a)

[![Agent Skill](https://img.shields.io/badge/Agent-Skill-7C3AED.svg)]()
[![Claude Code](https://img.shields.io/badge/Claude_Code-ready-blue.svg)]()
[![Codex](https://img.shields.io/badge/Codex-ready-green.svg)]()

**个性化判断 | 红线提醒 | 利润测算 | 合规侵权调研 | 本地零配置**

**Created By buluslan@新西楼.AI**

</div>

---

## 项目简介

天眼是一款 **AI Agent Skill**,判断一个亚马逊产品 / 品类**值不值得做、适不适合你**。

它不只是一份「市场分析报告」——会结合**你的经验、资金、品类渊源**做个性化判断:**同一个品,对新手可能是坑,对老手可能是机会**,结论因人而异。

### 它解决什么问题

- ❌ 选品靠拍脑袋,看不出藏在底下的红线(侵权 / 合规认证 / 退货雷区)
- ❌ 利润算不准,选品阶段根本拿不出出厂价、算不清广告后净利
- ❌ 网上的「选品分析」千篇一律,没考虑你自己的情况——新手做亏的品,老手可能做赚

### 核心能力

| 能力 | 说明 |
|------|------|
| **市场结构诊断** | 销量集中度 / 评论壁垒 / 价格真空带 / 品牌集中度 / 新品窗口 / 自营占比 |
| **红线排查** | 侵权(专利 / 商标)、合规认证(FCC / UL / CE / Prop65 / FDA / EPA)、退货根因 |
| **利润测算** | 3 档定价 × 出厂价 / 头程 / 配送 / CPC / CVR / 退货率,自动基于市场数据估算 |
| **个性化判断** | 按你的经验(新手 / 进阶 / 成熟)+ 资金 + 品类关系调整结论 |
| **可重跑** | 有真实出厂价 / 转化率 / 退货率?填进去覆盖估算,结论更准 |

---

## 它怎么判断

四路并发,全部在系统跑完(本地零配置,不需要数据平台账号):

```
【你本地】你说:用天眼分析蓝牙音响美国站
              ↓
【你本地】问你:经验 / 资金 / 品类关系(+ 选填实测值)
              ↓
【后台服务器】同时分析(约 3 分钟,你不用管)
   ├─ ① 市场结构:Top100 销量 / 评论 / 价格 / 品牌 / 上架分布
   ├─ ② 合规侵权:合规认证(FCC/UL/CE 等)+ 专利 / 商标排查
   ├─ ③ 退货根因:差评根因 + 政策季节性
   └─ ④ 利润测算:1688 货源均价 + CVR/退货率典型区间
              ↓
【你本地】拿到完整判断报告,直接呈现给你(+ 存一份到本地)
```

---

## 报告长什么样

每份报告包含:

- **判断结论**:🔴 不建议 / 🟡 谨慎 / 🟢 可做 + 数据可信度
- **红线提醒**:踩了哪条线(如「扣广告净利率全档踩红线」)
- **分项评级**:市场结构 / 竞争格局 / 利润空间 / 合规风险 各维度
- **利润测算**:3 档(保守 / 中性 / 乐观),标注哪些是估算、哪些是实测
- **资金账**:启动资金 / 周转周期
- **风险与凭证**:数据来源 + 哪些结论扎实、哪些是估算
- **重跑入口**:本次报告 ID(凭 ID 可复查当时的报告 + 运行日志)

---

## 安装

> 把本仓库链接发给你的 AI Coding Agent(Claude Code / Codex / OpenCode 等),让它帮你装。下面步骤是给 **Agent** 看的,你不用自己敲。

### 你需要先联系我们获取
- **API key**(以 `sk_t_` 开头)
- **服务地址**(以 `http://` 开头)

### 步骤(Agent 执行)

**1. 下载技能到你 Agent 的技能目录**(目录名必须是 `bulus-amazon-product-radar`,否则识别不到):

```bash
# Claude Code
git clone https://github.com/buluslan/bulus-amazon-product-radar.git ~/.claude/skills/bulus-amazon-product-radar
# Codex
git clone https://github.com/buluslan/bulus-amazon-product-radar.git ~/.codex/skills/bulus-amazon-product-radar
# 其他 Agent(OpenCode 等):clone 到你 Agent 对应的 skills 目录,目录名保持 bulus-amazon-product-radar
```

**2. 写入 key 和服务地址**:

```bash
mkdir -p ~/.radar
cat > ~/.radar/config.json << EOF
{
  "api_key": "<你的 API key>",
  "cloud_endpoint": "<我们给你的服务地址>"
}
EOF
chmod 600 ~/.radar/config.json
```

**3. 重启 Agent**(或开新会话),技能才会加载。

---

## 使用

说:

> 用天眼分析蓝牙音响美国站

它会问你品类 / 经验 / 资金,几分钟后给一份判断报告。后续想更准,补真实转化率 / 退货率 / 出厂价,说一句改哪项,重算。

---

## 常见问题

- **连不上 / 报错** → 检查 key 和服务地址对不对(在 `~/.radar/config.json`)
- **key 无效或次数用完** → 联系我们
- **找不到这个技能** → 确认装到了你 Agent 的技能目录(如 `~/.claude/skills/bulus-amazon-product-radar` 或 `~/.codex/skills/bulus-amazon-product-radar`),目录名必须是 `bulus-amazon-product-radar`,并重启 Agent

---

## 联系

- 公众号:【新西楼.AI】
- 微信:bulus_lan
- 邮箱:buluu599@163.com

**Created By buluslan@新西楼.AI**
