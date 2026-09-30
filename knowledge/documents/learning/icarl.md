---
schema_version: 1
id: icarl
title: iCaRL前置知识
type: learning-note
domains: []
topics: []
tags: []
sources: []
review:
  human:
    status: unreviewed
maintenance:
  status: legacy
provenance:
  origin: imported
  ai_assisted: false
---

## 一、从任务形态开始理解 Class-Incremental Learning

### 1. 输入为一段不断扩展的类别流

普通多分类训练通常假设，训练开始时已经知道全部类别：

$$
\mathcal{Y}
=
\{1,2,\ldots,C\}
$$

并且可以同时访问所有类别的训练数据：

$$
D
=
\bigcup_{y=1}^{C}D_y
$$

Class-Incremental Learning（CIL）的输入形式不同。类别按照时间逐步出现：

```text
阶段 1
获得 Classes 1...10 的完整训练数据
        ↓
训练并离开这些完整数据

阶段 2
获得 Classes 11...20 的完整训练数据
        ↓
继续更新同一个系统

阶段 3
获得 Classes 21...30
        ↓
……
```

假设第 $r$ 个阶段新增类别集合为：

$$
\mathcal{C}_r
$$
系统在第 $r$ 个阶段结束后必须能够在：

$$
\mathcal{Y}_r
=
\mathcal{C}_1
\cup\cdots\cup
\mathcal{C}_r
$$

中的所有已见类别之间进行一次统一分类。

这里最关键的是： 测试时通常不会告诉模型“这个样本属于第几个任务”。

所以 CIL 不是分别维护：

```text
Task 1 classifier
Task 2 classifier
Task 3 classifier
```

然后根据 task ID 选择其中一个。

它要求：

```text
输入 x
  ↓
一个统一分类决策
  ↓
在全部已见类别中选一个 y
```

---

### 2. CIL 与此前 LwF / EWC 常见设定的差别

此前可以把持续学习想成：

```text
Task A
↓
Task B
↓
Task C
```

每个 task 可以拥有自己的语义和输出空间。

但 iCaRL 关注的是：

```text
原本认识：
cat, dog

后来新增：
car, bus

再后来新增：
apple, orange
```

最终分类器必须直接回答：

$$
\hat y
\in
\{
\text{cat},
\text{dog},
\text{car},
\text{bus},
\text{apple},
\text{orange}
\}
$$

因此这里新增的不只是“新的数据分布”，而是：

> **分类空间本身持续扩张。**

这会额外引入三个实际问题：

```text
旧类数据逐渐不可访问
        ↓
旧类 Representation 容易被新类训练改变

类别不断增加
        ↓
Classifier 也必须不断扩展

测试时没有 Task ID
        ↓
旧类与新类必须直接竞争
```

所以只做到“旧任务输出不要完全忘掉”还不够，还必须让所有已见类别最终处在同一个可比较的分类空间中。

---

### 3. CIL 系统维护的状态

假设当前已经观察到 $t$ 个类别。

系统至少需要某种：

```text
当前 Representation
+
所有已见类别的分类依据
+
对旧类别的历史信息
```

不同方法对“历史信息”的保存方式不同。

EWC 主要保存：

```text
旧参数位置
+
参数重要性
```

iCaRL 使用的核心历史载体则会变成：

```text
少量旧类原始样本
```

这些少量样本称为：

> exemplar。

---

## 二、Feature Representation 与分类规则

### 1. Backbone 首先把图像变成特征向量

设特征提取器为：

$$
\phi_\Theta:\mathcal X\rightarrow\mathbb R^d
$$

输入图像：

$$
x
$$

经过网络得到：

$$
z=\phi_\Theta(x)
$$

其中：

$$
z\in\mathbb R^d
$$

是 feature vector。

后续分类并不一定必须由神经网络最后一个 Linear Layer 完成。

整个视觉分类系统可以拆成：

```text
Image x
   ↓
Feature Extractor φ_Θ
   ↓
Feature z
   ↓
Classification Rule
   ↓
Class y
```

Representation Learning 负责：

> 把语义相似的图像映射到有利于分类的特征空间。

Classifier 负责：

> 在这个特征空间里定义“怎样决定类别”。

---
### 2. 普通线性分类器依赖当前 Representation

设类别 $y$ 对应权重：

$$
w_y\in\mathbb R^d
$$

线性 score 为：

$$
a_y(x)
=
w_y^T\phi_\Theta(x)
$$

普通网络最终根据这些 score 决定类别。

