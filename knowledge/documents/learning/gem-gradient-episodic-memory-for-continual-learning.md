---
schema_version: 1
id: gem-gradient-episodic-memory-for-continual-learning
title: GEM：Gradient Episodic Memory for Continual Learning 论文精读笔记
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

# GEM：Gradient Episodic Memory for Continual Learning 论文精读笔记

> 论文：David Lopez-Paz, Marc'Aurelio Ranzato, *Gradient Episodic Memory for Continual Learning*, NeurIPS 2017  
> 本笔记默认已经掌握《GEM 前置知识：从 SGD 更新到梯度约束与二次规划》中的 Gradient Conflict、Taylor 一阶近似、Projection、QP、Dual 与 KKT 基础，因此不重复推导这些内容。这里重点回答：**GEM 在论文里到底定义了什么持续学习问题，训练时每一步怎么做，episodic memory 怎样参与更新，实验如何设计，以及结果真正验证了什么。**

## 一、论文研究的问题不是普通 Batch Training

### 1. 传统 ERM 的前提

普通监督学习通常假设训练集：

$$
D_{\text{tr}}
=
\{(x_i,y_i)\}_{i=1}^{n}
$$

来自一个固定分布：

$$
P(X,Y)
$$

并且训练样本近似满足 iid。

模型：

$$
f_\theta
$$

通过最小化经验风险：

$$
\frac{1}{|D_{\text{tr}}|}
\sum_{(x_i,y_i)\in D_{\text{tr}}}
\ell(f_\theta(x_i),y_i)
$$

完成训练。

这种训练方式隐含了几个条件：

```text
训练数据整体可访问
        ↓
可以反复 shuffle
        ↓
可以多次遍历同一批数据
        ↓
每个 mini-batch 都近似来自同一固定数据分布
```

GEM 论文认为，持续学习恰好破坏了这些条件。

---

### 2. GEM 研究的数据流

论文把持续学习数据写成：

$$
(x_1,t_1,y_1),
\ldots,
(x_i,t_i,y_i),
\ldots,
(x_n,t_n,y_n)
$$

其中：

- $x_i$：输入；
- $y_i$：监督目标；
- $t_i$：task descriptor，标识当前样本属于哪个任务。

一个任务内部的数据可以近似看成来自：

$$
P_t(X,Y)
$$

但整个数据流不是从某一个固定：

$$
P(X,T,Y)
$$

iid 采样。

原因是实际数据顺序更接近：

```text
Task 1 的一段样本
        ↓
Task 2 的一段样本
        ↓
Task 3 的一段样本
        ↓
……
```

所以任务切换时，输入分布和目标函数都会发生结构性变化。

论文重点强调三类问题：

1. **Non-iid input**：整体训练流不是固定分布上的 iid 数据；
2. **Catastrophic Forgetting**：学习新任务会破坏过去任务；
3. **Transfer**：不同任务如果相关，学习一个任务也可能帮助其他任务。

GEM 不是只想做到“旧任务别掉分”，它还希望保留：

> 学新任务以后，旧任务反而变好的可能性。

这也是它后面只禁止旧任务 Loss 增大、而不要求旧行为完全不变的原因。

---

## 二、GEM 的任务设定与模型接口

### 1. Predictor 显式接收 Task Descriptor

论文把预测器写成：

$$
f_\theta:X\times T\rightarrow Y
$$

测试时输入：

$$
(x,t)
$$

输出对应任务的预测：

$$
\hat y=f_\theta(x,t)
$$

因此 GEM 原论文的正式框架里：

> **测试时可以知道 task descriptor。**

最简单的 task descriptor 就是整数：

$$
t=1,2,\ldots,T
$$

它告诉模型当前需要解决哪一个任务。

---

### 2. Task Descriptor 可以做什么

论文指出，更一般的 $t$ 不一定只是整数，也可以是结构化信息，例如描述任务的文本。

如果 task descriptor 本身包含任务间关系，理论上可能帮助：

> 在还没有看到某个任务训练样本以前，就利用已有知识进行 zero-shot transfer。

但本文没有深入利用这种结构。

实验中主要使用：

> 简单的整数 task ID。

因此论文也明确说明：

> 使用这种简单 task descriptor 时，不应期待很强的 zero-shot Forward Transfer。

---

### 3. 与 iCaRL 的 Setting 不同

前面 iCaRL 重点研究 Class-Incremental Learning：

```text
测试输入 x
        ↓
通常不给 Task ID
        ↓
必须在全部已见类别中直接统一分类
```

GEM 论文中则允许：

```text
测试输入 x
+
Task ID t
        ↓
预测该 Task 对应输出
```

尤其在 CIFAR-100 实验中，论文直接为不同 task 配置 task-specific final linear classifier。

所以虽然论文使用了“Incremental CIFAR100”，但它的 GEM 实验协议不能简单等同于 iCaRL 原论文那种严格无 Task-ID 的统一 Class-Incremental Classification。

---

## 三、GEM 要维护的系统状态

假设当前正在学习任务：

$$
t
$$

此时系统主要需要：

### 1. 当前模型参数

$$
\theta
$$

这是一套在所有任务之间持续更新的共享模型参数。

---

### 2. 每个已见任务的 Episodic Memory

对于任务：

$$
k
$$

保存：

