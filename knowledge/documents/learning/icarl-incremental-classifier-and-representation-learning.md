---
schema_version: 1
id: icarl-incremental-classifier-and-representation-learning
title: iCaRL：Incremental Classifier and Representation Learning
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

# iCaRL：Incremental Classifier and Representation Learning

> 论文：Sylvestre-Alvise Rebuffi, Alexander Kolesnikov, Georg Sperl, Christoph H. Lampert, *iCaRL: Incremental Classifier and Representation Learning*, CVPR 2017  
> 本笔记重点回答：**当类别分批到来时，iCaRL 到底保存什么、每一步先做什么、为什么顺序必须这样，以及三个组件如何共同构成一个真正可执行的 Class-Incremental 系统。**

## 一、Class-Incremental 问题

### 1. 三个判定条件

论文不是泛泛地把“顺序训练”称为 class-incremental learning，而是明确要求算法满足三个条件。

第一，训练数据以类别流形式到达，不同类别可以在不同时间出现。

第二，在任何时间点，都必须提供一个对**所有已见类别**有效的统一 multi-class classifier。

第三，计算和内存需求应保持有界，或者至少只随类别数缓慢增长，而不能简单保存全部历史训练数据后反复从头训练。

因此 iCaRL 要解决的不是：

```text
旧任务 A 保住
+
新任务 B 学会
```

真正要求是：

```text
Class 1...10
     ↓
Class 11...20 到达
     ↓
模型必须直接区分 1...20

Class 21...30 到达
     ↓
模型必须直接区分 1...30
```

而且旧类完整数据已经不再持续保留。

---

### 2. iCaRL 的核心状态

假设当前已经观察到 $t$ 个类别。CaRL 运行状态包括：
$$
\boxed{
S_t=
(\Theta,P_1,\ldots,P_t)
}
$$

其中：

- $\Theta$：当前神经网络参数；
- $P_y$：类别 $y$ 的 exemplar list。

因此，如果现在只拿到一个普通旧模型：
$$
\Theta
$$

但没有旧类别 exemplar sets：
$$
P_1,\ldots,P_t
$$

就不能完整恢复论文定义的 iCaRL 状态。因为 exemplar 不只用于 rehearsal，还直接决定 inference classifier。

这与 EWC 的状态结构很不同：

```text
EWC
模型参数 + Fisher

iCaRL
模型参数 + 原始 exemplar images
```

---

## 二、变量与网络结构

### 1. 类别数据

论文按照类别组织输入。类别 $y$ 的训练集：
$$
X_y
=
\{
x_1^y,\ldots,x_{n_y}^y
\}
$$
一次增量更新中新到达的类别为：
$$
s,s+1,\ldots,t
$$
所以当前新增数据是：
$$
X_s,\ldots,X_t
$$
在此之前已经观察过的旧类别为：
$$
1,\ldots,s-1
$$

---

### 2. Feature Extractor

网络中的 Representation 定义为：
$$
\phi:\mathcal X\rightarrow\mathbb R^d
$$
由参数 $\Theta$ 控制。论文明确说明所有 feature vector 都进行 L2 normalization；对 feature 做平均以后也会再次 normalization，只是为了避免公式冗长没有反复写出。

---
### 3. Network Output Head

对于已经观察到的每个类别 $y$，网络都有一个 weight vector：
$$
w_y\in\mathbb R^d
$$
logit：
$$
a_y(x)
=
w_y^T\phi(x)
$$
输出：
$$
g_y(x)
=
\frac{1}
{1+\exp(-a_y(x))}
$$
这是独立 sigmoid output，而不是一个 Softmax。当前观察到 $t$ 个类别时，就有：

$$
w_1,\ldots,w_t
$$
因此新类别到达后，输出层也要增加对应的新 class weight vectors。

---
### 4. 系统组件关系

虽然网络具有：
$$
g_1(x),\ldots,g_t(x)
$$

这些分类输出，论文明确指出：

> iCaRL 不使用它们作为最终分类规则。

这些输出主要用于：

```text
Representation Learning
+
Distillation
```

真正 inference 时使用的是：

> nearest-mean-of-exemplars。