问题在于：
$$
w_y
$$
是在某个特定 feature space 中学到的。

如果后续持续训练使：
$$
\phi_{\Theta_{\text{old}}}(x)
$$
变成：
$$
\phi_{\Theta_{\text{new}}}(x)
$$
那么即使同一张图像没有变化，它在特征空间中的位置也可能变化。

于是旧权重：

$$
w_y
$$

可能不再适配新的 Representation。

可以把这个问题写成：

```text
旧阶段：

image
 ↓
φ_old
 ↓
feature space A
 ↓
w_old 可以正确划分类别

持续训练后：

image
 ↓
φ_new
 ↓
feature space B

但旧 classifier
未必同步适配 feature space B
```

因此在 CIL 中：

> “Feature Extractor 是否遗忘”和“Classifier 是否仍然与 Feature Space 对齐”是两个相关但不完全相同的问题。

---

## 三、Nearest Class Mean 与 Prototype Classification

### 1. 用类别中心代替可学习分类权重

假设类别 $y$ 有训练样本：

$$
X_y
=
\{x_1^y,\ldots,x_{n_y}^y\}
$$

把所有样本映射到 feature space：

$$
\phi(x_1^y),
\ldots,
\phi(x_{n_y}^y)
$$

可以计算该类别的特征均值：

$$
\mu_y
=
\frac{1}{n_y}
\sum_{x\in X_y}
\phi(x)
$$

$\mu_y$ 可以视为类别 $y$ 在 feature space 中的 prototype。

对于测试样本 $x$：

$$
z=\phi(x)
$$

Nearest Class Mean（NCM）选择：

$$
\hat y
=
\arg\min_y
\left\|
\phi(x)-\mu_y
\right\|_2
$$

因此分类过程不再依赖一组独立学习出来的：
$$
w_y
$$
而是依赖：

> 当前 Representation 下，类别样本本身形成的中心。

---

### 2. L2 Normalization 对距离规则的影响

如果 feature vector 都经过 L2 normalization：

$$
\|\phi(x)\|_2=1
$$

prototype 计算后也重新 normalization：

$$
\|\mu_y\|_2=1
$$

则：

$$
\|\phi(x)-\mu_y\|_2^2
=
\|\phi(x)\|_2^2
+
\|\mu_y\|_2^2
-
2\mu_y^T\phi(x)
$$

因为前两项均为 1：

$$
\|\phi(x)-\mu_y\|_2^2
=
2-2\mu_y^T\phi(x)
$$

因此：

$$
\arg\min_y
\|\phi(x)-\mu_y\|_2
=
\arg\max_y
\mu_y^T\phi(x)
$$

也就是说，在单位球面上：

> 最近 prototype 与最大内积分类是等价的。

而 prototype classifier 并不是与线性分类完全无关；它也可以写成一个线性 score：

$$
s_y(x)
=
\mu_y^T\phi(x)
$$

区别只在于它的“weight vector”不是独立优化出来的 $w_y$，而是由当前数据特征均值产生的 $\mu_y$。

---

### 3. Prototype 更新

如果保存的是原始 exemplar image：
$$
p
$$
那么 Representation 更新：
$$
\phi_{\text{old}}
\rightarrow
\phi_{\text{new}}
$$
之后，可以重新计算：
$$
\phi_{\text{new}}(p)
$$
于是 prototype：
$$
\mu_y
=
\frac{1}{|P_y|}
\sum_{p\in P_y}
\phi_{\text{new}}(p)
$$

也会自动进入新的 feature space。这与直接保存旧 feature vector：
$$
z_p=\phi_{\text{old}}(p)
$$
完全不同。如果只保存：
$$
z_p
$$

Representation 更新后它仍然停留在旧空间。所以对一个会持续改变 feature extractor 的系统而言：

> **保存原始 exemplar image 比保存旧 embedding 更能跟随 Representation 变化。**

---

## 四、Class Mean 缺陷

### 1. NCM 条件

要计算真正的：

$$
\mu_y
=
\frac{1}{|X_y|}
\sum_{x\in X_y}\phi(x)
$$
必须拥有该类所有样本：
$$
X_y
$$
如果 $\phi$ 永远固定，那么可以在第一次看到该类时计算 $\mu_y$ 并长期保存。

但持续学习中：
$$
\phi
$$
会继续变化。

于是每次 Representation 更新后，理论上都应该重新计算：
$$
\mu_y^{\text{new}}
=
\frac{1}{|X_y|}
\sum_{x\in X_y}
\phi_{\text{new}}(x)
$$
这要求重新访问所有旧类原始数据。如果这些数据已经不再保存，就无法得到真正的 current class mean。