$$
M_k
$$

其中存放这个任务过去见过的一小部分样本：

$$
(x_i,k,y_i)
$$

所以 GEM 的历史状态可以粗略理解成：

$$
S_t
=
\left(
\theta,
M_1,M_2,\ldots,M_t
\right)
$$

与 EWC 不同，GEM 不需要为旧任务保存：

$$
F_k
$$

也不要求保存旧模型副本。

它保存的是：

> 少量过去样本。

然后每一次更新时重新从这些 memory samples 计算旧任务当前梯度。

---

## 四、Episodic Memory 的具体管理方式

### 1. 总内存预算

论文假设总共有：

$$
M
$$

个 memory locations。

如果任务总数：

$$
T
$$

提前已知，则每个任务可以平均分配：

$$
m=\frac{M}{T}
$$

个 memory slots。

即：

$$
|M_k|
\le m
$$

---

### 2. 如果任务总数未知

如果事先不知道最终会有多少任务，论文建议随着新任务不断出现，逐渐降低每个任务的：

$$
m
$$

这和 iCaRL 的固定总内存预算思路类似：

```text
新 Task 不断增加
        ↓
总 Memory 固定
        ↓
每个 Task 平均能占用的 Memory 下降
```

不过 GEM 论文没有重点研究复杂 memory management。

---

### 3. 论文实验采用的简单策略

为了把研究重点放在 Gradient Constraint 本身，论文使用很简单的 memory population 策略：

> 每个任务保存最后 $m$ 个样本。

作者明确指出，也可以使用更高级的策略，例如：

> 为每个任务构建 coreset。

但这些方法没有在本文中深入研究。

因此不能把 GEM 的主要贡献理解成：

> 提出了一套先进的 exemplar selection。

它真正的贡献在于：

> **怎样使用 episodic memory 产生约束，而不是怎样挑 memory。**

---

### 4. Algorithm 1 与 Memory Budget 的关系

论文 Algorithm 1 中简化写成：

```text
M_t ← M_t ∪ (x,y)
```

也就是当前样本不断加入当前任务 memory。

但正文已经提前设定：

$$
|M_t|\le m
$$

并说明实际只保留最后 $m$ 个样本。

因此实现时不能把伪代码里的 union 理解成：

> memory 无限增长。

更准确的理解是：

```text
新样本到来
        ↓
加入当前 Task Memory
        ↓
如果超过当前 quota m
        ↓
按照 Memory Policy 删除旧元素
```

原论文默认的 policy 是保留最近的 $m$ 个。

---

## 五、旧任务 Memory 在 GEM 中不是普通 Replay Loss

### 1. 先定义旧任务 Memory Loss

对过去任务：

$$
k<t
$$

定义：

$$
L_k^M(\theta)
=
\frac{1}{|M_k|}
\sum_{(x_i,k,y_i)\in M_k}
\ell(f_\theta(x_i,k),y_i)
$$

它衡量当前模型：

$$
f_\theta
$$

在任务 $k$ 的 episodic memory 上表现如何。

---

### 2. GEM 没有直接最小化所有旧 Memory Loss 的加权和

一种普通 replay 写法是：

$$
L_{\text{total}}
=
L_t
+
\lambda
\sum_{k<t}
L_k^M
$$

但 GEM 没有采用这种形式。

论文认为，如果直接把 memory samples 与当前样本一起优化，模型可能会：

> 过拟合有限 memory。

而如果像 distillation 那样强制过去预测保持不变，又会限制：

> Positive Backward Transfer。

因此 GEM 的设计是：

> 不要求旧任务必须继续下降，也不要求输出完全不变；只要求旧任务 memory loss **不能上升**。

---

## 六、论文真正优化的约束问题

当前观测到：

$$
(x,t,y)
$$

时，GEM 希望优化：

$$
\min_\theta
\ell(f_\theta(x,t),y)
$$

subject to：

$$
L_k^M(\theta)
\le
L_k^M(\theta^{t-1}),
\qquad
\forall k<t
$$

其中：

$$
\theta^{t-1}
$$

表示学习当前任务之前、上一个任务结束时的模型状态。

这句话的语义是：

```text
当前任务：
尽量把当前 Loss 降低

旧任务：
只设置底线

当前更新以后，
旧 Task k 在其 Memory 上的 Loss
不能比原来更差
```

因此 GEM 的约束是**单边约束**。

允许：

$$
L_k^M(\theta)
<
L_k^M(\theta^{t-1})
$$

也就是旧任务性能继续改善。

---

## 七、从论文目标到每次 Update 的实际执行

前置笔记已经完整推导：

$$
g_k^Tg\ge0
$$

为什么是一阶意义上的“当前更新不伤害旧任务”条件，这里只看它在论文算法中怎样使用。

### 1. 当前样本产生 Current Gradient

对于当前任务：

$$
t
$$

的当前样本：

$$
(x,y)
$$

计算：

$$
g
=
\nabla_\theta
\ell(f_\theta(x,t),y)
$$

它是当前任务希望执行的原始 gradient。

---

### 2. 每个旧任务 Memory 分别产生一个 Gradient

对所有：

$$
k<t
$$

计算：

$$
g_k
=
\nabla_\theta
L_k^M(\theta)
$$

所以如果当前是任务：

$$
t
$$

已经有：

