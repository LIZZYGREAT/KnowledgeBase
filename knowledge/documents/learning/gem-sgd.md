---
schema_version: 1
id: gem-sgd
title: GEM 前置知识：从 SGD 更新到梯度约束与二次规划
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

# GEM 前置知识：从 SGD 更新到梯度约束与二次规划

> 对应论文：David Lopez-Paz, Marc'Aurelio Ranzato, *Gradient Episodic Memory for Continual Learning*, NeurIPS 2017  
> 本笔记不提前复述 GEM 的完整论文算法与实验。目标是把阅读论文真正需要的底层计算链讲清楚：**当前任务的一次梯度更新为什么可能伤害旧任务，如何用旧任务梯度检测这种干扰，为什么约束会写成梯度内积不等式，以及违反约束后为什么会转化成一个 Quadratic Program（QP）投影问题。**

## 一、从已经掌握的方法过渡到 GEM 的问题视角

### 1. LwF、EWC、iCaRL 已经分别保存了什么

前面几种持续学习方法的核心区别，可以从“过去的信息以什么形式留下来”理解。

LwF 保留的是旧模型的输出行为：

$$
f_{\text{new}}(x)
\approx
f_{\text{old}}(x)
$$

EWC 保留的是旧任务在参数空间中的局部约束：

$$
\theta_i^*,
\qquad
F_i
$$

iCaRL 则保留少量旧类原始样本：

$$
P_y
$$

并利用这些 exemplar 同时参与 rehearsal 和 prototype classification。

GEM 又换了一个观察层级。它关注的不是“这个参数能不能变”，也不是“这个输出必须保持成什么”，而是：

> **当前这一次梯度更新，如果真的执行，会不会让过去任务的 Loss 变差？**

于是问题进一步推进到：

```text
当前 Task 产生一个 Update Direction
        ↓
检查它与过去任务的优化方向是否冲突
        ↓
如果冲突，修改这一次 Gradient
```

要理解 GEM，最重要的前置知识因此不是新的网络结构，而是：

- Gradient 在参数空间中到底表示什么；
- SGD 的真正移动方向是什么；
- 一个方向如何影响另一个 Loss；
- Gradient Dot Product 为什么能判断干扰；
- 如何把“不允许伤害旧任务”写成约束；
- 如何寻找离原梯度最近、同时满足所有旧任务约束的新梯度；
- 为什么这个问题可以用 QP 与其 Dual 高效求解。

---

## 二、变量、形状与任务设定

### 1. 模型参数与 Gradient

设整个神经网络所有可训练参数为：

$$
\theta
=
(\theta_1,\theta_2,\ldots,\theta_p)
\in
\mathbb R^p
$$

实际程序中的参数并不是一个向量，而可能分散为：

```text
conv1.weight
conv1.bias
...
fc.weight
fc.bias
```

理论分析时，可以把所有 parameter tensors 按固定顺序 flatten 后拼接：

$$
\theta\in\mathbb R^p
$$

同理，反向传播得到的所有参数梯度也可以 flatten 并拼成：

$$
g\in\mathbb R^p
$$

因此“两个任务的梯度做内积”的实际含义是：

> 把两个任务对同一组模型参数产生的梯度，按照完全相同的参数顺序展开后，在 $\mathbb R^p$ 中计算向量内积。

---

### 2. 当前任务与过去任务

设当前正在学习任务：

$$
t
$$

过去已经学习过：

$$
1,\ldots,t-1
$$

这些任务。

当前样本或 mini-batch 的 Loss：

$$
L_t(\theta)
$$

当前梯度：

$$
g
=
\nabla_\theta L_t(\theta)
\in\mathbb R^p
$$

过去任务 $k$ 只保留一个有限 episodic memory：

$$
M_k
$$

使用 memory 计算过去任务的近似 Loss：

$$
L_k^M(\theta)
=
\frac{1}{|M_k|}
\sum_{(x_i,y_i)\in M_k}
\ell(f_\theta(x_i,k),y_i)
$$

对应梯度：

$$
g_k
=
\nabla_\theta L_k^M(\theta)
\in\mathbb R^p
$$

需要区分：

$$
L_k^M
$$

和真正旧任务完整数据分布上的 Loss。$M_k$ 只是有限样本集合，所以 $L_k^M$ 只是旧任务真实风险的估计。

---

### 3. Task Descriptor 与 iCaRL 设定的区别