---

### 2. Exemplar Mean

解决办法是每个旧类只保存少量样本：
$$
P_y
\subset X_y
$$
其中：
$$
|P_y|\ll|X_y|
$$
再计算：
$$
\hat\mu_y
=
\frac{1}{|P_y|}
\sum_{p\in P_y}
\phi(p)
$$
希望：
$$
\hat\mu_y
\approx
\mu_y
$$
问题由此转变为：

> 在只能保存很少样本时，怎样选出一个子集，让它的 feature mean 尽量逼近完整类别的 feature mean？

这就是 exemplar selection 要解决的问题。

---

## 五、Exemplar Rehearsal 与固定内存预算

### 1. Exemplar 用途

在 iCaRL 这类系统中，旧 exemplar 可以同时承担两个角色。

<mark style="background:#fdbfff"><font color="#7030a0">第一：</font></mark>

```text
旧 exemplar
   ↓
重新进入训练
   ↓
让网络继续看到旧类输入分布的一小部分
```

这叫 rehearsal / replay。

<mark style="background:#fdbfff"><font color="#7030a0">第二：</font></mark>

```text
旧 exemplar
   ↓
通过当前 φ 计算 features
   ↓
求 exemplar mean
   ↓
作为分类 prototype
```

所以 exemplar 既是：

> 训练记忆

也是：

> 分类器状态。

---

### 2. 旧数据的有限保存

如果每出现一个类别就永久保存全部训练数据：
$$
\text{Memory}
\propto
\text{Seen Data}
$$
那么持续学习会退化成：

> 把所有数据保存下来反复 batch training。

这违背了 CIL 希望内存增长受控的要求。因此设固定 exemplar budget $K$，无论观察多少类别，总共最多保存 $K$ 张 exemplar image。

---

### 3. 类别内存与类别数关系

当前共观察到 $t$ 个类别，如果各类平均分配预算，则每类最多保存 $m=\left\lfloor \frac{K}{t} \right\rfloor$ 个 exemplar。

所以当 $t\uparrow$ 时 $m\downarrow$。这意味着 CIL 中 exemplar management 不只是“新类别来时增加一些图片”。

它还必须执行：

```text
类别数量增加
    ↓
每类可用 quota 下降
    ↓
旧类 exemplar set 必须缩减
```

而旧类别完整训练数据已经不存在，所以缩减操作不能依赖重新访问$X_y$，这会直接影响 exemplar selection 的设计。

---

## 六、Herding： Class Mean 压缩

### 1. 选择目标

设某个新类别 $y$ 的完整训练集仍然可访问：

$$
X_y
=
\{x_1,\ldots,x_n\}
$$
先使用当前 Representation 计算真实 class mean：

$$
\mu
=
\frac{1}{n}
\sum_{x\in X_y}
\phi(x)
$$
现在希望选择：
$$
P_y=(p_1,p_2,\ldots,p_m)
$$

使前 $m$ 个 exemplar 的均值 $\frac{1}{m}\sum_{j=1}^{m}\phi(p_j)$ 尽可能接近$\mu$

---
### 2. 顺序式选择

Herding 不是先给每张图片计算一个“代表性分数”，再取前 $m$ 张，而是**逐步优化当前 exemplar 前缀的整体均值**。

为了避免和最终用于分类的 exemplar prototype 混淆，这里把当前还能访问全部训练样本时得到的真实 class mean 记为：

$$
\bar{\mu}_y
=
\frac{1}{|X_y|}
\sum_{x\in X_y}
\phi(x)
$$

已经选出：

$$
p_1,\ldots,p_{k-1}
$$

以后，第 $k$ 个 exemplar 选择：

$$
p_k
=
\arg\min_{x\in X_y}
\left\|
\bar{\mu}_y
-
\frac{1}{k}
\left[
\phi(x)
+
\sum_{j=1}^{k-1}
\phi(p_j)
\right]
\right\|_2
$$

这里优化的对象不是候选 $x$ 自己与 $\bar{\mu}_y$ 的距离，而是：

$$
\frac{1}{k}
\left[
\phi(x)
+
\sum_{j=1}^{k-1}\phi(p_j)
\right]
$$

也就是“如果把 $x$ 加进来，前 $k$ 个 exemplar 的平均 feature 会落在哪里”**。

因此选择过程是：