因此整个系统应画成：

```text
                         ┌─ Sigmoid outputs g_y
Image → Feature φ_Θ ─────┤
                         │   用于训练 Representation
                         │
                         └─ Exemplar prototypes μ_y
                             用于最终分类
```

这是理解 iCaRL 最重要的结构之一。

---

## 三、iCaRL 核心组件

论文将方法明确分成三个组成部分。

### 1. Nearest-Mean-of-Exemplars Classification

解决：

> Representation 持续变化时，旧的 parametric classifier weight 容易与新的 feature space 脱节。

iCaRL 不直接使用旧：
$$
w_y
$$
做最终预测，而是用 exemplar images 在**当前** feature extractor 下重新形成 prototype：
$$
\mu_y
=
\frac{1}{|P_y|}
\sum_{p\in P_y}
\phi(p)
$$
所以 Representation 更新后，prototype 也会随着：
$$
\phi
$$
变化。

---

### 2. Exemplar Rehearsal

解决：

> 新类别训练时旧类别完整数据已经不可访问。

Representation update 时训练集不只有新类数据，还加入旧 exemplar。

所以旧类真实输入分布的一小部分可以继续进入：

$$
\text{backpropagation}
$$

过程。

---

### 3. Herding-Based Prioritized Exemplar Selection

解决：

> 固定内存预算下，每个类别只能留下少量图片，而且随着类别增多还必须继续删减。

Herding 的目标不是寻找“最典型的一张图”，而是构造一个有顺序的 list：

$$
(p_1,p_2,\ldots)
$$

使任何较短前缀的 feature mean 都尽量接近完整 class mean。

因此以后旧类数据消失后仍然可以简单截断：

$$
P_y\leftarrow(p_1,\ldots,p_m)
$$

而无需重新选样本。

---

## 四、一次 Incremental Update 的完整输入与输出

假设当前已有：

$$
s-1
$$

个旧类别。

新一批类别：

$$
s,\ldots,t
$$

现在到达。

调用论文 Algorithm 2：

$$
\text{INCREMENTALTRAIN}
(
X_s,\ldots,X_t;
K,\Theta,P
)
$$

输入是：

```text
当前网络 Θ

旧 exemplar lists：
P1,...,P_{s-1}

新类别完整数据：
Xs,...,Xt

总 exemplar budget：
K
```

更新完成后输出状态：

```text
新的网络 Θ

所有已见类别的 exemplar lists：
P1,...,Pt
```

整个更新顺序不能随意交换：

```text
1. Update Representation
        ↓
2. 根据新的类别总数计算 m = K/t
        ↓
3. Reduce 旧 exemplar sets
        ↓
4. Construct 新类别 exemplar sets
```

这个顺序本身就是算法的一部分。

---

## 五、构造 Representation Update 训练数据

### 1. 新类别使用完整当前数据

当前新类别：
$$
s,\ldots,t
$$
完整加入训练集：

$$
\bigcup_{y=s}^{t}
\{
(x,y):x\in X_y
\}
$$

---

### 2. 旧类别只使用 Exemplars

旧类别：

$$
1,\ldots,s-1
$$

只能使用：

$$
P_y
$$

因此加入：

$$
\bigcup_{y=1}^{s-1}
\{
(x,y):x\in P_y
\}
$$

最终训练集：

$$
D
=
\left[
\bigcup_{y=s}^{t}
\{
(x,y):x\in X_y
\}
\right]
\cup
\left[
\bigcup_{y=1}^{s-1}
\{
(x,y):x\in P_y
\}
\right]
$$

所以一次增量训练真正看到的数据结构是：

```text
大量新类完整样本
+
少量旧类 exemplar
```

论文没有在主算法中额外规定 balanced sampler，因此原始训练集天然存在：

> 新类完整数据与旧类有限 rehearsal memory 之间的不平衡。

后面网络输出容易偏向近期类别，与这种数据条件和持续 Representation 更新都有关系；iCaRL 最终通过 exemplar-based classification 避免直接依赖这些 network outputs 作为最终决策。

---

## 六、训练前冻结旧模型响应

### 1. Teacher Target 必须在参数更新之前生成

