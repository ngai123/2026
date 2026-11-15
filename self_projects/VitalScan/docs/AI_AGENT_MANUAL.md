<!-- Compiled Documentation: AI_AGENT_MANUAL.md -->

# 🤖 AI System Prompts — Logic & Philosophy

This document outlines the "Sense-Think-Act" loop used by the VitalScan drone swarm and details the exact logic provided to the AI models.

---

## 🔄 The Sense-Think-Act Loop

```mermaid
flowchart TD
    S["📡 SENSE\nSituational Report:\n- GPS & Battery\n- Sector waypoints\n- Global map & survivors\n- SQLite scan history"] 
    T["🧠 THINK\nPriority Directives:\n1. Safety (Return if low batt)\n2. Efficiency (Use sweep_next)\n3. Goal (Track hits & coverage)"]
    A["⚙️ ACT\nComposite Skills:\n- Execute atomic sequences\n(e.g. sweep_next handles move+scan)"]

    S -->|Analyzes State| T
    T -->|Selects Action| A
    A -->|Updates World| S
```

---

## 🎯 Core Systems & Directives

| System | Role / Identity | Primary Workflow | Core Directives & Focus |
|--------|-----------------|------------------|-------------------------|
| 🚁 **Drone Agent** <br>(*DRONE_ONSITE_SYSTEM*) | Direct field responder | Loop `sweep_next()` until sector is 100% mapped. | Format: Position `\|` Battery `\|` Survivors. |
| 🎖️ **Command Drone** <br>(*COMMANDER_SYSTEM*) | Formation supervisor | Route `safe_navigate()`, monitor via `fleet_overview()`. | Detect ring swaps; report fleet readiness. |
| 📐 **Fan Spread** <br>(*FAN_SPREAD_SYSTEM*) | Corridor coordination | Assign 2.0km → 0km depth slices per drone. | Center sweep on 1.0km disaster focal point; ensure zero gaps. |

---

## 📋 Best Practices for Modifying Prompts
1. **Be Terse**: AI models (especially smaller ones like Qwen) perform better with direct, non-conversational instructions.
2. **Use Markdown**: Structuring the prompt with `#` and `##` headers improves the model's intent recognition.
3. **Skill Priority**: Always mention the "Composite Skills" (the 8 high-level tools) first, as they are safer and more robust than raw atomic tools.


---

<div align="center">

# 🛠️ AI Agent Skills
### Metro Manila Search & Rescue Swarm

</div>

---

## 🧠 Skill Classification Mindmap

Drones operate using a hierarchy of skills. **Atomic Skills** are direct commands to the physics engine, while **Composite Skills** bundle multiple actions into higher-level workflows.

```mermaid
mindmap
  root((Drone Skills))
    Composite Skills (High-Level)
      Boustrophedon Sweep
      Team Sector Sync
      Arc Formation
      Safe Navigate
    Atomic Skills (Physics Engine)
      Movement
        move_drone_to
        recall_drone_to_base
        override_drone_target
      Scanning
        thermal_scan
      Intel & Status
        get_battery_status
        get_active_drones
        get_mission_status
```

---

## ⚡ Composite Skills vs Atomic Skills

The AI should prioritize **Composite Skills** over chaining atomic commands manually. Composite skills reduce token usage and prevent hallucination by combining logic on the backend.

### Visualizing a Composite Skill: `sweep_next()`

```mermaid
sequenceDiagram
    participant AI as 🤖 Agent
    participant COMP as ⚙️ Composite Skill
    participant SIM as 🌍 Physics

    AI->>COMP: Execute sweep_next()
    
    rect rgb(235, 245, 255)
        Note over COMP,SIM: Handled Internally
        COMP->>SIM: 1. Calculate A* / OSRM Route
        COMP->>SIM: 2. move_drone_to(target)
        COMP->>SIM: 3. thermal_scan()
        COMP->>SIM: 4. Check & record battery cost
        COMP->>SIM: 5. Log area to SQLite DB
    end
    
    COMP-->>AI: Returns condensed 1-line Situation Report
```

