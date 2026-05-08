# **Dev Log — 修复前端中文标点换行渲染问题**

日期: 2025-01-15
 标签: bug-fix, frontend, css, typography, cjk-rendering

------

# **一、概述**

修复后端返回到前端后的中文文本在页面渲染时，中文标点符号出现在行首的问题。

问题根本原因是 `.message-text` 使用了：

```css
word-break: break-word;
```

该属性会破坏中文（CJK）文本的正常换行规则，导致浏览器允许在中文字符与标点之间任意断行，从而出现：

```text
这是第一行
。第二行
```

这种违反中文排版规范的情况。

本次修复方案：

- 将 `word-break` 改为 `normal`
- 添加 `line-break: strict`
- 使用 `overflow-wrap: break-word` 替代原有非标准写法

从而启用浏览器标准的中日韩（CJK）排版规则。

------

# **二、根因分析（Root Cause Analysis）**

原始 CSS：

```css
.message-text {
    word-break: break-word;
}
```

问题原因：

- `word-break: break-word` 属于历史遗留的非标准行为（最早来自 WebKit）
- 浏览器会允许任意位置断行
- 对中文来说，会允许：

```text
汉字 | 。
```

之间断开。

结果就是：

- `。`
- `，`
- `、`
- `》`
- `」`
- `）`

等标点可能被挤到下一行行首。

这违反了中文排版中的：

```text
标点避头尾规则
```

即：

- 标点不能出现在行首
- 开始括号不能出现在行尾

------

# **三、修改文件**

| **文件**               | **操作** | **说明**             |
| ---------------------- | -------- | -------------------- |
| `frontend/src/App.css` | 修改     | 修复中文文本换行规则 |

------

# **四、修改内容**

## **修复前**

```css
.message-text {
    font-size: 15px;
    line-height: 1.7;
    color: #e5e5e5;
    white-space: pre-wrap;
    word-break: break-word;
    padding: 8px 0;
}
```

问题：

- 非标准断行
- 中文标点可能出现在行首
- 浏览器跳过 CJK 排版规则

------

## **修复后**

```css
.message-text {
    font-size: 15px;
    line-height: 1.7;
    color: #e5e5e5;
    white-space: pre-wrap;

    overflow-wrap: break-word;
    word-break: normal;
    line-break: strict;

    padding: 8px 0;
}
```

------

# **五、CSS 属性说明**

| **属性**        | **值**       | **作用**             |
| --------------- | ------------ | -------------------- |
| `white-space`   | `pre-wrap`   | 保留 LLM 返回的换行  |
| `overflow-wrap` | `break-word` | 超长 URL 自动断开    |
| `word-break`    | `normal`     | 启用标准 CJK 换行    |
| `line-break`    | `strict`     | 启用严格中文排版规则 |

------

# **六、line-break: strict 的作用**

启用：

```css
line-break: strict;
```

后，浏览器会进入：

```text
Unicode Line Breaking Algorithm（Unicode 换行算法）
+
CJK Typography Rules（中日韩排版规则）
```

浏览器会自动识别：

```text
禁止出现在行首的 Unicode 标点
```

例如：

```text
、
。
，
》
」
）
】
】
```

因此这些字符不会再被放到新行开头。



同时：

```text
《
「
（
```