在对：
$$
\Theta
$$

执行任何新一轮训练之前，iCaRL 先对训练集：

$$
D
$$

运行当前旧模型。

对于每一个旧类别：

$$
y=1,\ldots,s-1
$$

以及每一个：

$$
(x_i,\cdot)\in D
$$

记录：

$$
q_i^y
=
g_y(x_i)
$$

注意这里有两个容易忽略的细节。

第一，$q_i^y$ 不只在旧 exemplar 上计算，而是对：

> **整个当前训练集 $D$**

计算。

这意味着新类图像也会被旧模型产生一组旧类 soft responses。

第二，这些：

$$
q_i^y
$$

是在 representation update 之前固定下来的。后续参数不断变化时，target 不应跟着当前网络同步变化，否则 distillation 约束就失去了“保留更新前行为”的意义。

---

### 2. 保存旧类别输出

该阶段记录：

$$
q_i^y
$$

但不需要把：

$$
\phi_{\text{old}}(x_i)
$$

固定为训练目标。

因此 iCaRL 允许 Representation 本身发生调整，只限制旧 class outputs 不要完全丢失。这里继承了 LwF 的核心思想，但与 LwF 最大的不同是：

> iCaRL 同时拥有旧类 exemplars，可以在训练时真正重放一部分旧输入。

---

## 七、Algorithm 3 的 Loss 优化

### 1. 新类别输出 Hard Binary Target

对于新类别节点：

$$
y=s,\ldots,t
$$

样本 $(x_i,y_i)$ 的目标是：

$$
r_i^y
=
\mathbf 1[y=y_i]
$$

于是新类部分 BCE：

$$
L_{\text{new}}
=
-
\sum_{(x_i,y_i)\in D}
\sum_{y=s}^{t}
\left[
\mathbf 1[y=y_i]\log g_y(x_i)
+
\mathbf 1[y\neq y_i]
\log(1-g_y(x_i))
\right]
$$

如果：

$$
y_i
$$

是旧类别，那么对所有新类节点：

$$
\mathbf 1[y=y_i]=0
$$

所以旧 exemplar 会直接告诉新类别输出：

> 这张图不是任何一个新类别。

---

### 2. 旧类别输出使用 Distillation Target

对于旧类别：

$$
y=1,\ldots,s-1
$$

目标不是新的 one-hot label，而是更新前保存的：

$$
q_i^y
$$

旧类 distillation loss：

$$
L_{\text{old}}
=
-
\sum_{(x_i,y_i)\in D}
\sum_{y=1}^{s-1}
\left[
q_i^y\log g_y(x_i)
+
(1-q_i^y)
\log(1-g_y(x_i))
\right]
$$

因此完整 loss：

$$
\boxed{
L(\Theta)
=
L_{\text{new}}
+
L_{\text{old}}
}
$$

然后直接使用标准 backpropagation 更新网络。

---

### 4. 网络 Head 的作用

最终 classification 并不用：
$$
\arg\max_y g_y(x)
$$
但训练过程中：
$$
g_y
$$
提供了一个可微的目标，使：
$$
\phi_\Theta
$$
能够通过 backprop 学习：

```text
新类别可分性
+
旧类别判别信息保持
```

所以网络 head 是：

> Representation-learning head，

而不是 iCaRL 最终部署时唯一的 classifier。

---

## 八、Representation 更新完成后再管理 Memory

### 1. 先训练，再缩减旧 Memory

Algorithm 2 首先完整执行：

$$
\text{UPDATEREPRESENTATION}
$$

此时旧类仍然拥有上一个阶段允许的全部 exemplar。只有网络训练完成后，才根据新的类别总数 $t$ 计算 $m=\frac{K}{t}$，实践中需要处理整数取整。

然后旧类：
$$
y=1,\ldots,s-1
$$
执行：
$$
P_y
\leftarrow
(p_1,\ldots,p_m)
$$
也就是只保留前 $m$ 个 exemplar。

---
### 2. 训练前保留旧 Exemplar

假设旧阶段每类还有：

$$
m_{\text{old}}
$$

张 exemplar。

新类别到达后新的 quota：