---

## 🧰 The Tactical Skill Matrix

| Category | Skill / Tool | Function | Threat / Cost |
|:---|:---|:---|:---|
| 🚁 **Flight** | `move_drone_to(x,y)` | Moves drone to specific GPS coordinates. | 🟡 `0.5% battery / km` |
| 🚁 **Flight** | `recall_drone_to_base()` | Emergency RTB for repairs or charging. | 🟢 Auto-charges at base |
| 🌡️ **Sensors** | `thermal_scan()` | Detects survivors within a 100m radius. | 🟢 Instant |
| 📊 **Intel** | `get_mapping_status()` | Retrieves global map completion percentage. | 🟢 Instant |
| 📊 **Intel** | `get_known_survivors()` | Pulls list of critical targets from SQLite. | 🟢 Instant |
| 👥 **Team** | `advance_team_sector()` | Progresses the entire 5-drone fleet to the next pie-slice. | 🔴 Blocks if team not ready |

---

## 🚨 Emergency Overrides (System Skills)

The following skills bypass the AI and are handled entirely by the backend environment. The AI cannot prevent them from occurring.

```mermaid
stateDiagram-v2
    state "Normal Operations" as Normal
    state "Critical Overrides" as Overrides {
        Earthquake: Seismic Converge
        Hardware: Malfunction RTB
        Battery: Auto Ring-Swap
    }

    Normal --> Overrides: Triggered by Physics/Environment
    Overrides --> Normal: Resumes Post-Event
```

---

## 🔗 Skill to MCP Tool Mapping Flowcharts

Every high-level **Composite Skill** acts as a wrapper that automatically sequences multiple low-level **MCP Tools**. Here is how the agent skills map directly to the 26 exposed MCP tools.

### 1. Boustrophedon Sweep (Rescue Drone Primary Skill)
This skill automates the "lawnmower" search pattern. Instead of the AI calculating geometry, it simply loops this skill to process a sector.

**MCP Tools Consumed:** `get_team_waypoint` ➔ `move_drone_to` ➔ `thermal_scan` ➔ `advance_zone_waypoint`

```mermaid
flowchart TD
    Start("Start Sweep Cycle")
    W["📡 get_team_waypoint(drone_id)"]
    M["🚁 move_drone_to(x, y)"]
    S["🌡️ thermal_scan(drone_id)"]
    A["⏭️ advance_zone_waypoint(drone_id)"]
    
    Start --> W
    W -->|Returns Next Target| M
    M -->|Arrived| S
    S -->|Logs Survivors to DB| A
    A -->|Cycle Complete| W
```

### 2. Team Sector Sync (Swarm Coordination Skill)
Ensures no single drone abandons its sector before the rest of the 5-drone formation finishes their slices.

**MCP Tools Consumed:** `get_team_sector_status` ➔ `get_active_drones` ➔ `advance_team_sector`

```mermaid
flowchart TD
    Start("Check Sync")
    S["📡 get_team_sector_status()"]
    D["🤖 get_active_drones()"]
    Check{"Are all 5 Drones\ndone with waypoints?"}
    Wait["⏳ Wait / Hover"]
    Adv["⏭️ advance_team_sector()"]

    Start --> S
    S --> D
    D --> Check
    Check -->|No| Wait
    Wait --> S
    Check -->|Yes| Adv
```

### 3. Arc Formation (Command Drone Navigation)
The CMD Drone uses this skill to fly its sweeping observational arc across the disaster zone without scanning for survivors.

**MCP Tools Consumed:** `get_arc_waypoints` ➔ `move_drone_to` ➔ `advance_arc_waypoint` ➔ `get_all_drones_status`