$$
t-1
$$

组过去梯度：

$$
g_1,\ldots,g_{t-1}
$$

---

### 3. 判断 Current Gradient 是否伤害过去任务

检查：

$$
g^Tg_k
\ge
0,
\qquad
\forall k<t
$$

如果全部成立：

```text
当前 Gradient
已经满足所有历史 Task Constraint
        ↓
不需要修改
```

所以：

$$
\tilde g=g
$$

---

### 4. 如果有冲突，则执行 Projection

如果存在某个：

$$
k
$$

满足：

$$
g^Tg_k<0
$$

则需要把 $g$ 投影到满足所有旧任务约束的最近方向：

$$
\tilde g
=
\operatorname{PROJECT}
(g,g_1,\ldots,g_{t-1})
$$

Dual QP 的推导在前置笔记已经说明。

论文最终通过低维 dual problem 求出：

$$
v^*
$$

然后恢复：

$$
\tilde g
=
G^Tv^*+g
$$

---

### 5. 用 Projected Gradient 更新参数

最后执行：

$$
\theta
\leftarrow
\theta-\alpha\tilde g
$$

注意这里 optimizer 真正使用的是：

$$
\tilde g
$$

而不是原始：

$$
g
$$

所以 GEM 的核心干预发生在：

```text
Backward
  ↓
得到 Current Gradient g
  ↓
得到 Past Gradients g_k
  ↓
检查 Constraint
  ↓
必要时 Project
  ↓
得到 \tilde g
  ↓
Parameter Update
```

而不是通过给 Loss 增加一个固定正则项间接改变梯度。

---

## 八、Algorithm 1 的完整训练状态机

论文 Algorithm 1 可以按实现逻辑重新写成：

```text
初始化：

每个任务的 Memory：
M_1,...,M_T ← empty

Evaluation Matrix：
R ← 0


Task t 到达
        ↓
依次读取这个 Task 的训练样本
        ↓

对于每个当前样本 (x,y)：

1. 把 (x,y) 放入 M_t
   并遵守 memory quota

2. Current Task Forward
        ↓
   计算当前 Loss

3. Backward
        ↓
   得到 current gradient g

4. 对每个旧任务 k<t：

   从 M_k 计算旧任务 memory loss
        ↓
   backward
        ↓
   得到 g_k

5. 检查：
   g^T g_k ≥ 0 ?

6. 如果都满足：
   \tilde g = g

   如果存在冲突：
   求 QP projection
        ↓
   得到 \tilde g

7. 参数更新：

   θ ← θ - α \tilde g

        ↓
继续下一个当前任务样本


Task t 全部训练数据结束
        ↓
在所有 T 个测试任务上评估
        ↓
把结果写入 R 的第 t 行
```

然后进入：

$$
t+1
$$

继续。

---

## 九、为什么 GEM 允许 Positive Backward Transfer

这是 GEM 相比“只冻结旧行为”的方法一个很重要的设计点。

### 1. Distillation 更强调保持

如果要求：

$$
f_{\text{new}}(x)
\approx
f_{\text{old}}(x)
$$

那么本质上是在限制旧模型行为变化。

这种设计擅长：

> 防止旧功能漂移。

但也可能限制：

> 新任务知识反过来改善旧任务。

---

### 2. GEM 只限制旧 Loss 不能增大

GEM 的约束是：

$$
L_k^{M,\text{new}}
\le
L_k^{M,\text{old}}
$$

所以：

$$
L_k^{M,\text{new}}
<
L_k^{M,\text{old}}
$$

完全合法。

因此如果新任务学习到的共享 Representation 对旧任务也有用：

```text
学 Current Task
        ↓
共享参数发生变化
        ↓
Past Task Memory Loss 反而下降
```

GEM 不会阻止这种更新。

---

### 3. $\gamma$ 的作用

论文在求出 dual solution：

$$
v^*
$$

后，还实验性地给：

$$
v^*
$$

增加一个小的：

$$
\gamma\ge0
$$

以偏置 projection，使更新更倾向于：

> beneficial backward transfer。

这不是 GEM 基本约束成立所必需的理论条件，而是论文实际实现中的一个额外超参数。

Appendix 的 hyperparameter search 中：

$$
\gamma
$$

搜索范围为：

$$
0.0,0.1,\ldots,1.0
$$

最终三个主要数据集都选用了：

$$
\gamma=0.5
$$

---

## 十、论文提出的 Continual Learning 评估矩阵

GEM 论文不满足于只报告：

> 最后所有任务的平均准确率。

因为两个模型最终 accuracy 相同，学习过程可能完全不同。

因此论文构造：

$$
R\in\mathbb R^{T\times T}
$$

其中：

$$
R_{i,j}
$$

表示：

> **刚刚学习完任务 $i$ 后，模型在任务 $j$ 测试集上的准确率。**

因此矩阵结构为：

```text
             测试 Task
          1    2    3   ...   T

学完 1   R11  R12  R13  ...  R1T
学完 2   R21  R22  R23  ...  R2T
学完 3   R31  R32  R33  ...  R3T
...
学完 T   RT1  RT2  RT3  ...  RTT
```

对角线：

$$
R_{i,i}
$$

表示任务 $i$ 刚学完时自己的性能。

最后一行：

$$
R_{T,:}
$$