$$
m_{\text{new}}<m_{\text{old}}
$$

如果先截断再训练，就会提前丢掉本来仍然可以参与本轮 rehearsal 的旧数据。

论文算法选择：

```text
先用当前拥有的全部旧 memory 更新 representation
        ↓
更新完成
        ↓
再为了未来固定预算缩减
```

这样当前这一轮能够最大程度利用已经保存的旧信息。

---

## 九、为新类别构造 Exemplar Lists

### 1. 使用更新后的 Feature Extractor

对于新类别：
$$
y=s,\ldots,t
$$
完整训练数据：
$$
X_y
$$
此时仍然可访问。

先用已经完成本轮 training 的当前：
$$
\phi
$$
计算 class mean：
$$
\mu_y
=
\frac{1}{|X_y|}
\sum_{x\in X_y}
\phi(x)
$$
再开始 herding。

这意味着：

> 新类别 exemplar selection 必须在 Representation Update 之后进行。

如果在训练前选择，得到的 exemplar 是针对旧 feature space 的 class mean，而不是最终准备进入下一阶段的 feature space。

---

### 2. Algorithm 4 的逐步选择

目标数量：

$$
m
$$

第 $k$ 个 exemplar：

$$
p_k
=
\arg\min_{x\in X_y}
\left\|
\mu_y
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

最终：

$$
P_y
=
(p_1,\ldots,p_m)
$$

重点不是每个：

$$
p_k
$$

单独离 class center 最近。

目标是：

> **让前 $k$ 个 exemplar 的平均 feature 尽量逼近完整 class mean。**

所以第二个 exemplar 可能本身离 center 不近，但它可以补偿：

$$
p_1
$$

造成的均值偏差。

---

### 3. Exemplar Set 为 Priority List

论文特别强调：

$$
P_y
$$

严格说不是无序集合，而是：

> prioritized list。

后续 memory quota 减少，只做：

$$
P_y
\leftarrow
(p_1,\ldots,p_m)
$$

不需要：

$$
X_y
$$

重新参与。

这就是 Algorithm 4 与 Algorithm 5 必须配套设计的原因。

---

## 十、旧类别的 Exemplar 不重新 Herding

新一轮 Representation 更新后：

$$
\phi_{\text{old}}
\rightarrow
\phi_{\text{new}}
$$

从纯理论角度看，旧类最优 exemplar subset 也可能发生变化。

但旧类完整训练集：

$$
X_y
$$

已经不可访问。

因此 iCaRL 无法重新计算真正 class mean 并重新执行 Algorithm 4。

对旧类别它只能：

```text
保留原来的 prioritized exemplar list
+
必要时截断
```

然后在 classification 时，把这些**原始图像**重新输入当前：

$$
\phi_{\text{new}}
$$

以更新 prototype。

所以 iCaRL 解决了：

> prototype feature 会随 Representation 更新，

但没有完全解决：

> 原先选中的 exemplar subset 在新 Representation 中是否仍然是最优代表。

论文后续 NCM 对照实验显示，实际差距很小，因此作者认为 exemplar selection 能较可靠地逼近 class mean；但它仍然是算法中的近似。

---

## 十一、最终 Classification 不使用 Network Argmax

### 1. 重新计算每个类别 Prototype

对于每个已见类别：
$$
y=1,\ldots,t
$$
使用当前 feature extractor：
$$
\phi
$$
重新编码：
$$
p\in P_y
$$
计算：

$$
\mu_y
=
\frac{1}{|P_y|}
\sum_{p\in P_y}
\phi(p)
$$

平均后按论文约定继续 L2 normalization。

---

### 2. 查询样本

对测试图像：

$$
x
$$

计算：

$$
z=\phi(x)
$$

最终：

$$
\boxed{
\hat y
=
\arg\min_{y=1,\ldots,t}
\|
\phi(x)-\mu_y
\|_2
}
$$

所以部署时真正需要：

```text
current feature extractor φ
+
raw exemplar images P1...Pt
```

network sigmoid weights：

$$
w_y
$$

仍然属于模型训练状态，但预测类别不通过：
$$
\arg\max_y g_y(x)
$$
产生。

---