```mermaid
flowchart TD
    Start("CMD Arc Cycle")
    AW["📐 get_arc_waypoints(drone_id)"]
    M["🚁 move_drone_to(x, y)"]
    Adv["⏭️ advance_arc_waypoint(drone_id)"]
    Stat["📊 get_all_drones_status()"]

    Start --> AW
    AW -->|Returns Vector| M
    M --> Adv
    Adv --> Stat
    Stat -->|Detects Ring Swaps| AW
```


---

<div align="center">

# 🎖️ Drone Swarm Hierarchy
### Command vs Rescue Drones Relationships

</div>

---

## 🧠 Fleet Chain of Command

The VitalScan Swarm utilizes a 1-to-5 decentralized command structure. While all agents are autonomous, their objectives and permissions differ heavily based on their assigned ring and role.

```mermaid
mindmap
  root((Swarm Fleet))
    Command Drone (CMD)
      Role: Formation Leader
      Navigation: Arc Waypoints
      Focus: Monitor Ring Swaps
    Rescue Drones (R1-R5)
      OUTER Ring (1.5km)
        R1 (NE Sector)
        R2 (SE Sector)
        R3 (SW Sector)
      MIDDLE Ring (1.0km)
        R4 (NW Sector)
        R5 (N Sector)
```

---

## 📡 Observation & Communication Flow

The CMD drone does **not** command the Rescue Drones directly. Instead, it observes their status via the `FastMCP` server. The Physics Engine inherently handles the promotions (Ring Swaps), while the CMD drone reports the holistic state to the dashboard.

```mermaid
flowchart TD
    subgraph CMD ["🎖️ Command Drone"]
        OBS["Observer Loop\nCalls get_all_drones_status()"]
        REP["Dashboard Reporter\n'R1 has entered low battery.'"]
    end

    subgraph PHYS ["🌍 Physics Engine"]
        SWAP{"Ring Swap Override\nIs OUTER drone battery < 50%?"}
        ACT1["Recall OUTER to base"]
        ACT2["Promote nearest MIDDLE to OUTER"]
    end

    subgraph RESC ["🚁 Rescue Drones (R1-R5)"]
        SCAN["Loop: sweep_next()"]
    end

    RESC -->|Reports status to| OBS
    RESC -->|Drains Battery| SWAP
    SWAP -->|Yes| ACT1
    SWAP -->|Yes| ACT2
    ACT1 -.->|Updates State| OBS
    ACT2 -.->|Updates State| OBS
    OBS --> REP
```

---

## ⚖️ Role Comparison

| Characteristic | 🎖️ Command Drone (CMD) | 🚁 Rescue Drones (R1-R5) |
| :--- | :--- | :--- |
| **Primary Mission** | Oversee fleet readiness & maintain arc formation. | Scan for survivors & map sectors. |
| **Search Responsibility** | **None.** Does not call `thermal_scan()`. | **Full.** Executes scans at every waypoint. |
| **Navigation Pattern** | Radial Arc Formations (`get_arc_waypoints`). | Sector Sweeps (`get_team_waypoint`). |
| **Battery Threshold** | RTB at `≤ 50%` (Recall Self). | RTB at `≤ 50%` (Automatically recalled by Physics). |
| **Response to Earthquakes**| Pauses for Seismic Survey. | Pauses for Seismic Survey & Converges. |

---

> **See also:** [ARCHITECTURE.md](ARCHITECTURE.md) for the full system loop.


---

<div align="center">

# 🧠 AI Engineering Techniques
### Prompt, Context, and Harnessing Strategies in VitalScan

This document details the advanced LLM engineering techniques employed to transform standard text-generation models into highly autonomous, reliable rescue agents.

</div>

---

## 1. 📝 Prompt Engineering Skills

Prompt engineering in VitalScan focuses on constraining LLM hallucinations and forcing deterministic, actionable output.

### 🎯 Role-Playing & Persona Injection
Drones are given strict operational identities. We don't just ask the model to "route a drone"; we define its exact state within the swarm.
> *"You are rescue drone 21 — callsign R1. You are operating in Sector Alpha (0°–90°)."*

