---
schema_version: 1
id: ewc-review
title: Overcoming Catastrophic Forgetting in Neural Networks
type: paper-note
domains:
  - artificial-intelligence
topics:
  - continual-learning
tags:
  - regularization
sources:
  - ewc-2017
review:
  ai:
    status: passed
  human:
    status: approved
maintenance:
  status: current
provenance:
  origin: imported
  ai_assisted: true
external_artifacts: []
---
# Elastic Weight Consolidation

## 一、方法概述

Elastic Weight Consolidation limits changes to parameters that matter to earlier tasks. See [[fisher-information|Fisher Information]] and [@ewc-2017, Sec. 2].

### 1. Objective

The parameter $\theta$ minimizes the objective.

$$
L(\theta) = L_{new}(\theta) + \lambda\Omega(\theta)
$$

```mermaid
flowchart LR
    A[Old task] --> B[Consolidate]
```

```python
text = "[[this is code]] $not math$"
```