### 3. 缓解 Classifier Drift

如果 Representation 发生变化：

$$
\phi_{\text{old}}
\rightarrow
\phi_{\text{new}}
$$

普通旧 weight：

$$
w_y
$$

不会自动因为 feature 位置变化而调整。

但 exemplar prototype：

$$
\mu_y^{\text{new}}
=
\frac{1}{|P_y|}
\sum_{p\in P_y}
\phi_{\text{new}}(p)
$$

会直接随当前 feature extractor 重新计算。所以最终 classifier 与当前 Representation 绑定在一起。

这就是论文 §2.2 认为 mean-of-exemplars 比 network output 更适合 class-incremental prediction 的核心原因。

---

## 十二、系统的组件关系

iCaRL 不是：

```text
Herding
+
Distillation
+
Prototype
```

三个独立技巧的简单堆叠。

它们形成一个循环系统：

```text
当前 φ + 旧 exemplars
        ↓
新类完整数据 + 旧 exemplar rehearsal
        ↓
distillation 保留旧判别行为
        ↓
得到新的 φ
        ↓
旧 raw exemplars 重新映射到新的 feature space
        ↓
prototype 跟随 φ 更新
        ↓
新类别利用新 φ 选择 prioritized exemplars
        ↓
Memory 固定缩减
        ↓
进入下一轮
```

如果删掉其中一个组件，会破坏不同环节。

没有 rehearsal：

> Representation 更新时几乎看不到旧类输入。

没有 distillation：

> 即使有少量 exemplar，旧网络判别结构仍然更容易漂移。

没有 mean-of-exemplars：

> 最终分类重新依赖容易受到增量训练偏置影响的 network outputs。

没有 herding / prioritized list：

> 固定 memory quota 下降时无法在没有旧完整数据的条件下稳定缩减 representative subset。

---

## 十三、内存预算如何随类别数运行

### 1. 固定总预算

论文设置总 exemplar budget：

$$
K
$$

当前类别数：

$$
t
$$

每类 quota：

$$
m=
K/t
$$

因此总 exemplar 数不会超过：

$$
K
$$

---

### 2. 整个系统状态非严格常数

Feature extractor 参数数量固定。Exemplar memory 被 $K$ 限制。但每出现一个类别，还要新增一个$w_y\in\mathbb R^d$，所以 classification head 参数随类别数增长。

论文也明确指出，至少每个类别需要：

- 一个 exemplar；
- 一个 weight vector。

因此在严格固定资源下，能够学习的类别数最终仍然有限。

---

## 十四、实验协议

### 1. Incremental Evaluation

论文先固定类别顺序。

每学习完一个 class batch，就立即在所有目前已经训练过的类别上测试。因此会得到一条$\text{Accuracy}\quad\text{vs}\quad\text{Number of Seen Classes}$ 曲线。

如果需要一个总指标，论文使用：

> average incremental accuracy，

即对各增量阶段得到的 accuracy 求平均。

---

### 2. iCIFAR-100

使用 CIFAR-100 的$100$ 个类别。分别按照每次：
$$
2,\ 5,\ 10,\ 20,\ 50
$$
个新类进行增量训练。

总 exemplar budget：
$$
K=2000
$$
网络：

> 32-layer ResNet。

每个 class batch 训练：

$$
70
$$

epochs。

Learning rate 初始：
$$
2.0
$$
在：
$$
49,\ 63
$$
epochs 后分别除以 5。

---
### 3. iILSVRC

论文使用两个 ImageNet setting。

iILSVRC-small$100$类，每批$10$类。

iILSVRC-full $1000$ 类，每批$100$类。

总 exemplar budget：

$$
K=20000
$$

网络：

> 18-layer ResNet。

每一批训练：

$$
60
$$

epochs。

Learning rate：
$$
2.0
$$

并在：
$$
20,\ 30,\ 40,\ 50
$$
epochs 后分别除以 5。

所有方法使用 batch size：
$$
128
$$
weight decay：
$$
10^{-5}
$$

论文指出 learning rate 看起来较大，作者认为与其采用 binary cross-entropy output 有关；若使用普通 multi-class softmax，可能需要更小学习率。

