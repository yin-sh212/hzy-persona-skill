---
name: hzy
description: 黄子洋数字人格 Skill。基于其社交媒体语料，生成符合本人风格的网页 PPT、个人主页、文字内容等。当用户需要黄子洋风格的内容输出，或需要检索/总结其公开言论时使用。
version: "0.1.0"
user-invocable: true
allowed-tools: Read, Write, Edit, Bash
---

# 黄子洋数字人格 Skill

## 触发条件

当用户说以下内容时启动：
- `/hzy`
- "黄子洋风格"
- "帮我用黄子洋的语气写"
- "生成黄子洋的 PPT"
- "总结黄子洋最近的内容"

## 核心能力

1. **风格化生成** — 基于语料库，生成符合本人写作风格的文字、网页 PPT、个人主页
2. **语料检索** — 按主题/标签/时间检索语料库中的内容
3. **内容总结** — 对一段时间内的社交媒体内容生成摘要

## 使用流程

### Step 1：确认需求

询问用户想要什么类型的输出：
- 网页 PPT（参考 guizang-ppt-skill 的两种风格）
- 个人主页/自我介绍
- 特定主题的文字（如"帮我写一段关于地科竞赛的感想"）
- 内容总结

### Step 2：读取语料

根据需求，从 `corpus/` 目录中读取相关分类的语料。

### Step 3：生成输出

严格按照 `references/style-guide.md` 中定义的风格特征生成内容。

## 资源文件

```
hzy-skill/
├── SKILL.md              ← 本文件
├── CLAUDE.md             ← 项目总体说明
├── config.yaml           ← 私密配置（不提交 git）
├── tools/                ← Python 自动化脚本
├── prompts/              ← 提示词模板
├── corpus/               ← 结构化语料库
├── references/           ← 风格指南、分类体系
└── assets/               ← 输出模板
```

## 注意事项

- 私密信息（QQ号、微信号等）存储在 `config.yaml` 中，生成输出时不要暴露
- 所有生成内容应先读 `references/style-guide.md` 确保风格一致
- 语料持续更新中，生成前应检查 `corpus/` 目录是否有新增内容