GEM 论文的基本样本形式是：

$$
(x_i,t_i,y_i)
$$

除了输入 $x_i$ 和标签 $y_i$，还给模型一个 task descriptor：

$$
t_i
$$

模型写成：

$$
f_\theta(x,t)
$$

这和 iCaRL 的 Class-Incremental Learning 需要明确区分。

iCaRL 更强调：

```text
输入 x
  ↓
不知道它来自哪个历史 Task
  ↓
直接在全部已见类别中统一分类
```

GEM 论文的正式框架允许：

```text
输入 x
+
Task Descriptor t
        ↓
模型知道当前需要解决哪个 Task
```

最简单的 $t$ 只是任务编号。在多头网络中，$t$ 可以用于选择对应的 task-specific output head。

因此阅读 GEM 时，不能把“任务序列上的梯度约束”直接等同于“纯 Class-Incremental Learning 中不知道 Task ID 的统一分类问题”。

---

## 三、Gradient 到底是什么：从 Backprop 到参数空间方向

### 1. 一个 Loss 对所有参数的偏导数组成 Gradient

给定：

$$
L(\theta)
$$

Gradient 定义为：

$$
\nabla_\theta L
=
\begin{bmatrix}
\frac{\partial L}{\partial\theta_1}\\
\frac{\partial L}{\partial\theta_2}\\
\vdots\\
\frac{\partial L}{\partial\theta_p}
\end{bmatrix}
$$

所以 Gradient 同时包含：

> 如果分别轻微改变每个参数，Loss 会以多快的速度变化。

Gradient 和参数 $\theta$ 具有相同总维度 $p$，因此它本身可以看作参数空间中的一个向量。

---

### 2. Gradient 指向 Loss 增长最快的方向

当前位置：

$$
\theta
$$

的 Gradient：

$$
g=\nabla_\theta L(\theta)
$$

指向局部范围内 Loss 上升最快的方向。

Gradient Descent 真正执行的是反方向：

$$
\theta'
=
\theta-\alpha g
$$

其中：

$$
\alpha>0
$$

是 learning rate。

必须始终记住：

```text
Gradient g
→ Loss 增长方向

真正参数 Update
→ -g
```

GEM 中很多“为什么内积应该 $\ge0$ 而不是 $\le0$”的困惑，都来自把 $g$ 和真正参数移动方向 $-g$ 混在一起。

---

### 3. 当前任务的普通 SGD 更新

当前任务 Loss：

$$
L_t(\theta)
$$

产生：

$$
g
=
\nabla_\theta L_t(\theta)
$$

普通 SGD：

$$
\theta'
=
\theta-\alpha g
$$

它只回答：

> 怎样让当前 $L_t$ 局部下降最快？

它不会自动判断这一步对旧任务 $L_1,\ldots,L_{t-1}$ 的影响。

---

## 四、一阶 Taylor 展开：怎样判断一次更新会不会伤害旧任务

### 1. 准备执行一个参数更新

假设我们准备使用某个 gradient-like vector：

$$
d
$$

执行：

$$
\theta'
=
\theta-\alpha d
$$

如果没有任何约束：

$$
d=g
$$

就是当前任务原始梯度。

现在考虑旧任务 $k$ 的 memory loss：

$$
L_k^M(\theta)
$$

真正要判断的是：