```text
k = 1
选择 p1
使 φ(p1) 尽量接近完整类别均值

        ↓

k = 2
固定 p1
选择一个 p2
使 [φ(p1)+φ(p2)] / 2
尽量接近完整类别均值

        ↓

k = 3
固定 p1、p2
选择 p3
使三个 exemplar 的平均 feature
继续逼近完整类别均值

        ↓
……
```

这里不能写成：

$$
p_1\ge p_2\ge p_3
$$

并把它理解为“$p_1$ 单独最接近 class mean，$p_2$ 次之，$p_3$ 再次之”。

只有 $p_1$ 是在单个样本条件下直接选择最接近 $\bar{\mu}_y$ 的样本；从 $p_2$ 开始，选择目标已经变成了**补偿当前 exemplar 前缀的均值偏差**。因此某个 $p_k$ 单独看可能并不比后面的 exemplar 更接近 class mean，但把它加入前缀以后，整个前缀的平均 feature 更接近 $\bar{\mu}_y$。

所以 herding 中真正的“优先级”是：

> **较短前缀已经被构造成一个尽可能好的 class-mean approximation。**

而不是：

> 每个 exemplar 按照它单独距离 class mean 的远近进行排序。

这也解释了后续为什么可以从列表尾部删除 exemplar。

另外，这种优先级是在**选择 exemplar 当时的 Representation $\phi$** 下建立的。后续持续学习会使：

$$
\phi_{\text{old}}
\rightarrow
\phi_{\text{new}}
$$

于是原来选出的：

$$
p_1,p_2,\ldots
$$

在新的 feature space 中未必仍然构成最优的 herding 顺序。

但此时旧类别完整数据：

$$
X_y
$$

已经不可访问，因此无法重新计算完整 class mean 并重新执行 herding。iCaRL 能做的是：

```text
保留当时选择出的原始 exemplar images
        ↓
Representation 更新后
重新计算这些 images 的当前 feature
        ↓
用当前 feature 重新计算类别 prototype
```

因此要区分下面四个对象：

- $y$：类别编号；
- $X_y$：类别 $y$ 的完整训练数据，只在该类别首次到来时完整可用；
- $P_y=(p_1,\ldots,p_m)$：类别 $y$ 保存下来的 exemplar image 列表；
- $\mu_y$：当前时刻由 $P_y$ 在**当前 Representation** 下计算出的 exemplar prototype。

分类时使用：
$$
\mu_y
=
\frac{1}{|P_y|}
\sum_{p\in P_y}
\phi(p)
$$
并在平均后重新进行 L2 normalization。

对查询样本 $x$：

$$
\hat y
=
\arg\min_y
\left\|
\phi(x)-\mu_y
\right\|_2
$$

由于 $\phi(x)$ 和 $\mu_y$ 都经过 L2 normalization：

$$
\hat y
=
\arg\max_y
\mu_y^T\phi(x)
$$

如果把所有类别 prototype 作为列向量组成：
$$
W_\mu
=
[\mu_1,\mu_2,\ldots,\mu_t]
\in
\mathbb R^{d\times t}
$$
则：
$$
W_\mu^T\phi(x)
\in
\mathbb R^t
$$
第 $y$ 个维度就是：
$$
\mu_y^T\phi(x)
$$
最终选择最大维度对应的类别。

它在形式上和普通线性分类器：

$$
W^T\phi(x),
\qquad
W=[w_1,\ldots,w_t]
$$

很相似，但二者的列向量来源不同：

```text
普通线性分类器：
w_y 是通过梯度下降学习出来的参数

iCaRL prototype classifier：
μ_y 是当前 φ 下
旧类 exemplar features 的均值
```

因此 Representation 更新后，$w_y$ 不会自动跟着旧类样本的新位置移动；而 $\mu_y$ 会因为重新编码 exemplar images 而随当前 feature space 更新。

### 3. 有顺序的列表

固定内存预算意味着未来可能需要从：

$$
m_0
$$

个 exemplar 缩减到：

$$
m<m_0
$$

但那时：
$$
X_y
$$

已经没有了。

如果原来只是选出了一个无序集合，就无法知道应该删除谁。

Herding 的顺序构造使：

$$
(p_1,\ldots,p_m)
$$

本身就是高优先级前缀。因此未来缩减时只需：

$$
P_y
\leftarrow
(p_1,\ldots,p_m)
$$

直接删除末尾即可。这个 prefix property 是它适合 class-incremental memory management 的关键原因。

---

## 七、iCaRL 训练

