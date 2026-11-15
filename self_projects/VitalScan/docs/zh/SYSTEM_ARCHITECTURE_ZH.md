<!-- Compiled Documentation: SYSTEM_ARCHITECTURE_ZH.md -->

<div align="center">

# 🏗️ 系统架构与设计
### 马尼拉大都会搜索与救援无人机集群

[![LangGraph](https://img.shields.io/badge/LangGraph-ReAct_Agents-blueviolet?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Mesa](https://img.shields.io/badge/Mesa-3.0_Simulation-orange?style=for-the-badge)](https://mesa.readthedocs.io)
[![FastMCP](https://img.shields.io/badge/FastMCP-SSE_Protocol-red?style=for-the-badge)](https://github.com/jlowin/fastmcp)
[![FastAPI](https://img.shields.io/badge/FastAPI-Live_Dashboard-009688?style=for-the-badge)](https://fastapi.tiangolo.com)

</div>

---

## 全局系统架构

```mermaid
graph TD
    %% Styles
    classDef agent  fill:#2d1b4e,stroke:#9d72ff,stroke-width:2px,color:#fff
    classDef llm    fill:#0a3622,stroke:#2ea043,stroke-width:2px,color:#fff
    classDef mcp    fill:#3b1d12,stroke:#d25a2c,stroke-width:2px,color:#fff
    classDef db     fill:#4a3f05,stroke:#cca700,stroke-width:2px,color:#fff
    classDef sim    fill:#0a2540,stroke:#3b82f6,stroke-width:2px,color:#fff
    classDef ui     fill:#451a3d,stroke:#e9328f,stroke-width:2px,color:#fff
    classDef prompt fill:#1e1e1e,stroke:#555,stroke-width:1px,color:#ddd

    subgraph Swarm["🧠 LangGraph 集群大脑"]
        LLM[("异构大模型\nGemini 2.5 · Qwen3 · Llama3")]:::llm

        subgraph Prompts["系统提示词"]
            DP["DRONE_ONSITE_SYSTEM\n'你是救援无人机 {drone_id}...\n1. 测绘扫描\n2. 检查电量\n3. 结构化报告'"]:::prompt
            CP["COMMANDER_SYSTEM\n'你是指挥机 CMD...\n1. 弧线巡航\n2. 监控编队\n3. 报告状态'"]:::prompt
        end

        subgraph Agents["异步智能体 (5 + 1 CMD)"]
            DA1["🚁 drone_21 · R1\n东北扇区 0°–90°"]:::agent
            DA2["🚁 drone_22 · R2\n东南扇区 90°–180°"]:::agent
            DA3["🚁 drone_23 · R3\n西南扇区 180°–270°"]:::agent
            DA4["🚁 drone_24 · R4\n西北扇区 270°–360°"]:::agent
            DA5["🚁 drone_25 · R5\n北扇区 −45°–45°"]:::agent
            CCA["🎖️ CMD 指挥机\n弧线领航员"]:::agent
        end

        DA1 & DA2 & DA3 & DA4 & DA5 -. reads .-> DP
        CCA -. reads .-> CP
        LLM --- DA1 & DA2 & DA3 & DA4 & DA5 & CCA
    end

    subgraph Interface["📡 接口层"]
        MCP["FastMCP 服务器\n端口 8766\nSSE 流"]:::mcp

        subgraph Tools["26 个暴露的 MCP 工具"]
            T1[move_drone_to]
            T2[thermal_scan]
            T3[recall_drone_to_base]
            T4[override_drone_target]
            T5[get_mapping_status]
            T6[get_scanned_areas_db]
            T7[get_team_waypoint]
            T8[get_mission_status]
        end

        DB[("SQLite 数据库\n扫描记录 · 事件 · 幸存者")]:::db
    end

    subgraph Physics["🌍 Mesa 物理引擎"]
        SIM["连续 GPS 坐标系\nHaversine · A* · OSRM"]:::sim
        DR1(("D1")):::sim
        DR2(("D2")):::sim
        DR3(("D3")):::sim
        DR4(("D4")):::sim
        DR5(("D5")):::sim
        SIM --- DR1 & DR2 & DR3 & DR4 & DR5
    end

    subgraph View["📊 仪表盘前端 (端口 8765)"]
        UI["FastAPI\nMapLibre 3D + 战术指挥中心"]:::ui
        WS["WebSocket\n地图状态流"]
        HTTP["HTTP 流\n逐词 AI 输出"]
    end

    Agents ==>|"异步 SSE 工具调用"| Tools
    Tools -.->|"执行代码函数"| SIM
    T2 -.->|"记录扫描"| DB
    T6 -.->|"读取 SQL"| DB
    SIM ==>|"地图状态"| WS
    Agents -->|"StreamingCallback\n逐词 Token"| HTTP
    WS --> UI
    HTTP --> UI
```

---

## 智能体提示词逻辑

### 🚁 救援无人机 — `DRONE_ONSITE_SYSTEM`

每架救援无人机在每个航点执行战术报告提示词：

```
1. SCAN       执行 thermal_scan(drone_id)
              → 统计幸存者、标记危急、检测聚集区 (50m 内 3 人以上)

2. ASSESS     评估: 发现了多少人？有危急人员吗？

3. BATTERY    执行 get_battery_status(drone_id)
              → 若存在警报: 汇报警报，切勿前往下一航点

4. REPORT     以严格的结构化格式输出报告
```

**层级替换机制 (Battery Swap):** 如果外圈无人机电量降至 `≤ 50%`，物理引擎将强制自动召回它，并提升最近的中圈无人机到外圈。无人机**不会**手动调用召回命令——全由物理引擎接管。

**地震与故障强制覆盖:** 物理引擎独立于 AI 处理动态事件。如果进入地震带，所有无人机将冻结进行地质测量，随后收敛聚集，然后再返回各自的扫描路线。硬件故障发生在第 10 次扫描时，强制触发 A* 返航。

---

### 🎖️ 指挥无人机 — `COMMANDER_SYSTEM`

指挥 (CMD) 无人机**不执行扫描任务**。它按弧线巡航并监控整个编队：

```
每一个循环:
  步骤 1 → get_arc_waypoints(drone_id)       — 获取下一个弧线位置
  步骤 2 → move_drone_to(drone_id, x, y)     — 飞向该位置
  步骤 3 → advance_arc_waypoint(drone_id)    — 推进弧线光标
  步骤 4 → get_all_drones_status()           — 监控机队替换情况
  步骤 5 → get_battery_status(drone_id)      — 若 ≤ 50%: 自动召回自身
```

---

## 直播流架构 (Live Streaming)

本系统的标志性功能是 **大模型思维链实时流传输** — 无需等待完整响应生成。

```mermaid
sequenceDiagram
    participant LLM as 🤖 Gemini / Qwen3 / Gemma 4
    participant CB  as StreamingCallback
    participant Q   as asyncio.Queue
    participant W   as _stream_worker (aiohttp)
    participant API as FastAPI /api/ai_stream
    participant UI  as X-Ray Console (指挥台)

    loop 每个生成的 Token
        LLM->>CB: on_llm_new_token(token)
        CB->>Q: put_nowait({drone_id, chunk})
    end

    loop 异步工作进程
        Q->>W: await get()
        W->>API: HTTP POST {drone_id, chunk}
        API->>UI: 逐字追加到前端控制台
    end
```

---

## 并发模型 (Concurrency)

```mermaid
graph LR
    subgraph ASYNC["asyncio 事件循环"]
        D1["drone_21 任务"]
        D2["drone_22 任务"]
        D3["drone_23 任务"]
        D4["drone_24 任务"]
        D5["drone_25 任务"]
        CMD["CMD 任务"]
    end

    MCP_SEM["MCP 信号量\n最多 3 个并发调用"]
    LLM_SEM["LLM 信号量\n最多 2 个并发请求"]

    D1 & D2 & D3 & D4 & D5 & CMD --> MCP_SEM
    D1 & D2 & D3 & D4 & D5 & CMD --> LLM_SEM
```

> **信号量 (Semaphores)** 可防止 Ollama 本地服务器与 MCP SSE 端点的连接耗尽崩溃。


---

<div align="center">

# 🛰️ 技术栈深度解析 (Tech Stack Deep Dive)
### 马尼拉大都会搜索与救援无人机集群

</div>

---

## 1. 模拟引擎 — Mesa 3.0

### 🗺️ 这是什么？

Mesa 是一个 Python **基于智能体的建模 (Agent-based modeling)** 框架。相较于全局方程式，每个实体（无人机、幸存者）都是一个带有状态和 `step()` 函数的 *独立智能体*。在每个模拟滴答 (tick) 中，每个智能体都会独立采取行动。

```mermaid
classDiagram
    class mesa_Agent {
        <<abstract>>
        +unique_id: int
        +model: Model
        +step()
    }

    class DroneAgent {
        +x: float
        +y: float
        +battery: float
        +status: DroneStatus
        +target: tuple
        +step()
        +_step_toward(tx, ty)
        +_thermal_scan_area()
        +_auto_battery_swap()
    }

    class SurvivorAgent {
        +x: float
        +y: float
        +rescued: bool
        +critical: bool
        +step()
    }

    class MetroManilaRescueModel {
        +space: ContinuousSpace
        +schedule: RandomActivation
        +drones: list
        +survivors: list
        +step()
    }

    mesa_Agent <|-- DroneAgent
    mesa_Agent <|-- SurvivorAgent
    MetroManilaRescueModel "1" *-- "5" DroneAgent
    MetroManilaRescueModel "1" *-- "600" SurvivorAgent
```

---

### 📐 地理空间 (Geographic Space)

模拟运行在 **真实的 GPS 坐标** 中——而非简化的网格。每个位置都是马尼拉大都会上空真实的经纬度。

```
地理边界 (马尼拉市)
─────────────────────────────────────────────────────
  西南角 →  14.550°N, 120.950°E
  东北角 →  14.630°N, 121.010°E
  宽度   →  ≈ 6.0 km  (东西跨度)
  高度   →  ≈ 8.9 km  (南北跨度)
  面积   →  ≈ 53.4 km²
─────────────────────────────────────────────────────
```

---

### 🧭 寻路算法 — 双层策略

无人机不会瞬间移动。它们通过双层寻路系统沿真实计算的路径飞行：

```mermaid
flowchart TD
    START([无人机接收到移动指令]) --> OSRM

    OSRM["🌐 第一层: OSRM 开放 API\n基于真实街道的高清物理路由\n返回 GeoJSON 路径"]
    OSRM -->|"✅ 成功"| PATH_OSRM["使用 OSRM 航点\n真实物理街道几何"]

    OSRM -->|"❌ 超时或失败"| ASTAR

    ASTAR["🔧 第二层: A* 算法\n在 GPS 边界上建立 15×15 虚拟网格\n8 向移动 + Haversine 启发式函数"]
    ASTAR --> PATH_ASTAR["使用 A* 航点\n直线模拟"]

    PATH_OSRM --> STEP["DroneAgent._step_toward()\n每个滴答沿路径移动 0.05 公里\n每公里扣除 0.5% 电量"]
    PATH_ASTAR --> STEP
```

---

### 🏹 编队策略 — 3-2-1 弧形阵型

所有 5 架无人机从基站呈同心圆向外扩展扫描。

```mermaid
graph TD
    subgraph RINGS ["3-2-1 阵型 — 向外扩展"]
        BASE2(["📍 基地站"])
        INNER["🟢 内圈 (0.5 km)"]
        MIDDLE["🟡 中圈 (1.0 km)"]
        OUTER["🔴 外圈 (1.5 km)\n首批响应者 (R1, R2, R3)"]
        BASE2 --> INNER --> MIDDLE --> OUTER
    end
```

**电池替换逻辑 (Battery Swap):**
```
如果外圈无人机电量 ≤ 50%:
  → 自动召回基地
  → 晋升最近的中圈无人机前往外圈
  → 将剩余外圈航点分配给被晋升的无人机
  → 旧无人机充电至 80% 后被重新分配为内圈
```

---

### 📐 距离公式 — Haversine

所有的测距都使用 **Haversine 公式** 以确保地球球面 GPS 距离的绝对准确性（在马尼拉 14.6°N 纬度下极为重要，直接替代了不准确的欧几里得近似计算）。

---

## 2. 🔌 MCP 服务器 — 工具协议

**MCP (模型上下文协议)** 是由 Anthropic 提出的一种开放标准，允许 LLM 通过结构化 JSON 调用外部函数，它专为 AI 智能体设计。

```mermaid
sequenceDiagram
    participant AI as 🤖 无人机智能体
    participant MCP as 📡 FastMCP 服务器 :8766
    participant SIM as 🌍 Mesa 物理引擎
    participant DB as 💾 SQLite 数据库

    AI->>MCP: HTTP POST /tool_call<br/>{"tool": "thermal_scan", "args": {"drone_id": "drone_1"}}
    MCP->>SIM: 触发 Python 函数<br/>mcp_thermal_scan("drone_1")
    SIM->>DB: 记录扫描坐标
    SIM-->>MCP: 返回发现的幸存者
    MCP-->>AI: SSE 流返回 JSON
    AI->>AI: 解析结果 → 做出下一步决策
```


---

<div align="center">

# 📡 MCP 工具参考指南 (MCP Tools Reference)
### FastMCP 服务器接口

</div>

---

## 🗂️ 26 个 MCP 工具类别分类

| # | 类别 | 工具数 | 描述 |
|---|----------|:-----:|-------------|
| 1 | 🔍 机队发现 | 1 | 发现所有活跃的无人机 ID |
| 2 | 🔋 电池与状态 | 3 | 检查无人机健康和位置 |
| 3 | 🚁 移动控制 | 3 | 导航无人机穿梭地图 |
| 4 | 🌡️ 热成像扫描 | 1 | 探测附近的红外幸存者信号 |
| 5 | 📊 任务情报 | 5 | 获取进度、扇区、以及已知幸存者 |
| 6 | 🧭 扫描导航策略 | 5 | 三种路径规划策略 |
| 7 | 👥 团队扇区扫描 | 3 | 协调 5 架无人机收敛至单扇区 |
| 8 | ⚙️ 模拟控制 | 1 | 暂停 / 恢复模拟 |

---

## 重点工具演示 (Highlighted Tools)

### 🔋 电池与状态 (Battery & Status)
> **规则:** 绝不要在电量 ≤ 20% 时指派任务。务必先调用 `recall_drone_to_base`。

**`get_battery_status` 示例:**
```json
// 请求 (Request)
{ "tool": "get_battery_status", "arguments": { "drone_id": "drone_21" } }

// 响应 (低电量警告)
{ "drone_id": "drone_21", "battery": 18.2, "status": "low_batt", "warning": "Battery critical — recall immediately" }
```

### 🚁 移动控制 (Movement)
> **消耗:** 每飞行 1 公里消耗 `0.5%` 电量（基于 Haversine 距离）。

**`move_drone_to` 示例:**
```json
// 请求
{ "tool": "move_drone_to", "arguments": { "drone_id": "drone_21", "x": 121.001, "y": 14.612 } }

// 响应 (成功)
"OK: drone_21 heading to (121.0010, 14.6120). Distance: 0.31 km. Est. battery cost: ~0.2%."

// 响应 (被拒绝)
"REFUSED: drone_21 battery 18% — recall to base first."
```

### 🌡️ 热成像扫描 (Thermal Scanning)

```json
// 请求
{ "tool": "thermal_scan", "arguments": { "drone_id": "drone_21" } }

// 响应 — 发现幸存者
{
  "drone_id": "drone_21",
  "position": { "x": 120.993, "y": 14.601 },
  "survivors_found": [
    { "id": "survivor_14", "x": 121.001, "y": 14.610, "critical": true,  "rescued": false }
  ],
  "scan_radius_km": 0.1,
  "tick": 142
}
```

---

## 🔄 任务阶段流 (Mission Phase Flow)

> 系统分为两大阶段：第一阶段负责全面测绘（通过扇区工具扫描盲区），第二阶段负责精准救援（提取 `get_known_survivors` 数据后进行针对性飞行）。

```mermaid
sequenceDiagram
    participant AI as 🤖 智能体
    participant MCP as 📡 工具
    
    rect rgb(235, 245, 255)
        Note over AI,MCP: 阶段 1 — 测绘 (MAP)
        AI->>MCP: get_active_drones()
        AI->>MCP: get_all_drones_status()
        loop 每个扇区 Tick
            AI->>MCP: get_team_waypoint()
            MCP-->>AI: {x, y, ring}
            AI->>MCP: move_drone_to()
            AI->>MCP: thermal_scan()
            AI->>MCP: advance_zone_waypoint()
        end
    end

    rect rgb(255, 235, 235)
        Note over AI,MCP: 阶段 2 — 救援 (RESCUE)
        AI->>MCP: get_known_survivors()
        MCP-->>AI: [危重目标列表]
        loop 每个幸存者
            AI->>MCP: move_drone_to(target.x, target.y)
            AI->>MCP: thermal_scan()
        end
    end
```

---

*以上为完整的系统架构与技术栈细节，深入理解有助于进一步拓展或调试无人机行为。*