$$
L_k^M(\theta')
-
L_k^M(\theta)
$$

的正负。

---

### 2. 一阶 Taylor 展开

对于参数的小变化：

$$
\Delta\theta
=
\theta'-\theta
$$

有：

$$
L_k^M(\theta+\Delta\theta)
\approx
L_k^M(\theta)
+
\nabla_\theta L_k^M(\theta)^T
\Delta\theta
$$

定义：

$$
g_k
=
\nabla_\theta L_k^M(\theta)
$$

而：

$$
\Delta\theta
=
-\alpha d
$$

所以：

$$
L_k^M(\theta')
\approx
L_k^M(\theta)
-
\alpha g_k^T d
$$

因此旧任务 Loss 的局部变化量：

$$
\boxed{
\Delta L_k^M
\approx
-\alpha g_k^T d
}
$$

这是理解 GEM 最关键的基础公式。

---

### 3. 从 Loss 不增加推导 Gradient Constraint

希望旧任务不变差：

$$
L_k^M(\theta')
\le
L_k^M(\theta)
$$

按照一阶近似：

$$
-\alpha g_k^T d
\le
0
$$

因为 $\alpha>0$，所以：

$$
\boxed{
g_k^T d
\ge
0
}
$$

因此：

> “旧任务 Loss 不增加”

在局部一阶近似下，等价于：

> “准备采用的 gradient $d$ 与旧任务 gradient $g_k$ 的内积不能为负”。

这个不等式不是人为规定的，而是从 SGD 更新和 Taylor 展开直接推出来的。

---

## 五、Gradient Dot Product 与任务干扰

### 1. Dot Product 与夹角

两个 Gradient：

$$
d,\ g_k
$$

内积：

$$
d^Tg_k
=
\|d\|_2
\|g_k\|_2
\cos\varphi
$$

其中 $\varphi$ 是两个向量的夹角。

---

### 2. 内积大于 0：局部协同

如果：

$$
d^Tg_k>0
$$

则：

$$
\Delta L_k^M
\approx
-\alpha d^Tg_k
<0
$$

这一步不仅不会伤害旧任务，反而可能让旧任务 Loss 下降。

因此：

```text
Current Task Update
        ↓
同时降低 Past Task Loss
        ↓
Positive Backward Transfer
```

---

### 3. 内积等于 0：一阶上互不影响

如果：

$$
d^Tg_k=0
$$

则：

$$
\Delta L_k^M
\approx0
$$

说明在当前点的一阶局部近似中，这一步对旧任务没有明显影响。

这只是 first-order statement，更高阶项仍然可能产生变化。

---

### 4. 内积小于 0：Gradient Conflict

如果：

$$
d^Tg_k<0
$$

则：

$$
\Delta L_k^M
\approx
-\alpha d^Tg_k
>0
$$

意味着当前更新方向如果直接执行，旧任务 memory loss 很可能上升。

这就是 gradient interference / gradient conflict。

可以整理为：

```text
Current Task
产生 gradient g

Past Task k
产生 gradient g_k

g^T g_k < 0
        ↓
两个任务在当前参数位置的局部优化方向冲突
        ↓
直接执行 current gradient
        ↓
Past Task Loss 预计上升
```

---

## 六、Episodic Memory 在这里真正承担的作用

### 1. Memory 用来估计旧任务的局部优化方向

前面 iCaRL 中，exemplar 会直接重新进入训练 Loss，并参与 prototype classification。

GEM 中 episodic memory 更重要的用途是：

> **用少量旧样本估计旧任务在当前参数位置的 gradient。**

对于过去任务 $k$：

$$
M_k
$$

先计算：

$$
L_k^M(\theta)
$$

再反向传播得到：

$$
g_k
=
\nabla_\theta L_k^M(\theta)
$$

这个 $g_k$ 告诉我们：

> 如果现在想降低 task $k$ 在 memory 上的 Loss，参数局部应该往哪个方向移动。

因此 memory 提供的是：

$$
\boxed{
\text{Past Task Local Optimization Direction}
}
$$

---

### 2. 为什么 Memory 必须具有代表性

真正想保护的是完整旧任务分布：

$$
P_k(X,Y)
$$

但程序实际只有 $M_k$。

如果 $M_k$ 严重偏离旧任务数据分布，那么即使满足：

$$
g_k^Td\ge0
$$

也只能说明：

> 这一步没有伤害这些 memory samples。

不能保证完整旧任务一定不退化。

因此后面的 gradient constraint 建立在两个近似之上：

```text
有限 episodic memory
≈
旧任务分布

一阶 Taylor
≈
一次小参数更新后的 Loss 变化
```

---

### 3. 为什么简单把 Memory Loss 加进总 Loss 不等价

普通 replay 可以写成：

$$
L_{\text{total}}
=
L_t
+
\lambda
\sum_{k<t}L_k^M
$$

那么：

$$
\nabla L_{\text{total}}
=
g
+
\lambda
\sum_{k<t}g_k
$$

这意味着：

> 当前任务和旧 memory loss 一起作为优化目标。

而梯度约束表达的是另一种要求：

```text
主要目标：
尽量优化当前任务

约束：
过去任务不要变差

如果还能顺便让过去任务变好：
允许
```

这更接近：

$$
\min L_t
$$

subject to：

$$
L_k^{M,\text{new}}
\le
L_k^{M,\text{old}}
$$

所以“Replay Loss Addition”和“Constraint Optimization”不是同一种设计。

---

## 七、从 Loss Constraint 转成 Gradient Constraint

### 1. 理想约束写在 Loss 上

希望对每一个旧任务：

$$
k<t
$$

都有：

$$
L_k^M(\theta_{\text{new}})
\le
L_k^M(\theta_{\text{old}})
$$

直接求解完整非线性约束代价很大。

---

### 2. 用局部一阶近似替代

对于候选更新：

$$
\theta_{\text{new}}
=
\theta-\alpha d
$$

有：

$$
L_k^M(\theta_{\text{new}})
-
L_k^M(\theta)
\approx
-\alpha g_k^Td
$$

所以只需要：

$$
\boxed{
g_k^Td\ge0
}
$$

对所有 $k<t$ 成立。

于是复杂的 nonlinear loss constraints 被转换成 gradient space 中的 linear inequality constraints。

---

## 八、约束的几何意义：Half-space 与 Feasible Cone

### 1. 一个旧任务对应一个 Half-space

固定 $g_k$，约束：

$$
g_k^Td\ge0
$$

在 $\mathbb R^p$ 中定义一个 half-space。

边界：

$$
g_k^Td=0
$$

是经过原点的超平面。

一侧：

$$
g_k^Td>0
$$

表示对旧任务局部安全或有益。

另一侧：

$$
g_k^Td<0
$$

表示冲突。

---

### 2. 多个旧任务形成 Feasible Region

如果已经学习 $t-1$ 个旧任务，需要：

$$
g_1^Td\ge0,\quad
g_2^Td\ge0,\quad
\ldots,\quad
g_{t-1}^Td\ge0
$$

所有 half-spaces 的交集：

$$
\mathcal C
=
\left\{
d:
g_k^Td\ge0,\ \forall k<t
\right\}
$$

因为这些都是齐次线性不等式，$\mathcal C$ 是一个凸锥。

它表示：

> 能够同时不伤害所有旧任务 memory loss 的 gradient directions。

---

### 3. 当前 Gradient 已经可行时无需修改

如果：

$$
g_k^Tg\ge0,
\qquad
\forall k<t
$$

那么：

$$
g\in\mathcal C
$$

当前 gradient 可以直接使用。

所以 gradient constraint 并不是每一步都强行修改梯度。只有检测到 interference 时才需要修正。

---

## 九、Projection：冲突时为什么寻找“离原梯度最近”的方向

### 1. 原始 Gradient 不可行

如果至少存在某个旧任务：

$$
g_k^Tg<0
$$

那么当前梯度：

$$
g\notin\mathcal C
$$

需要找新的：

$$
\tilde g
$$

满足：

$$
g_k^T\tilde g\ge0,
\qquad
\forall k<t
$$

---

### 2. 仅满足约束还不够

例如：

$$
\tilde g=0
$$

永远满足所有约束，但模型也无法继续学习当前任务。

因此还要要求：

> 在所有安全方向中，尽量保留原始 current-task gradient 的学习意图。

定义为：

$$
\boxed{
\min_{\tilde g}
\frac{1}{2}
\|\tilde g-g\|_2^2
}
$$

subject to：

$$
g_k^T\tilde g\ge0,
\qquad
\forall k<t
$$

这就是 Euclidean Projection：

> 把原始 gradient 投影到 feasible region 上。

---

### 3. 为什么使用 L2 Distance

$$
\|\tilde g-g\|_2^2
$$

衡量修改后的 gradient 与原 gradient 相差多少。

目标不是“找一个最有利于旧任务的方向”，而是：

> **只做满足旧任务约束所必需的最小修改。**

所以优先级是：

```text
第一：
不能伤害旧任务 memory loss

第二：
在满足第一点的方向里，
尽量接近 current-task 原始 gradient
```

---

## 十、Quadratic Programming：Projection 为什么是 QP

### 1. 展开 Projection Objective

设：

$$
z=\tilde g
$$

目标：

$$
\frac{1}{2}
\|z-g\|_2^2
$$

展开：

$$
\frac{1}{2}
(z-g)^T(z-g)
$$

得到：

$$
\frac{1}{2}z^Tz
-
g^Tz
+
\frac{1}{2}g^Tg
$$

最后一项和 $z$ 无关，可以删掉。

于是：

$$
\min_z
\frac{1}{2}z^Tz-g^Tz
$$

---

### 2. 把所有旧任务 Gradient 组成矩阵

定义：

$$
G
=
\begin{bmatrix}
g_1^T\\
g_2^T\\
\vdots\\
g_{t-1}^T
\end{bmatrix}
\in
\mathbb R^{(t-1)\times p}
$$

那么：

$$
Gz
=
\begin{bmatrix}
g_1^Tz\\
g_2^Tz\\
\vdots\\
g_{t-1}^Tz
\end{bmatrix}
$$

所有约束可以写成：

$$
Gz\ge0
$$

完整问题：

$$
\boxed{
\begin{aligned}
\min_z\quad&
\frac{1}{2}z^Tz-g^Tz\\
\text{s.t.}\quad&
Gz\ge0
\end{aligned}
}
$$

目标是 quadratic function，约束是 linear inequalities，所以它就是一个 Quadratic Program。

---

### 3. 与标准 QP 对应

标准形式：

$$
\min_z
\frac{1}{2}z^TCz+p^Tz
$$

subject to：

$$
Az\ge b
$$

当前问题对应：

$$
C=I,\qquad
p=-g,\qquad
A=G,\qquad
b=0
$$

所以 QP 并不是额外发明的模块，它只是“离原梯度最近的安全梯度”的标准优化表达。

---

## 十一、为什么 Primal QP 直接求解不划算

### 1. Primal Variable 与神经网络参数同维

变量：

$$
z=\tilde g
\in\mathbb R^p
$$

如果模型有百万级参数，那么 primal QP 就有百万级优化变量。

---

### 2. 约束数量却只有过去任务数

虽然 $p$ 很大，但约束只有：

$$
t-1
$$

个。

通常：

$$
t-1\ll p
$$

例如：

```text
参数数量：
1,000,000

过去任务数量：
19
```

这说明问题存在明显低维结构，Dual Optimization 正是利用这一点。

---

## 十二、Lagrangian 与 Dual：怎样把百万维 QP 降到任务数维度

### 1. 从 Primal 开始

考虑：

$$
\min_z
\frac{1}{2}
\|z-g\|_2^2
$$

subject to：

$$
Gz\ge0
$$

把约束改写成：

$$
-Gz\le0
$$

为每个约束引入 multiplier：

$$
v_k\ge0
$$

组成：

$$
v\in\mathbb R^{t-1}
$$

---

### 2. 构造 Lagrangian

$$
\mathcal L(z,v)
=
\frac{1}{2}
\|z-g\|_2^2
-
v^TGz
$$

---

### 3. 先对 $z$ 求最优

对 $z$ 求导：

$$
\nabla_z\mathcal L
=
z-g-G^Tv
$$

令其为 0：

$$
z-g-G^Tv=0
$$

得到：

$$
\boxed{
z
=
g+G^Tv
}
$$

所以 projected gradient 可以写成：

$$
\tilde g
=
g
+
v_1g_1
+
v_2g_2
+\cdots+
v_{t-1}g_{t-1}
$$

这说明 projection 的本质是：

> 在当前 gradient 上加入过去任务 gradients 的某个线性组合，用来抵消冲突分量。

Dual 要决定的就是每个系数 $v_k$ 应该是多少。

---

### 4. 得到 Dual Problem

把：

$$
z=g+G^Tv
$$

代回 Lagrangian，去掉与优化无关的常数，可以得到：

$$
\boxed{
\min_{v\ge0}
\frac{1}{2}
v^TGG^Tv
+
g^TG^Tv
}
$$

现在：

$$
v\in\mathbb R^{t-1}
$$

所以：

```text
Primal：
变量数 = 神经网络参数数 p

Dual：
变量数 = 过去任务数 t-1
```

这就是 GEM 中 Dual QP 计算上更可行的根本原因。

---

### 5. Dual 解如何回到真正 Gradient

求得：

$$
v^*
$$

以后：

$$
\boxed{
\tilde g
=
g+G^Tv^*
}
$$

最后更新：

$$
\theta'
=
\theta-\alpha\tilde g
$$

Dual Solver 不直接更新网络，它只负责计算：

> current gradient 需要加入多少 past-gradient correction。

---

## 十三、KKT 条件需要理解到什么程度

阅读 GEM 不需要完整学习凸优化，但需要理解 Dual Multiplier 为什么代表“哪些约束真正起作用”。

### 1. Primal Feasibility

最终必须满足：

$$
G\tilde g\ge0
$$

---

### 2. Dual Feasibility

$$
v_k\ge0
$$

---

### 3. Stationarity

$$
\tilde g
=
g+G^Tv
$$

说明 projected gradient 来自 current gradient 加 active old-task corrections。

---

### 4. Complementary Slackness

对每个任务 $k$：

$$
v_k
(g_k^T\tilde g)
=
0
$$

如果某个约束最终很宽松：

$$
g_k^T\tilde g>0
$$

则通常：

$$
v_k=0
$$

这个旧任务不需要额外修正 current gradient。

如果某个冲突约束正好成为边界：

$$
g_k^T\tilde g=0
$$

对应 $v_k$ 可能为正，真正参与 projection。

所以 $v_k$ 可以理解为：

> 当前这一步训练中，旧任务 $k$ 的约束对 gradient correction 的作用强度。

---

## 十四、Task-specific Head 对 Gradient Inner Product 的影响

### 1. 所有任务 Gradient 必须放在同一参数坐标系

即使不同任务拥有不同 output heads，仍把整个模型参数写成：

$$
\theta\in\mathbb R^p
$$

对于某个任务完全不使用的 task-specific head，其对应 gradient 自然为 0。

因此一个 task gradient 可以看成：

```text
Shared Backbone Gradient
+
自己 Head 的 Gradient
+
其他 Task Heads 的 Zero Gradient
```

---

### 2. 跨任务冲突主要发生在共享参数

例如：

```text
Task A：
shared backbone + head_A

Task B：
shared backbone + head_B
```

那么 $g_A$ 在 head_B 对应坐标上为 0，$g_B$ 在 head_A 对应坐标上也为 0。

二者内积主要来自：

$$
\boxed{
\text{shared backbone parameter dimensions}
}
$$

所以 gradient conflict 实际测量的是：

> 不同任务是否试图以相互冲突的方式修改共享 Representation。

---

## 十五、Positive Backward Transfer 与“只防止遗忘”的差别

### 1. 约束不是要求旧任务完全不变

Gradient constraint 要求：

$$
g_k^T\tilde g\ge0
$$

等价于一阶意义上的：

$$
\Delta L_k^M\le0
$$

注意是：

$$
\le0
$$

而不是：

$$
=0
$$

因此允许：

$$
\Delta L_k^M<0
$$

也就是当前学习新任务时，旧任务 Loss 反而下降。

所以这种约束表达的是：

> **过去可以变化，但不能朝更差的方向变化。**

这就是 positive backward transfer 能够发生的根本原因。

---

## 十六、这条方法链中的近似与潜在问题

### 1. 一阶近似只在局部成立

核心判断：

$$
\Delta L_k^M
\approx
-\alpha g_k^Td
$$

依赖一次参数更新足够小。

如果 learning rate 太大，或者局部曲率很强，高阶项可能不可忽略。

所以即使：

$$
g_k^Td\ge0
$$

实际完整 Loss 也不一定严格不升。

---

### 2. Memory Gradient 只是旧任务 Gradient 的估计

真正旧任务风险与：

$$
L_k^M
$$

不完全相同。

如果 memory 很小或样本选择很差：

$$
\nabla L_k^M
$$

可能无法代表真正旧任务 gradient。

所以算法可能保护 memory，却仍然忘记 memory 之外的旧数据。

---

### 3. 每多一个旧任务，就多一次 Gradient 计算

当前梯度需要一次 backward。

每个旧任务 $k$ 又要从 $M_k$ 计算一次：

$$
g_k
$$

因此任务数量增加时，构造 $G$ 的 backward 成本会增长。

Dual QP 虽然维度只有过去任务数，但旧任务梯度本身仍然需要被计算出来。

---

### 4. Gradient Conflict 是当前位置相关的

两个任务并不是永远冲突或永远一致。

因为：

$$
g_t(\theta)
$$

和：

$$
g_k(\theta)
$$

都依赖当前参数 $\theta$。

训练继续进行以后，它们的夹角也会变化。

所以 gradient interference 是：

> **当前参数位置上的局部关系。**

---

## 十七、从真正实现的角度理解需要哪些操作

### 1. 得到 Current Gradient

当前 mini-batch：

$$
B_t
$$

计算：

$$
L_t
$$

反向传播：

$$
g=\nabla_\theta L_t
$$

再把所有 parameter gradients 按固定顺序 flatten：

$$
g\in\mathbb R^p
$$

---

### 2. 得到 Past-task Gradients

对每个：

$$
M_k
$$

计算：

$$
L_k^M
$$

分别 backward：

$$
g_k
=
\nabla_\theta L_k^M
$$

同样 flatten 后组成：

$$
G
\in
\mathbb R^{(t-1)\times p}
$$

---

### 3. 检查是否存在冲突

计算：

$$
Gg
=
\begin{bmatrix}
g_1^Tg\\
\vdots\\
g_{t-1}^Tg
\end{bmatrix}
$$

如果逐元素：

$$
Gg\ge0
$$

则 current gradient 已经可行。

如果存在：

$$
(Gg)_k<0
$$

说明至少一个旧任务与当前 gradient 冲突。

---

### 4. 冲突时求 Projection

求：

$$
v^*
=
\arg\min_{v\ge0}
\left[
\frac12
v^TGG^Tv
+
g^TG^Tv
\right]
$$

然后：

$$
\tilde g
=
g+G^Tv^*
$$

---

### 5. 把 Projected Gradient 写回模型

理论上的 $\tilde g$ 是 flatten vector。

程序中还要按照原 parameter shapes 把它重新切开：

```text
tilde_g
 ↓
slice
 ↓
reshape
 ↓
parameter.grad
```

最后执行：

$$
\theta
\leftarrow
\theta-\alpha\tilde g
$$

所以 GEM 类型方法的关键干预位置位于：

> **backward 与 parameter update 之间。**

---

## 十八、与 EWC、iCaRL 的实现位置对照

### 1. EWC

EWC 修改：

$$
L_{\text{total}}
$$

通过：

$$
L_{\text{new}}
+
L_{\text{EWC}}
$$

让 backward 自然得到受约束的 gradient。

干预位置是：

```text
Loss Construction
```

---

### 2. iCaRL

iCaRL 修改：

- training data；
- distillation targets；
- representation-learning loss；
- inference classifier。

干预分布在：

```text
Data
+
Loss
+
Memory
+
Prediction Rule
```

---

### 3. Gradient-Constrained 方法

关键位置是：

```text
Forward
 ↓
Loss
 ↓
Backward
 ↓
得到 Current Gradient
        ← 在这里检查 Past Gradients
 ↓
Gradient Projection
 ↓
Optimizer Step
```

所以它不是给参数附加一个固定“重要性”，而是：

> 每一次准备更新之前，动态判断当前这一步是否与过去任务冲突。

---

## 十九、阅读 GEM 原论文前应形成的完整逻辑链

```text
当前 Task 给出 mini-batch
        ↓
计算 current loss L_t
        ↓
Backward 得到 current gradient g
        ↓
普通 SGD 想执行：
θ' = θ - αg
        ↓
过去 Task k 也有自己的 loss
        ↓
从 episodic memory M_k
估计过去任务 loss L_k^M
        ↓
Backward 得到 past gradient g_k
        ↓
用一阶 Taylor：

L_k^M(θ - αg)
≈
L_k^M(θ) - α g_k^T g

        ↓
如果 g_k^T g < 0
        ↓
当前更新预计让旧任务 loss 上升
        ↓
发生 Gradient Conflict
        ↓
要求新的 gradient d 满足：

g_k^T d ≥ 0
for every past task k

        ↓
多个线性不等式
形成 gradient space 中的 feasible region
        ↓
如果 g 已经在 region 内：
直接使用

如果 g 在 region 外：
        ↓
寻找距离 g 最近的可行 gradient
        ↓

min 1/2 ||d-g||²
s.t. Gd ≥ 0

        ↓
这是 Quadratic Program
        ↓
Primal variable 数量 = 参数数 p
太大
        ↓
利用 Dual
把变量数降到 past task 数量 t-1
        ↓
求 v*
        ↓
恢复：

\tilde g = g + G^T v*

        ↓
把 \tilde g 写回 parameter.grad
        ↓
正常更新参数
```

如果这条链能够逐步解释清楚，那么阅读 GEM 的核心方法部分时，真正需要关注的就会转变成：

- episodic memory 怎样分配；
- 每个 task gradient 在论文训练协议中如何计算；
- 为什么论文选择 inequality constraint 而不是 replay loss 或 distillation；
- 为什么这种设计允许 positive backward transfer；
- QP 在每次训练更新中什么时候执行；
- 任务数量增加时计算成本如何变化；
- ACC、BWT、FWT 的实验究竟验证了哪些能力。

这些内容再留到论文精读笔记中展开。