---

## 十五、主实验对照

论文比较四种方法。

### 1. Finetuning

持续用新数据训练普通 multi-class network。

没有：

- exemplar rehearsal；
- distillation protection；
- prototype classification。

结果是 catastrophic forgetting 最严重。

---

### 2. Fixed Representation

第一批类别之后冻结 feature representation。之后主要训练新增类别的 classifier weights。

它通过：
> 不再改变 Representation

避免忘掉旧 feature。

但代价是：
> 后续类别无法继续塑造 Representation。

论文 Figure 3 显示它反而偏向最早一批类别，因为 Representation 最初就是围绕这些类别学出来的。

---

### 3. LwF.MC

使用 distillation，但：

- 不保存 exemplar；
- 最终用 network outputs 分类。

它比 finetuning 好，但在 class-incremental setting 中明显偏向近期类别。

---

### 4. iCaRL

同时拥有：
```text
exemplar rehearsal
+
distillation
+
nearest-mean-of-exemplars
```

论文 Figure 2 中，iCaRL 在 iCIFAR-100 和 iILSVRC 的大部分增量设置下明显优于其他方法。而且类别 batch 越小，也就是更新次数越多、setting 越“incremental”，iCaRL 相对优势越明显。

---

## 十六、Confusion Matrix

论文 Figure 3 非常重要，因为它展示各方法错误分布不同。

### 1. iCaRL

预测在 $1,\ldots,100$ 各类别上相对均匀。说明没有明显偏向最早或最近类别。

### 2. LwF.MC

更多预测集中在靠后的类别，即：

> 最近加入的 classes。

这说明只做 distillation 的 network classifier 仍会产生明显 recent-class bias。

### 3. Fixed Representation

倾向最早的 class batch。原因是 feature extractor 只在最早阶段学过。

### 4. Finetuning

几乎只输出最后一批类别。这不是普通意义上的“准确率低一点”，而是：

> 模型已经基本忘记早期类别存在。

所以 confusion matrix 把不同机制的失败模式直接暴露出来。

---
## 十七、Differential Analysis

论文 §4.2 构造 hybrid methods，不是只报告 iCaRL 比 baseline 好，而是分别关闭组件。

### 1. Hybrid 1

保留 iCaRL Representation Learning，但用 Network Output 分类

它拥有：

- exemplar rehearsal；
- distillation；

但最终不使用 mean-of-exemplars。

结果在小 class batch，也就是频繁 Representation Update 的条件下明显差于 iCaRL。

这验证：

> Representation 变化越频繁，直接使用 network classifier 越容易出现问题，prototype classifier 的价值越明显。

---

### 2. Hybrid 2

使用 Exemplars 分类，但移除 Distillation

它保留 prototype classifier，但训练时没有旧输出 distillation。

结果显示：

- class batch 很小时，distillation 甚至可能略微伤害 accuracy；
- class batch 较大、update 次数较少时，distillation 明显有帮助。

Table 1a 中，2 classes/batch：
$$
\text{iCaRL}=57.0
$$
而：
$$
\text{hybrid2}=57.6
$$

所以不能简单总结：

> distillation 在 iCaRL 的所有 setting 中都单调提升性能。

更准确的是：

> 整体方法中它通常有保护作用，但贡献随增量粒度变化。

---

### 3. Hybrid 3

Exemplars 只用于 Representation Learning

它不使用：

- distillation；
- exemplar classifier。

但旧 exemplars 仍参加训练。

与没有 exemplar 的 LwF.MC 比较，论文发现 hybrid3 明显更强。

这直接说明：

> rehearsal 本身就是 iCaRL 抵抗 forgetting 的重要来源。

---

### 4. 三个组件不是完全可互换的

Ablation 的结论不是：

> 某一个组件决定全部性能。

论文观察到大部分 hybrid 结果位于 iCaRL 与 LwF.MC 之间。

说明：

```text
prototype classification
+
rehearsal
+
distillation
```

分别解决不同问题。

---
## 十八、Herding 效果分析

### 1. NCM 对照保存全部旧数据

作者使用同一套 iCaRL Representation，但分类时不用 exemplar mean，而是访问所有历史训练数据，在每次 Representation 更新后重新计算真正的：