表示全部任务学习结束后的最终性能。

---

## 十一、Average Accuracy、BWT 与 FWT

### 1. Average Accuracy

全部任务结束后：

$$
\mathrm{ACC}
=
\frac{1}{T}
\sum_{i=1}^{T}
R_{T,i}
$$

它回答：

> 最终模型对所有任务的平均性能是多少？

---

### 2. Backward Transfer

定义：

$$
\mathrm{BWT}
=
\frac{1}{T-1}
\sum_{i=1}^{T-1}
\left(
R_{T,i}-R_{i,i}
\right)
$$

每一项比较：

```text
Task i 刚学完时：
R_{i,i}

全部后续任务都学完以后：
R_{T,i}
```

如果：

$$
R_{T,i}<R_{i,i}
$$

则旧任务变差。

如果：

$$
R_{T,i}>R_{i,i}
$$

则旧任务在学习后续任务后反而提升。

因此：

- $\mathrm{BWT}<0$：平均存在 forgetting；
- $\mathrm{BWT}\approx0$：旧任务大体保持；
- $\mathrm{BWT}>0$：存在 positive backward transfer。

所以 catastrophic forgetting 可以视为：

> 强烈的 negative BWT。

---

### 3. Forward Transfer

设：

$$
\bar b_i
$$

为模型随机初始化时，在任务 $i$ 上的 baseline performance。

论文定义：

$$
\mathrm{FWT}
=
\frac{1}{T-1}
\sum_{i=2}^{T}
\left(
R_{i-1,i}
-
\bar b_i
\right)
$$

这里：

$$
R_{i-1,i}
$$

表示：

> 在正式学习任务 $i$ **之前**，模型已经学习完前 $i-1$ 个任务时，对任务 $i$ 的表现。

所以 FWT 衡量：

> 过去任务学到的知识，是否让模型在未来任务尚未训练时就表现得比随机初始化更好。

如果 task descriptor 只是整数，模型没有未来任务结构信息，一般很难期待很强 zero-shot FWT。

---

## 十二、实验一：MNIST Permutations

### 1. 数据集本身是什么

原始 MNIST 是：

> 28×28 灰度手写数字分类数据集。

类别是：

$$
0,1,\ldots,9
$$

GEM 构造 MNIST Permutations 时，为每个任务生成一套固定 pixel permutation。

即：

```text
原图 28×28
        ↓
flatten / 按固定 permutation 重排像素
        ↓
仍然分类 0~9
```

不同 task 使用不同 permutation。

---

### 2. 为什么它适合 Continual Learning 实验

每个 task 内部：

> 所有图像使用同一套 permutation。

所以 task 内部仍然可以学习稳定映射。

但不同 task：

> pixel positions 被完全不同地重排。

因此论文认为这些任务之间的：

> input distribution 近似不相关。

也就是说，它是一个任务差异很大的 continual-learning setting。

---

### 3. 任务规模

论文统一使用：

$$
T=20
$$

个任务。

MNIST Permutations 中，每个 task 有：

$$
1000
$$

个训练样本。

每个 task 都仍然包含：

$$
10
$$

个数字类别。

---

### 4. 网络结构

MNIST 实验使用 fully-connected network：

```text
Input
 ↓
Hidden Layer
100 ReLU units
 ↓
Hidden Layer
100 ReLU units
 ↓
Output
```

因此没有使用 CNN。

---

### 5. 这个实验主要测试什么

因为不同 permutation 的输入结构差别很大，它主要测试：

> 当不同 task 需要截然不同的输入映射时，共享参数能否避免严重 interference。

---

## 十三、实验二：MNIST Rotations

### 1. 数据集构造

仍然从 MNIST 开始。

但不是随机置换像素，而是为每个任务固定一个旋转角度：

$$
\alpha_t
\in
[0^\circ,180^\circ]
$$

例如不同任务看到：

```text
0° 的数字
10° 的数字
30° 的数字
...
```

每个任务内部角度固定。

---

### 2. 与 Permutations 的关键区别

MNIST Permutations：

> 不同 task 的输入空间关系很弱。

MNIST Rotations：

> 不同 task 仍然是相同数字，只是视觉方向逐渐变化。

因此不同 rotation task 的数据分布更相关。

这意味着：

> 任务之间更可能发生有益 transfer。

所以它特别适合观察：

- FWT；
- BWT；
- GEM 是否能利用共享 Representation。

---

### 3. 任务规模与网络

同样：

$$
T=20
$$

每个 task：

$$
1000
$$

个训练样本。

类别仍然是全部：

$$
0,\ldots,9
$$

网络仍然是：

> 两层、每层 100 个 ReLU hidden units 的 fully-connected network。

---

## 十四、实验三：Incremental CIFAR-100

### 1. CIFAR-100 是什么

CIFAR-100 是彩色自然图像分类数据集。

共有：

$$
100
$$

个类别。

图像大小为：

$$
32\times32
$$

论文把 100 个类别分割成多个互不重叠的任务。

---

### 2. 本文怎样构造 20 个任务

论文设置：

$$
T=20
$$

所以每个任务包含：

$$
\frac{100}{20}=5
$$

个类别。

即：

```text
Task 1：
5 个类别

Task 2：
另外 5 个类别

...

Task 20：
最后 5 个类别
```