### 🔄 ReAct (Reasoning + Acting)
We utilize the LangGraph `create_react_agent` to enforce a strict chain-of-thought loop. The model is forced to output a `Thought` before making a `Tool Call`.

```mermaid
flowchart LR
    P["System Prompt"] --> T["💭 Thought\n(Reasoning)"]
    T --> A["🔧 Action\n(Tool Call)"]
    A --> O["👁️ Observation\n(Tool Result)"]
    O --> T
    O --> F["✅ Final Answer\n(Decision)"]
```

### 🧱 Markdown-Structured Directives
To help smaller models (like `qwen3:4b`) parse instructions, the system prompt heavily utilizes Markdown headers (`#`, `##`, `•`) rather than conversational paragraphs.

| Technique | Example | Benefit |
| :--- | :--- | :--- |
| **Negative Constraints** | `"Do NOT proceed if battery ≤ 20%"` | Prevents unsafe tool execution. |
| **Data Formatting** | `"Report in Position \| Battery \| Survivors format"` | Forces scannable, structured terminal outputs. |
| **Composite Priority** | `"Use sweep_next() instead of moving manually"` | Reduces token usage by bundling logic. |

---

## 2. 🗄️ Context Engineering Skills

Context engineering ensures the LLM has the exact data it needs to make a decision—without overflowing the context window.

### 💾 Persistent External Memory (SQLite)
LLMs suffer from context amnesia during long missions. Instead of putting the entire flight history in the context window, we save scans to `rescue_mission.db`.
- **How it works**: The LLM queries `get_scanned_areas_db()` to pull summarized, aggregated data about the map, keeping the active context window small and fresh.

### 📍 Dynamic Situational Injection
Before every decision, the LLM is injected with the most up-to-date telemetry. It doesn't need to "remember" where it is; it is told dynamically.

```mermaid
sequenceDiagram
    participant P as 🌍 Physics Engine
    participant C as 🧩 Context Builder
    participant AI as 🤖 LLM Context Window

    P->>C: Tick 142: Battery 74%, Pos (120.9, 14.6)
    P->>C: Active Sector: Alpha
    C->>AI: INJECT: "Current State: {batt: 74, sector: Alpha}"
    AI->>P: move_drone_to()
```

### 🛡️ Semantic Boundaries
We prevent hallucinations by denying context that doesn't belong to the drone. A drone in Sector Alpha cannot "see" the waypoints of Sector Delta, mathematically reducing the chance of cross-sector interference.

---

## 3. ⚙️ Harnessing Engineering Skills

Harnessing refers to how we physically bridge the non-deterministic LLM into the deterministic Python physics engine (Mesa).

### 🔌 Model Context Protocol (MCP)
Instead of relying on fragile string parsing, we use `FastMCP` to harness the model. The LLM interfaces with the physics engine strictly through JSON-schema validated Server-Sent Events (SSE). 
- If an LLM hallucinates an invalid coordinate, the MCP tool schema rejects it before it crashes the simulation.

### 🚦 Tool Interception & Graceful Failures
We never trust the LLM's tool calls blindly. Tools are harnessed with Python logic that returns natural-language errors back to the model, allowing it to self-correct.

| LLM Hallucination | Harness Interception | Result Sent to LLM |
| :--- | :--- | :--- |
| Tries to fly 5km with 10% battery | Physics layer calculates Haversine cost. | `"REFUSED: Battery critical. Execute recall_to_base()"` |
| Tries to scan outside its sector | Wrapper checks sector bounds. | `"ERROR: Target outside Sector Alpha boundaries."` |
| Tries to invent a tool `scan_all()` | MCP schema validator catches it. | `"ERROR: Tool not found. Available tools: thermal_scan..."` |

### 🔬 Telemetry Streaming (X-Ray Console)
To harness the reasoning of the AI for the human operator, we intercept the `StreamingCallback` of the LangGraph chain. Tokens are pushed word-by-word over WebSockets to the **Tactical Command Center**, allowing operators to monitor the AI's internal thoughts in real-time.


---