$$
\mu_y^{\text{NCM}}
=
\frac{1}{|X_y|}
\sum_{x\in X_y}
\phi(x)
$$

这需要保存全部历史数据，因此不再满足论文的 class-incremental resource criterion。

---
### 2. 结果只比 iCaRL 略好

Table 1b 中，两者差距很小。

例如 10 classes/batch：

$$
\text{iCaRL}=64.1
$$

$$
\text{NCM}=64.5
$$

50 classes/batch：

$$
68.6
\quad\text{vs}\quad
68.7
$$

所以论文据此认为：

> herding 选出的少量 exemplar mean 能够较好逼近真实 class mean。

这正是在验证 Algorithm 4，而不仅是在验证“更多 memory 有用”。

---
## 十九、Memory Budget 实验

论文 Figure 4 改变：

$$
K
$$

比较：

- iCaRL；
- NCM；
- hybrid1。

随着：
$$
K
$$
增大，所有方法性能都提高。

原因不止一个。

第一，更多 exemplar 参与 rehearsal：

> Representation Learning 获得更丰富的旧类输入。

第二，iCaRL 的：
$$
\hat\mu_y
$$
会更接近真实 class mean。

当：
$$
K
$$

足够大时，iCaRL 与 NCM 非常接近。

但使用 network output 的 hybrid1 仍明显较差，进一步说明：

> 仅靠更好的 Representation 还不足以解释 iCaRL 的性能，最终 prototype classification 本身也很重要。

---

## 二十、资源边界与方法局限

### 1. 性能仍低于 Batch Training

论文明确指出 iCaRL 仍没有追上：

> 所有类别数据同时可访问的 batch training。

因此 iCaRL 证明的是：

> 在受限 historical memory 下大幅改善 CIL，

不是证明 incremental learning 已经没有性能代价。

---
### 2. 依赖 Raw Exemplars

最强性能的重要来源之一就是保存 exemplar images。

这带来：

- memory；
- privacy；
- data retention policy；

等问题。

论文结论也把：

> 不能存 raw training data

作为后续需要研究的场景。

---
### 3. 每类 Memory 不断缩小

固定：

$$
K
$$

下：

$$
m=K/t
$$

所以类别数不断增加时，每类 representativeness 必然下降。

这会同时影响：

- rehearsal；
- prototype estimation。

---
### 4. 旧 Exemplar Selection 无法随 Representation 完全重做

旧完整：
$$
X_y
$$

已经不存在。

因此 Representation 变化后只能重新编码已经选择的：
$$
P_y
$$
不能重新执行全数据 herding。

这意味着 exemplar list 是：

> 在它第一次被选择时那个 Representation 下构造的历史压缩。

---

### 5. Head 仍随类别数增长

即使 exemplar 总量固定，weight vectors：
$$
w_1,\ldots,w_t
$$
仍会随着类别数增加。所以系统不是绝对 constant-memory。

---

## 二十一、逻辑状态机

从实现角度，iCaRL 可以压缩成以下循环：

```text
初始化：
Θ
P = empty
K = fixed memory budget

        ↓

新 class batch X_s...X_t 到达

        ↓

扩展 network outputs
加入新 class nodes

        ↓

构造训练集 D：

全部新类数据
+
当前全部旧 exemplars

        ↓

用更新前 Θ
对 D 中所有样本记录
旧类 outputs q_i^y

        ↓

训练 Θ：

new classes
→ hard BCE targets

old classes
→ distillation soft targets

        ↓

得到新的 Representation φ

        ↓

m = floor(K / t)

        ↓

旧类别：
P_y 截断为前 m 个

        ↓

新类别：
在当前 φ 下计算完整 class mean

        ↓

逐步 herding
得到 ordered exemplar list
P_y=(p_1,...,p_m)

        ↓

更新系统状态：
Θ + P_1...P_t

        ↓

测试时：

每个类别
用当前 φ 重新编码 exemplars
        ↓
得到 prototype μ_y

query x
↓
φ(x)
↓
nearest μ_y
↓
prediction
```

下一批类别到来后重复整个循环。