不同任务的类别集合完全不重叠。

每个任务有：

$$
2500
$$

个训练样本。

---

### 3. 和 MNIST 两组实验的区别

这里不同任务看到的仍然都是：

> CIFAR 自然图像。

所以论文认为：

> input representation 在不同任务间较相似。

但是每个任务需要区分不同的 5 个类别，因此：

> output distribution 不同。

---

### 4. 它不是纯 iCaRL 式统一 Class-Incremental Head

论文在 CIFAR-100 上为：

> 每个任务配置一个独立 final linear classifier。

所以 task descriptor：

$$
t
$$

可以告诉模型：

> 当前应该调用哪个 task-specific head。

因此这里虽然类别按批次递增，但测试协议仍使用 task identity。

这个区别很重要，因为它降低了：

> 不知道当前样本属于哪个 task 时，所有 100 类直接竞争

这一额外难度。

---

### 5. 网络结构

CIFAR-100 使用：

> 一个缩小版 ResNet-18。

论文把所有 layer 的 feature maps 数量减少到标准 ResNet-18 的约：

$$
\frac13
$$

同时每个 task 有自己的：

> final linear classifier。

共享主体仍然负责学习跨任务 Representation。

---

## 十五、统一训练设置

### 1. 数据只看一次

论文强调其主要 continual-learning protocol 是：

> 每个训练样本只观察一次。

也就是单遍 streaming learning。

---

### 2. Mini-batch

所有模型使用 plain SGD。

Mini-batch size：

$$
10
$$

---

### 3. 超参数

所有方法都使用 grid-search 选择最佳 hyperparameters。

GEM 主要搜索：

- learning rate；
- memory size；
- $\gamma$。

Appendix 最终报告主要实验中：

$$
\text{learning rate}=0.1
$$

$$
\text{memory size}=5120
$$

$$
\gamma=0.5
$$

适用于三个主要数据集的最佳设置。

---

## 十六、论文比较的 Baselines

### 1. Single

使用一个 predictor 连续训练所有任务。

没有特殊 continual-learning protection。

它代表：

> 直接把普通 SGD 用到 task sequence 上。

主要用于观察 catastrophic forgetting。

---

### 2. Independent

每个 task 都训练一个独立 predictor。

每个网络的 hidden units 数量缩小，使总容量与 single predictor 可比较。

新 predictor 可以：

- 随机初始化；
- 或 clone 上一个 task predictor 再 fine-tune。

具体选择由 grid-search 决定。

这种方法几乎不会发生：

> 旧任务参数被新任务修改。

所以 BWT 可以接近 0。

但缺点是：

> task 之间共享与 transfer 能力很弱。

---

### 3. Multimodal

仅用于 MNIST。

它与 single 共用大部分结构，但：

> 每个 task 有独立 input layer。

这种设计特别适合 MNIST task，因为不同 permutation / rotation 主要改变输入映射。

它允许：

```text
Task-specific Input Adapter
+
Shared Higher Layers
```

所以是一个很强的结构化 baseline。

---

### 4. EWC

使用 parameter regularization 减少 catastrophic forgetting。

在这里主要作为：

> Parameter-importance continual learning

的代表。

---

### 5. iCaRL

只在 CIFAR-100 上比较。

论文指出 iCaRL 要求：

> 不同任务共享相同 input representation。

所以没有用于 MNIST Permutations / Rotations 的对比。

它作为：

> episodic-memory + exemplar-based continual learning

的代表。

---

## 十七、MNIST Permutations 的主要结果

Appendix 给出的最终结果：

| 方法 | ACC | BWT | FWT |
| --- | ---: | ---: | ---: |
| Single | 0.6018 | -0.1980 | 0.0093 |
| Independent | 0.4523 | 0.0000 | 0.0000 |
| Multimodal | 0.7561 | -0.0275 | 0.0059 |
| EWC | 0.6185 | -0.1653 | 0.0054 |
| GEM | **0.8260** | **+0.0247** | 0.0088 |

### 1. Single

BWT：

$$
-0.1980
$$

说明直接连续训练后，过去任务平均性能明显下降。

这就是标准 catastrophic forgetting。

---

### 2. Independent

BWT：

$$
0
$$

因为不同任务模型彼此独立。

但 ACC 只有：

$$
0.4523
$$

说明：

> 完全隔离任务虽然不忘，但无法有效利用有限共享容量与任务之间可能存在的知识。

---

### 3. Multimodal

ACC：

$$
0.7561
$$

明显强于 Single 和 EWC。

这说明 task-specific input layer 对 permutation task 很合适。

---

### 4. GEM

GEM：

$$
\mathrm{ACC}=0.8260
$$

同时：

$$
\mathrm{BWT}=+0.0247
$$

即平均而言，模型学习后续任务后，早期任务性能并没有下降，反而略有提升。

这正是论文希望展示的：

> GEM 不只是减少 forgetting，还允许 positive backward transfer。

---

## 十八、MNIST Rotations 的主要结果

Appendix 最终结果：

| 方法 | ACC | BWT | FWT |
| --- | ---: | ---: | ---: |
| Single | 0.5307 | -0.0896 | 0.4254 |
| Independent | 0.6241 | 0.0000 | 0.0000 |
| Multimodal | 0.7585 | -0.0243 | 0.0177 |
| EWC | 0.5461 | -0.2047 | 0.5524 |
| GEM | **0.8607** | **+0.0048** | **0.6647** |