这一部分需要先把 iCaRL 训练阶段的数据流固定下来。对于输入图像 $x$，网络先通过 Feature Extractor 得到：
$$
z=\phi_\Theta(x)
$$
当前一共已经建立了 $t$ 个类别输出节点，每个类别 $y$ 都有自己的线性权重：
$$
w_y
$$
先得到 logit：
$$
a_y(x)
=
w_y^T\phi_\Theta(x)
$$
iCaRL 原论文随后对**每一个类别节点独立使用 Sigmoid**：
$$
g_y(x)
=
\sigma(a_y(x))
=
\frac{1}{1+e^{-a_y(x)}}
$$
所以训练阶段完整的数据流是：

```text
Image x
   ↓
Feature Extractor φ_Θ
   ↓
Feature z
   ↓
每个类别各自的 Linear Score a_y = w_y^T z
   ↓
每个类别各自经过 Sigmoid
   ↓
g_1(x), g_2(x), ..., g_t(x)
   ↓
Binary Cross-Entropy
   ↓
反向传播
   ↓
同时更新 Feature Extractor 和输出层
```

需要特别注意：

> **Softmax 在原始 iCaRL 的训练 Head 中并没有被使用。**

---

### 1. Softmax 与独立 Sigmoid 在流程中的位置

#### Softmax：把整组 Logits 变成一个互相竞争的概率分布

普通 $C$ 类单标签分类通常先得到：
$$
a(x)
=
[a_1(x),a_2(x),\ldots,a_C(x)]
$$

然后一次性对整个向量做 Softmax：
$$
p(y=c\mid x)
=
\frac{e^{a_c(x)}}
{\sum_{j=1}^{C}e^{a_j(x)}}
$$
因此：$$\sum_{c=1}^{C}p(y=c\mid x)=1$$
它表达的是：

> 这张图只能从这 $C$ 个类别中选择一个类别，因此所有类别共同竞争总概率质量 $1$。

流程是：

```text
Feature
  ↓
C 个 logits
  ↓
对整个 logit vector 做一次 Softmax
  ↓
一个 C 维概率分布
  ↓
通常配合 Multi-class Cross-Entropy
```

如果某个类别的 Softmax 概率上升，在归一化作用下其他类别概率会受到影响，因此不同类别输出是耦合的。

#### Sigmoid：每个类别节点独立回答一个二值问题

iCaRL 对每个：

$$
a_y(x)
$$

单独计算：

$$
g_y(x)
=
\sigma(a_y(x))
$$

因此：

$$
g_1(x),\ldots,g_t(x)
$$

之间没有“总和必须为 1”的约束。

每个节点独立表示：

> 对当前输入而言，类别 $y$ 这个输出节点应该有多大的响应？

所以流程变成：

```text
Feature
  ↓
t 个 logits

a_1   a_2   ...   a_t
 ↓     ↓           ↓
σ      σ            σ
 ↓     ↓           ↓
g_1   g_2   ...   g_t
```

这些输出之后**逐节点**与各自 target 计算 Binary Cross-Entropy。这种形式非常适合 iCaRL 当前的训练目标，因为同一个样本可以同时拥有：

```text
旧类别节点：
使用旧模型留下来的 soft target

新类别节点：
使用当前真实标签形成的 hard target
```

二者可以直接组成一个长度为 $t$ 的 target vector，并逐节点训练。

再次强调：这些 Sigmoid 输出是训练 Representation 时使用的；iCaRL 最终预测类别时并不执行：
$$
\arg\max_y g_y(x)
$$
最终预测仍然使用 exemplar prototype。

---
### 2. Binary Cross-Entropy、Hard Label 与 Soft Label

#### Hard Label 是确定的 0/1 监督

对于一个独立 Sigmoid 节点，target 记为：

$$
r\in[0,1]
$$

如果使用 hard label，则：

$$
r\in\{0,1\}
$$

含义是确定的：

```text
r = 1
→ 希望这个类别节点对当前样本产生高响应

r = 0
→ 希望这个类别节点对当前样本产生低响应
```

Binary Cross-Entropy 为：

$$
\ell(r,g)
=
-
\left[
r\log g
+
(1-r)\log(1-g)
\right]
$$

当$r=1$时：
$$
\ell(1,g)
=
-\log g
$$

Loss 会推动：
$$
g\rightarrow1
$$

当 $r=0$ 时：
$$
\ell(0,g)
=
-\log(1-g)
$$
Loss 会推动：
$$
g\rightarrow0
$$

如果把 Sigmoid 之前的 logit 记为$a$，由于：
$$
g=\sigma(a)
$$