### 1. 为什么这里 FWT 明显更高

Rotation tasks 之间具有连续视觉相关性。

学会某些角度后：

> 即使还没有正式训练未来旋转角度，模型的 Representation 也可能已经具有一定泛化能力。

所以这里各共享模型的 FWT 明显高于 Permutations。

---

### 2. GEM 的表现

GEM：

$$
\mathrm{ACC}=0.8607
$$

明显最高。

同时：

$$
\mathrm{BWT}=+0.0048
$$

接近零且略为正。

FWT：

$$
0.6647
$$

也是表中最高。

所以这个数据集最能体现 GEM 想同时处理的两件事：

```text
Backward：
后续任务不要破坏旧任务

Forward：
过去学到的 Representation
帮助未来相关任务
```

---

## 十九、CIFAR-100 的主要结果

Appendix 最终结果：

| 方法 | ACC | BWT | FWT |
| --- | ---: | ---: | ---: |
| Single | 0.4631 | -0.1226 | -0.0006 |
| Independent | 0.4235 | 0.0000 | 0.0000 |
| iCaRL | 0.5462 | -0.0830 | 0.0000 |
| EWC | 0.4984 | -0.0799 | -0.0077 |
| GEM | **0.6783** | **+0.0042** | -0.0078 |

### 1. 这个实验比 MNIST 更接近复杂视觉学习

模型不再是小型 fully-connected network，而是 ResNet-style convolutional network。

输入是自然图像。

因此它用于验证：

> GEM 能否扩展到更复杂的视觉 Representation Learning。

---

### 2. GEM 的 BWT

GEM：

$$
\mathrm{BWT}=+0.0042
$$

仍然接近零且略为正。

论文 Figure 1 右侧还专门展示：

> 随着越来越多 task 被学习，Task 1 的 accuracy 如何变化。

在 CIFAR-100 上 GEM 出现了明显的：

> Positive Backward Transfer。

---

### 3. 与 iCaRL 的比较要注意 Setting

论文结果中：

$$
\mathrm{ACC}_{\text{GEM}}
=
0.6783
$$

高于：

$$
\mathrm{ACC}_{\text{iCaRL}}
=
0.5462
$$

但不能脱离本文 protocol 直接把它理解成：

> GEM 在所有 Class-Incremental Setting 下都优于 iCaRL。

因为本文 GEM 使用 task descriptor / task-specific classifier 的实验协议，与 iCaRL 原论文的严格统一分类设定并不完全一致。

这里能支持的结论是：

> 在 GEM 论文定义的 CIFAR-100 continual-learning protocol 下，GEM 的最终 ACC 和 BWT 优于作者实现的 iCaRL baseline。

---

## 二十、Memory Size 实验

论文 Table 2 在 CIFAR-100 上比较不同 episodic memory size：

| Memory Size | 200 | 1280 | 2560 | 5120 |
| --- | ---: | ---: | ---: | ---: |
| GEM ACC | 0.487 | 0.579 | 0.633 | 0.654 |
| iCaRL ACC | 0.436 | 0.494 | 0.500 | 0.508 |

可以看到：

$$
M\uparrow
\Rightarrow
\mathrm{ACC}\uparrow
$$

对 GEM 很明显。

---

### 1. 为什么 Memory 越大通常越好

GEM 用：

$$
M_k
$$

估计旧任务 gradient：

$$
g_k
$$

memory 越大：

```text
对旧任务分布覆盖更充分
        ↓
Past Gradient Estimate 更可靠
        ↓
Gradient Constraint 更能代表真实旧任务
```

因此这个实验实际上验证的是：

> GEM 对 memory representativeness 的依赖。

---

### 2. 它并不意味着 Memory 可以无限增加

GEM 研究的仍然是有限 memory continual learning。

Table 2 只是说明：

> 给更多 episodic memory，性能会持续改善。

而不是把 GEM 变成“保存全部历史数据”。

---

## 二十一、为什么论文还研究每个 Task 多训练几遍

主实验规定：

> 每个样本只看一次。

但作者进一步提出：

> 如果每个 Task 反复训练多轮，catastrophic forgetting 会怎样？

MNIST Rotations 上结果如下。

| 方法 | 1 epoch ACC/BWT | 2 epochs ACC/BWT | 5 epochs ACC/BWT |
| --- | --- | --- | --- |
| Single, shuffled iid | 0.83 / -0.00 | 0.87 / -0.00 | 0.89 / -0.00 |
| Single | 0.53 / -0.08 | 0.49 / -0.25 | 0.43 / -0.40 |
| Independent | 0.56 / -0.00 | 0.64 / -0.00 | 0.67 / -0.00 |
| Multimodal | 0.76 / -0.02 | 0.72 / -0.11 | 0.59 / -0.28 |
| EWC | 0.55 / -0.19 | 0.59 / -0.17 | 0.61 / -0.11 |
| GEM | 0.86 / +0.05 | 0.88 / +0.02 | 0.89 / -0.02 |

---

### 1. Single 为什么越训练越差

当当前 Task 被反复优化：

```text
当前 Task Gradient
反复推动参数适配当前分布
        ↓
参数越来越远离过去 Task 的解
        ↓
过去 Task Forgetting 更严重
```

因此 Single 的 BWT：

$$
-0.08
\rightarrow
-0.25
\rightarrow
-0.40
$$

持续恶化。

---

### 2. GEM 为什么能利用更多训练轮数

GEM 每次更新都重新检查旧任务 constraint。

所以更多当前任务优化步骤并不等于：

> 无限制地朝当前任务方向移动。

在 5 epochs 时：

$$
\mathrm{ACC}=0.89
$$

已经接近：

> 把所有 task 数据打乱后做 iid training

得到的：

$$
0.89
$$

论文因此把 iid shuffled training 视作该实验里的 oracle-style performance upper bound。

需要注意：

> 这是这个具体实验 protocol 中的经验性上界参照，不是 GEM 的严格理论 upper bound。

---

## 二十二、计算复杂度与真正的瓶颈

### 1. Dual QP 本身不是最大问题

论文指出 GEM 通过 dual formulation，把 QP variable 数从：

$$
p
$$

降到：

$$
t-1
$$

所以 projection optimization 本身只与已见任务数量有关，而不是直接在百万级参数空间中优化 QP。

---

### 2. 真正昂贵的是 Past-task Backward

每个训练 iteration：

```text
Current Task
→ 1 次 gradient

每个 Past Task
→ 都需要从 M_k 再算 1 次 gradient
```

因此当过去任务数为：

$$
t-1
$$

时，需要大量额外 backward。

论文明确把这一点列为 GEM 的主要瓶颈：

> 每次 iteration 需要对每一个过去任务计算一次 backward pass。

所以任务数增加时：

$$
\text{Computation}
\uparrow
$$

---

### 3. 论文中的训练时间

MNIST CPU 训练时间表：

| 方法 | Permutations | Rotations |
| --- | ---: | ---: |
| Single | 11 s | 11 s |
| Independent | 11 s | 16 s |
| Multimodal | 14 s | 13 s |
| EWC | 179 s | 169 s |
| GEM | 77 s | 135 s |

在作者当时的实现和实验环境中，GEM 比 EWC 更快。

但论文同时强调：

> GEM 的核心计算瓶颈仍然是每一步都计算历史任务梯度。

因此不能把这些 2017 年具体 CPU 秒数当成一般性的现代硬件结论。

---

## 二十三、Figure 1 应该怎么看

论文第 6 页 Figure 1 左侧分别画出三个数据集上的：

- ACC；
- BWT；
- FWT。

右侧则追踪：

> Task 1 的 test accuracy 随着后续 Task 2、3、...、20 被学习时如何变化。

所以 Figure 1 的右半部分实际上是在直接可视化：

$$
R_{1,1},
R_{2,1},
R_{3,1},
\ldots,
R_{T,1}
$$

如果曲线不断下降：

> catastrophic forgetting。

如果基本水平：

> old task retained。

如果反而上升：

> positive backward transfer。

GEM 的曲线在三组数据中都明显比普通 sequential training 更稳定。

---

## 二十四、论文的 Causal Compression 解释

论文还提供了一个额外视角：

> GEM 可以被看作在多个 task distribution 之间寻找共同 correlations。

如果某些特征关系在多个 task / environment 中都成立，那么这种关系更可能具有跨环境稳定性。

作者把这种跨任务稳定预测与：

> causal invariance

联系起来，并称其为一种：

> causal compression view。

但需要注意：

- 这不是 GEM 核心算法推导的必要部分；
- 论文没有围绕它展开独立的因果识别实验；
- GEM 的主要实验证据仍然是 continual-learning performance。

所以读论文时可以把这一段理解成：

> 作者对“为什么跨任务共享可能学到更稳定结构”的理论直觉，

而不是 GEM 已经完成了严格 causal inference。

---

## 二十五、与 EWC 和 iCaRL 的核心差别

### 1. EWC

保存：

$$
\theta_k^*
+
F_k
$$

核心问题：

> 哪些参数对旧任务重要？

保护方式：

> 参数空间中的 importance-weighted regularization。

---

### 2. iCaRL

保存：

$$
P_y
$$

核心问题：

> 怎样在新增类别时同时维持 Representation 和统一分类器？

保护方式：

- exemplar rehearsal；
- distillation；
- prototype classifier。

---

### 3. GEM

保存：

$$
M_k
$$

但 memory 的主要使用方式是：

$$
M_k
\rightarrow
L_k^M
\rightarrow
g_k
$$

核心问题：

> **当前这一步更新，会不会与过去任务的优化方向发生冲突？**

保护方式：

> 对当前 gradient 做动态约束与 projection。

所以可以形成：

```text
EWC：
历史知识 → Parameter Importance

iCaRL：
历史知识 → Exemplars + Prototype

GEM：
历史知识 → Episodic Memory
             ↓
          Past Gradients
             ↓
      Update Constraints
```

---

## 二十六、GEM 的方法边界

### 1. 依赖 Episodic Memory

GEM 不是 rehearsal-free 方法。

每个旧任务都需要保留：

$$
M_k
$$

因此存在：

- memory budget；
- 数据隐私；
- memory representativeness；

等问题。

---

### 2. Memory Selection 很基础

本文默认：

> 保存每个 task 最后的 $m$ 个样本。