BCE 对 logit 的梯度具有非常直接的形式：
$$\frac{\partial\ell}{\partial a}=g-r$$
所以：

```text
Hard target r = 1：
如果当前 g 太小
g-r < 0
→ 梯度推动 logit 增大
→ g 增大

Hard target r = 0：
如果当前 g 太大
g-r > 0
→ 梯度推动 logit 减小
→ g 减小
```

这就是 hard label 真正进入参数更新的方式。

#### Soft Label 为 Teacher 的连续输出

soft label / soft target 允许：

$$
0<r<1
$$

在 iCaRL 中，它不是人工指定一个模糊类别，而是来自**更新前旧模型自己的输出**。

对于样本 $x_i$ 和旧类别节点 $y$：

$$
q_i^y
=
g_y^{\text{old}}(x_i)
$$

例如旧模型可能认为：
$$
q_i^y=0.73
$$

那么新模型训练这个旧类别节点时，目标不是强迫：
$$
g_y^{\text{new}}(x_i)\rightarrow1
$$

或者：
$$
g_y^{\text{new}}(x_i)\rightarrow0
$$

而是希望：
$$
g_y^{\text{new}}(x_i)
\rightarrow
q_i^y
$$

即保持更新前模型对这个输入、这个旧类别的响应强度。

对应梯度：

$$
\frac{\partial\ell}{\partial a_y}
=
g_y^{\text{new}}(x_i)-q_i^y
$$

如果新模型输出已经接近旧模型$g_y^{\text{new}}(x_i) \approx q_i^y$ 这一项产生的梯度就很小。如果偏离明显，Distillation Loss 就会产生梯度，把新的输出拉回旧模型的响应。

所以 hard label 与 soft label 的作用可以严格区分为：

```text
Hard Label
来源：当前阶段的 Ground Truth
作用：告诉新类别节点“应该是什么”

Soft Label
来源：更新前旧模型的输出
作用：告诉旧类别节点“原来是什么，不要漂移太远”
```

需要注意，iCaRL 使用的是**独立 Sigmoid 输出**，所以：
$$
q_i^1,\ldots,q_i^{s-1}
$$
并不要求总和为 1。这里的 soft target 是每个旧类别节点各自需要保持的 response，而不是一个 Softmax 概率分布。

---
### 3. 新类别 Hard Target 与旧类别 Soft Target

这里首先要区分两个维度：

```
维度一：当前输入样本属于什么类别
- 新类别样本
- 旧类别 exemplar

维度二：网络中的输出节点属于什么类别
- 旧类别节点 1,...,s-1
- 新类别节点 s,...,t
```

<mark style="background:#fdbfff"><font color="#7030a0">iCaRL 决定使用 Hard Target 还是 Soft Target，依据的是输出节点属于旧类别还是新类别，而不是当前输入图片属于新类还是旧类。</font></mark>

假设更新前模型已经认识旧类别：
$$  
1,\ldots,s-1  
$$
这一轮新增类别：
$$  
s,\ldots,t  
$$
当前训练集为：
$$D_{\text{new}}  \cup  D_{\text{exemplar}}  $$
其中：

```
D_new = 本轮新类别的完整训练数据

D_exemplar = 之前旧类别留下来的 exemplar images
```

#### 第一步：在参数更新前固定旧类别节点的 Soft Targets

开始训练本轮新类别之前，先<mark style="background:#fdbfff">保留一份</mark>**更新前的旧模型**。对于训练集 $D$ 中的每一个输入$x_i$ ，都让旧模型计算所有旧类别节点$y=1,\ldots,s-1$ 的输出 $g_y^{\text{old}}(x_i)$。 

注意，在这里的$D$就已经明确表明了是 含$D_{exemplar}$的组成，而不是所有的$D_{old} \cup D_{new}$，然后每一个$x_i$有它对应的
$$Q_i = \left[  q_i^1,  q_i^2,  \ldots,  q_i^{s-1}  \right],q_i^y = g_y^{old}(x_i)$$

需要注意：**无论 $x_i$ 本身是新类别图片还是旧类别 exemplar，都要计算这个旧类别响应向量。**

原因并不是认为“新类别图片也属于旧类别”，而是要记录：

> 在参数更新之前，旧模型面对这个输入时，原来的旧类别判别函数产生了什么响应。

后续学习新类会修改共享 Feature Extractor $\phi_\Theta$ ，如果完全不约束旧类别节点，那么新任务梯度可能使  $g_y^{\text{new}}(x)$ 与  $g_y^{\text{old}}(x)$发生很大偏离。