没有系统研究：

- herding；
- reservoir sampling；
- gradient-based coreset；
- diversity selection。

作者自己把 advanced memory management 列为未来工作。

---

### 3. 依赖 Task Descriptor

正式 framework 使用：

$$
f(x,t)
$$

所以标准 GEM 实验通常默认知道当前 task identity。

这和严格 task-free / class-incremental setting 有明显区别。

---

### 4. 约束只是一阶局部保证

即使：

$$
g_k^T\tilde g\ge0
$$

成立，也只是根据局部一阶近似判断：

> 这一小步不应该增加旧 memory loss。

它不是旧任务全分布上的严格全局保证。

---

### 5. 每个旧 Task 都要计算 Gradient

随着 task 数增加：

$$
t\uparrow
$$

每个训练 step 的 backward 数量也增加。

论文自己明确把这一点列为后续主要改进方向。

---

### 6. Structured Task Descriptor 没有真正利用

理论 framework 允许 richer task descriptor。

但本文没有深入使用它。

所以 FWT 的潜力没有被完整开发。

这也是作者结论部分提出的未来方向之一。

---

## 二十七、论文真正贡献了什么

### 1. 不只是提出 GEM 算法

论文首先系统化提出了一个 continual-learning evaluation framework。

它强调不能只问：

> 最后 Accuracy 是多少？

还要问：

```text
过去 Task 是否被忘记？
→ BWT

过去 Task 是否因后来学习而改善？
→ Positive BWT

已经学到的知识是否帮助未来 Task？
→ FWT
```

ACC、BWT、FWT 后来成为持续学习中很常见的评价视角。

---

### 2. 把 Catastrophic Forgetting 转成 Gradient Constraint

GEM 最大的方法创新是把：

> “不要忘记过去”

转成：

> **当前 gradient 不允许增加过去任务 memory loss。**

因此保护对象从静态：

```text
Parameter
Output
```

变成动态：

```text
每一次 Optimization Step
```

---

### 3. 允许 Transfer 而不只是冻结过去

它没有强制：

$$
L_k^{\text{new}}
=
L_k^{\text{old}}
$$

而只要求：

$$
L_k^{\text{new}}
\le
L_k^{\text{old}}
$$

于是：

> 旧任务继续改善是合法的。

实验中的正 BWT 正是在验证这一设计目标。

---

## 二十八、从实现角度重新串联整篇论文

真正实现 GEM，可以把整篇论文压缩成下面这个循环：

```text
系统已有：

当前模型 θ

Past Task Memories：
M_1,...,M_{t-1}


新的 Task t 到达
        ↓

初始化 / 维护 M_t

        ↓

当前 mini-batch B_t

        ↓

Forward
        ↓
Current Loss L_t

        ↓

Backward
        ↓
Current Gradient g

        ↓

for k = 1,...,t-1:

    从 M_k Forward
        ↓
    Past Memory Loss L_k^M
        ↓
    Backward
        ↓
    Past Gradient g_k

        ↓

检查所有：

g^T g_k ≥ 0 ?

        ↓

如果全部成立：

    \tilde g = g

否则：

    把 g 投影到
    所有 old-task constraints
    的 feasible region

    得到 \tilde g

        ↓

Parameter Update：

θ ← θ - α \tilde g

        ↓

保存当前 Task Memory

        ↓

继续下一个 batch

        ↓

Task t 结束

        ↓

在所有测试 Task 上评估
        ↓
填写 R_{t,:}

        ↓

继续 Task t+1
```

整个系统中需要长期保存的核心历史信息不是过去所有训练数据，也不是过去模型副本，而是：

$$
M_1,\ldots,M_t
$$

这些 episodic memories。

每一次训练更新时，它们被重新解释成：

$$
g_1,\ldots,g_{t-1}
$$

也就是：

> **过去任务在当前参数位置上提出的局部优化约束。**

---

## 二十九、整篇论文的核心逻辑链

```text
普通 ERM
假设 iid + 可反复访问数据
        ↓
Continual Learning 不满足这些条件
        ↓
顺序 Task 导致 Catastrophic Forgetting
        ↓
但新 Task 也可能帮助旧 Task
        ↓
因此不能简单冻结旧模型
        ↓
为每个 Past Task 保存少量 Episodic Memory
        ↓
在当前参数 θ 上
从 Memory 重新计算 Past-task Gradients
        ↓
检查 Current Gradient 是否与旧任务冲突
        ↓
不冲突：
直接学习 Current Task

冲突：
只对 Current Gradient 做最小必要修改
        ↓
Projected Gradient 同时满足
所有 Past-task Non-increase Constraints
        ↓
继续更新共享模型
        ↓
旧任务可以保持
也允许进一步改善
        ↓
用 ACC / BWT / FWT
分别衡量最终能力、Backward Transfer、
Forward Transfer
```

GEM 最值得留下的核心认识是：

$$
\boxed{
\text{持续学习中的“遗忘”可以在每一次优化步骤上被看成 Gradient Interference。}
}
$$

它因此把问题从：

> “训练完新任务之后再检查旧任务忘了多少”

提前到了：

> **“每一次准备更新参数之前，就检查这一步是否会伤害过去任务。”**

这正是 GEM 相比 LwF、EWC、iCaRL 在优化视角上的核心推进。