所以对旧类别节点，iCaRL 希望 $g_y^{\text{old}}(x_i)$ 这就是 Distillation 所保护的对象。这些 $q_i^y$ 一旦在本轮训练开始前记录下来，在整个 Representation Update 中都保持不变。不能训练一会儿后重新用当前模型生成 $q_i^y$，否则 teacher target 会跟着 student 一起变化，便失去了“保持更新前行为”的参照。

---
#### 第二步：按照“旧节点 / 新节点”构造完整 Target Vector

对于任意训练样本：
$$  
(x_i,y_i)\in D  
$$
当前模型会产生：

$$
g_1(x_i),  
g_2(x_i),  
\ldots,  
g_t(x_i)  
$$

共 $t$ 个 Sigmoid 输出。

对应的完整 target 定义为：
$$
r_i^y
=
\begin{cases}
q_i^y,
&
1\le y<s
\\[4pt]
\mathbf 1[y=y_i],
&
s\le y\le t
\end{cases}
$$
因此

```
旧类别输出节点
→ Soft Target

新类别输出节点
→ Hard Target
```

同一个输入样本会同时产生这两种监督信号。

---

#### 第三步：新类别样本与旧 Exemplar 分别如何形成 Target

##### 新类别样本

假设$x_i$属于本轮新增类别：
$$  
y_i=c,  
\qquad  
c\in{s,\ldots,t}  
$$
对于旧类别节点：
$$  
1,\ldots,s-1  
$$
仍然使用旧模型保存的整个响应向量：
$$  
q_i^1,  
q_i^2,  
\ldots,  
q_i^{s-1}  
$$

即：

```
旧类别节点 1 ... s-1

→ target = q_i^1 ... q_i^{s-1}

→ 要求新模型继续保持：
   旧模型以前看到这张输入时，
   对所有旧类别产生的响应
```

这里并不是说这张新图片属于某个旧类别。这些值表达的是：

> 旧模型原来的函数行为。

对于新类别节点：
$$  
s,\ldots,t  
$$
则直接根据真实标签构造：$$ \mathbf 1[y=c]  $$因此：

```
类别 c 节点
→ target = 1

其他本轮新类别节点
→ target = 0
```

负责真正学习当前新类别。例如旧类别为$1,2,3$，新类别为$4,5$，当前图片属于：

$$  
y_i=4  
$$

更新前旧模型可能输出：$[0.08,0.31,0.04]$，那么这一样本的完整 target 就是：$[0.08,;0.31,;0.04,;1,;0]$

前三维负责：

> 保持旧模型的旧类别响应。

后两维负责：

> 学习新类别 4。

因此新类别图片也具有旧类别 soft target，是因为学习新类时会改变共享 Representation，而 distillation 要限制这种变化不要任意破坏旧类别判别函数。

---
##### 旧类别 Exemplar

这里需要提一嘴，在开始训练前，
再考虑：
$$  
x_i  
$$
是一张旧类别 exemplar，并且真实属于：
$$  
y_i=c,  
\qquad  
c<s  
$$
对于旧类别节点：
$$  
1,\ldots,s-1  
$$
iCaRL **仍然对全部旧类别节点使用 Soft Target**：
$$  
q_i^1,  
q_i^2,  
\ldots,  
q_i^{s-1}  
$$
而不是只对真实旧类别 $c$ 使用：
$$  
q_i^c  
$$

原因是 Distillation 想保存的并不是：

> “正确类别这个节点原来是多少”。

而是：

> **旧模型对这个输入形成的整个旧类别响应结构。**

例如一张真实类别 2 的 exemplar，旧模型可能产生$[0.12,0.86,0.07]$

iCaRL 希望更新后仍然满足：
$$  
[g_1,g_2,g_3]_{\text{new}}  
\approx  
[0.12,0.86,0.07]  
$$

所以 Soft Target 保护的是：
$$  
\boxed{  
\text{旧模型完整的旧类别输出函数}  
}  
$$
而不是：
$$  
\boxed{  
\text{真实旧类别对应的单个输出节点}  
}  
$$


因此一张旧 exemplar 同时发挥两种作用：

```
在旧类别节点上：

Soft Targets
→ 保持旧模型整个旧类别响应结构


在新类别节点上：

Hard Target = 0
→ 告诉新节点：
   不要把这张旧类别图片误认为任何一个新类别
```

这也解释了 exemplar 为什么比“只在新类别数据上做 LwF 式 distillation”更有价值：

> exemplar 让真正来自旧类别分布的输入再次经过当前 Feature Extractor，于是 distillation 可以直接在旧数据所在区域约束 Representation。

---

#### 第四步：Hard Target 与 Soft Target 如何共同形成最终 Loss

对于训练集中的所有：

$$  
(x_i,y_i)\in D  
$$

Loss 可以拆成：
$$L_{\text{new}}  +  L_{\text{old}}  $$

其中，新类别节点使用 Hard Target：
$$\sum_{(x_i,y_i)\in D}  \sum_{y=s}^{t}  \left[  \mathbf 1[y=y_i]\log g_y(x_i)  +  \mathbf 1[y\neq y_i]\log(1-g_y(x_i))  \right]  $$

它负责：

> 利用当前 Ground Truth 学习新类别。

旧类别节点使用 Soft Target：
$$\sum_{(x_i,y_i)\in D}  \sum_{y=1}^{s-1}  \left[  q_i^y\log g_y(x_i)  +  (1-q_i^y)\log(1-g_y(x_i))  \right]$$

它负责：

> 让更新后的网络继续复现更新前模型的旧类别响应。

因此同一个训练 batch 中实际同时存在两股梯度：

```
L_new
    ↓
推动 Feature Extractor 学会区分新类别

          +

L_old
    ↓
限制 Feature Extractor 和旧输出节点
不要破坏已有旧类别判别行为

          ↓

共同反向传播
          ↓
更新共享 Representation φ_Θ
```

这就是 iCaRL 中 Hard Target 与 Soft Target 同时存在的目的：
$$  
\boxed{  
\text{Hard Target 提供 Plasticity}  
+  
\text{Soft Target 提供 Stability}  
}  
$$
其中 exemplar 又进一步让 Stability 约束不仅作用于新类别输入，还能作用在真实旧类别输入附近。

最后仍然需要区分训练和预测：

```
训练阶段：

Image
 ↓
φ_Θ
 ↓
Linear Head
 ↓
Independent Sigmoid
 ↓
Hard / Soft Targets
 ↓
Binary Cross-Entropy
 ↓
Backprop
 ↓
更新 Representation


预测阶段：

Image
 ↓
φ_Θ
 ↓
与所有类别 exemplar prototype μ_y 比较
 ↓
Nearest-Mean-of-Exemplars
 ↓
最终类别
```

所以这一节中的 Sigmoid、Hard Target、Soft Target 与 BCE 解决的是：
> **怎样更新 Representation，同时学习新类别并尽量保持旧类别判别能力。**

而最终：
$$\arg\min_y  |\phi(x)-\mu_y|_2$$

解决的则是：

> **训练完成之后，怎样在全部已见类别中真正做统一分类。**

---
## 八、训练分类头与最终预测规则

### 1. 网络输出可以只服务于 Representation Learning

系统结构是：

```text
训练阶段：

Image
 ↓
φ_Θ
 ↓
Linear/Sigmoid Head
 ↓
Classification + Distillation Loss
 ↓
反向传播
 ↓
更新 Representation


测试阶段：

Image
 ↓
φ_Θ
 ↓
Prototype Distance
 ↓
Class
```

这里网络输出 head 的作用是：

> 提供可微分的训练目标，从而塑造 feature representation。

而真正 inference classifier 可以是：

> nearest prototype。

所以阅读 iCaRL 时必须始终区分 $\text{training objective}$ 与$\text{prediction rule}$ 二者不是同一个组件。

---

## 九、iCaRL 的完整操作链

如果现在面对一个 CIL 数据流，应该先能把问题整理成：

```text
第一个类别批次到达
        ↓
训练 feature extractor
        ↓
需要保存少量旧类信息
        ↓
每类选择 representative exemplars
        ↓
后续新类别到达
        ↓
新类完整数据 + 旧类 exemplars
共同参与 Representation 更新
        ↓
旧类输出通过 distillation 保持
        ↓
总 memory budget 固定
        ↓
旧 exemplar lists 按前缀缩减
        ↓
新类用 herding 构造 exemplar list
        ↓
测试时
用当前 φ 重新编码 exemplar images
        ↓
计算每类 exemplar mean
        ↓
nearest prototype 分类
```

这条链里有三个彼此耦合的问题：

```text
Representation 会变
→ 旧 classifier 怎样跟上？

旧完整数据会消失
→ 怎样继续训练旧类？

Memory 固定
→ 怎样让少量旧样本尽量有代表性？
```
